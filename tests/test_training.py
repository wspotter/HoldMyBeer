"""Task versions isolate their sessions and retain source recordings."""
import pytest
from fastapi.testclient import TestClient

from holdmybeer.app import create_app
from holdmybeer.app import Store
from holdmybeer.training import is_mutable_training_session
from holdmybeer.proposals import create_proposal


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app)


def test_immutability_guard_is_safe_before_training_schema_exists(tmp_path):
    store = Store(tmp_path / "standalone")
    assert is_mutable_training_session(store, "not-a-session") is True


def create_app_task(client, name="Browser"):
    app = client.post("/api/training/apps", json={"name": name})
    assert app.status_code == 200, app.text
    return app.json()


def create_task(client, app_id, name="Save a draft"):
    response = client.post(f"/api/training/apps/{app_id}/tasks", json={
        "name": name, "description": "Save the requested item", "done": "Receipt matches inputs"})
    assert response.status_code == 200, response.text
    return response.json()


def test_one_app_has_independent_tasks_and_sessions(client):
    app = create_app_task(client)
    first = create_task(client, app["id"], "First task")
    second = create_task(client, app["id"], "Second task")
    assert first["session"]["id"] != second["session"]["id"]
    listed = client.get("/api/training/apps").json()["apps"][0]
    assert listed["id"] == app["id"]
    assert {t["name"] for t in listed["tasks"]} == {"First task", "Second task"}
    assert {t["session_id"] for t in listed["tasks"]} == {first["session"]["id"], second["session"]["id"]}
    assert client.post("/api/training/apps", json={"name": " Browser "}).status_code == 409
    assert client.get("/api/training/tasks/not-a-uuid").status_code == 422
    assert client.get("/api/training/tasks/00000000-0000-4000-8000-000000000000").status_code == 404


def test_edit_copies_media_to_a_new_session_and_prior_version_is_protected(client):
    app = create_app_task(client)
    task = create_task(client, app["id"])
    store = client.app.state.store
    old = task["session"]["id"]
    media = store.artifacts / f"{old}.webm"
    media.write_bytes(b"original recording")
    client.put(f"/api/sessions/{old}", json={"answers": {
        "teaching_goal": "Save the requested item", "teaching_done": "Receipt matches inputs",
        "teaching_recording_confirmed": "yes"}})
    edited_response = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1})
    assert edited_response.status_code == 200, edited_response.text
    edited = edited_response.json()
    new_id = edited["session"]["id"]
    assert new_id != old
    assert edited["versions"][1]["parent_version"] == 1
    assert edited["session"]["training"] == {"version": 2}
    assert edited["session"]["answers"]["teaching_recording_confirmed"] == "no"
    assert edited["session"]["runs"] == []
    assert (store.artifacts / f"{new_id}.webm").read_bytes() == b"original recording"
    (store.artifacts / f"{new_id}.webm").write_bytes(b"changed recording")
    assert media.read_bytes() == b"original recording"
    assert is_mutable_training_session(store, old) is False
    assert is_mutable_training_session(store, new_id) is True
    blocked_edit = client.put(f"/api/sessions/{old}", json={"notes": "must remain retained"})
    assert blocked_edit.status_code == 409
    blocked_media = client.post(f"/api/sessions/{old}/media", content=b"replacement",
                                headers={"content-type": "video/webm"})
    assert blocked_media.status_code == 409
    assert media.read_bytes() == b"original recording"
    assert client.put(f"/api/sessions/{new_id}", json={"notes": "latest draft stays editable"}).status_code == 200


def test_restore_clones_selected_source_without_inheriting_approval_or_trial(client):
    app = create_app_task(client)
    task = create_task(client, app["id"])
    store = client.app.state.store
    sid1 = task["session"]["id"]
    (store.artifacts / f"{sid1}.mp4").write_bytes(b"version one")
    v2 = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1}).json()
    sid2 = v2["session"]["id"]
    (store.artifacts / f"{sid2}.mp4").write_bytes(b"version two")
    with store.connect() as db:
        db.execute("UPDATE training_tasks SET working_version=1 WHERE id=?", (task["id"],))
    restored = client.post(f"/api/training/tasks/{task['id']}/restore",
                           json={"base_version": 2, "source_version": 1})
    assert restored.status_code == 200, restored.text
    value = restored.json()
    sid3 = value["session"]["id"]
    assert value["latest_version"] == 3
    assert value["working_version"] == 1
    assert value["versions"][-1]["parent_version"] == 1
    assert (store.artifacts / f"{sid3}.mp4").read_bytes() == b"version one"
    assert value["session"]["runs"] == []
    assert value["session"]["answers"]["teaching_recording_confirmed"] == "no"
    assert not list(store.artifacts.glob(f"{sid3}.*.understanding.json"))


def test_stale_edit_and_restore_conflicts_do_not_create_sessions(client):
    app = create_app_task(client)
    task = create_task(client, app["id"])
    first = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1}).json()
    before = len(client.get("/api/sessions").json()["sessions"])
    conflict = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1})
    assert conflict.status_code == 409
    missing = client.post(f"/api/training/tasks/{task['id']}/restore",
                          json={"base_version": 2, "source_version": 99})
    assert missing.status_code == 404
    assert len(client.get("/api/sessions").json()["sessions"]) == before
    assert first["latest_version"] == 2


def test_activation_requires_current_approved_understanding_and_matching_proof(client):
    app = create_app_task(client)
    task = create_task(client, app["id"])
    sid = task["session"]["id"]
    response = client.post(f"/api/training/tasks/{task['id']}/activate",
                           json={"version": 1, "run_id": "00000000-0000-4000-8000-000000000000"})
    assert response.status_code == 409
    sid = task["session"]["id"]
    client.put(f"/api/sessions/{sid}", json={"answers": {
        "teaching_goal": "Save the requested item", "teaching_done": "Receipt matches inputs",
        "teaching_recording_confirmed": "yes"}})
    media = client.post(f"/api/sessions/{sid}/media", content=b"recording",
                        headers={"content-type": "video/webm"})
    assert media.status_code == 200
    client.put(f"/api/sessions/{sid}", json={"answers": {
        "teaching_goal": "Save the requested item", "teaching_done": "Receipt matches inputs",
        "teaching_recording_confirmed": "yes"}})
    procedure = {"revision": 2, "steps": [
        {"goal": "Select media", "check": "File selected", "action": "select_media", "target": "Media", "input": "filename"},
        {"goal": "Enter caption", "check": "Caption visible", "action": "fill", "target": "Caption", "input": "caption"},
        {"goal": "Save", "check": "Receipt appears", "action": "click", "target": "Save draft"},
        {"goal": "Verify", "check": "Inputs match", "action": "verify_draft"}]}
    proposal = create_proposal(client.app.state.store.root, sid,
                               [{"timestamp": 1, "text": "Select media before entering the caption."}], [], procedure)
    assert client.put(f"/api/sessions/{sid}", json={"procedure": procedure}).status_code == 200
    approved = client.post(f"/api/sessions/{sid}/teaching-review/approve",
                           json={"proposal_id": proposal["id"], "consent": True})
    assert approved.status_code == 200, approved.text
    assert client.post(f"/api/training/tasks/{task['id']}/activate",
                       json={"version": 1, "run_id": "00000000-0000-4000-8000-000000000000"}).status_code == 409
    run_id = "10000000-0000-4000-8000-000000000000"
    client.app.state.store.save_run(sid, {"id": run_id, "status": "verified", "mode": "practice",
                                         "procedure": None})
    assert client.post(f"/api/training/tasks/{task['id']}/activate",
                       json={"version": 1, "run_id": run_id}).status_code == 409
    changed = client.get(f"/api/sessions/{sid}").json()["answers"]
    changed["teaching_done"] = "A fresh receipt has matching inputs"
    assert client.put(f"/api/sessions/{sid}", json={"answers": changed}).status_code == 200
    assert client.post(f"/api/training/tasks/{task['id']}/activate",
                       json={"version": 1, "run_id": run_id}).status_code == 409
    fresh_proposal = create_proposal(client.app.state.store.root, sid,
                                     [{"timestamp": 2, "text": "The save receipt follows the filled caption."}],
                                     [], procedure)
    assert client.post(f"/api/sessions/{sid}/teaching-review/approve",
                       json={"proposal_id": fresh_proposal["id"], "consent": True}).status_code == 200
    verified_id = "20000000-0000-4000-8000-000000000000"
    client.app.state.store.save_run(sid, {"id": verified_id, "status": "verified", "mode": "procedure",
                                         "revision": procedure["revision"], "procedure": procedure})
    activated = client.post(f"/api/training/tasks/{task['id']}/activate",
                            json={"version": 1, "run_id": verified_id})
    assert activated.status_code == 200, activated.text
    assert activated.json()["working_version"] == 1
    assert activated.json()["activation"]["capability"] == "supported_fixture_only"
    assert is_mutable_training_session(client.app.state.store, sid) is False
    with pytest.raises(ValueError, match="Edit task"):
        create_proposal(client.app.state.store.root, sid,
                        [{"timestamp": 3, "text": "A later proposal must not rewrite the working version."}],
                        [], procedure)
    assert client.put(f"/api/sessions/{sid}", json={"notes": "working version is locked"}).status_code == 409
    assert client.post(f"/api/sessions/{sid}/media", content=b"replacement",
                       headers={"content-type": "video/webm"}).status_code == 409
    next_draft = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1})
    assert next_draft.status_code == 200, next_draft.text
    next_value = next_draft.json()
    assert next_value["latest_version"] == 2
    assert next_value["working_version"] == 1
    next_sid = next_value["session"]["id"]
    with pytest.raises(ValueError, match="Edit task"):
        create_proposal(client.app.state.store.root, sid,
                        [{"timestamp": 4, "text": "Historical version stays frozen."}], [], procedure)
    new_draft_proposal = create_proposal(client.app.state.store.root, next_sid,
                                         [{"timestamp": 5, "text": "The new draft can be taught."}], [], procedure)
    assert new_draft_proposal["session_id"] == next_sid
    assert is_mutable_training_session(client.app.state.store, sid) is False
    assert is_mutable_training_session(client.app.state.store, next_sid) is True
    assert client.put(f"/api/sessions/{next_sid}", json={"notes": "new draft remains editable"}).status_code == 200
    next_answers = client.get(f"/api/sessions/{next_sid}").json()["answers"]
    next_answers["teaching_recording_confirmed"] = "yes"
    assert client.put(f"/api/sessions/{next_sid}", json={"answers": next_answers}).status_code == 200
    next_proposal = create_proposal(client.app.state.store.root, next_sid,
                                    [{"timestamp": 6, "text": "The edited version retains its own review."}],
                                    [], procedure)
    assert client.post(f"/api/sessions/{next_sid}/teaching-review/approve",
                       json={"proposal_id": next_proposal["id"], "consent": True}).status_code == 200
    next_run_id = "30000000-0000-4000-8000-000000000000"
    client.app.state.store.save_run(next_sid, {"id": next_run_id, "status": "verified", "mode": "procedure",
                                               "revision": procedure["revision"], "procedure": procedure})
    promoted = client.post(f"/api/training/tasks/{task['id']}/activate",
                           json={"version": 2, "run_id": next_run_id})
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["working_version"] == 2
    assert (client.app.state.store.artifacts / f"{sid}.webm").read_bytes() == b"recording"
    assert is_mutable_training_session(client.app.state.store, sid) is False
    assert is_mutable_training_session(client.app.state.store, next_sid) is False
    with pytest.raises(ValueError, match="Edit task"):
        create_proposal(client.app.state.store.root, next_sid,
                        [{"timestamp": 7, "text": "Promoted version is frozen too."}], [], procedure)
    assert client.get(f"/api/training/tasks/{task['id']}").status_code == 200

