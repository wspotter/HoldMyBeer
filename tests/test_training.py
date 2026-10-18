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


def create_task_name_only(client, app_id, name="Save a draft"):
    # A name-only task is allowed; description/done are not pre-recorded intent.
    response = client.post(f"/api/training/apps/{app_id}/tasks", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def test_name_only_task_starts_pending_intent(client):
    app = create_app_task(client)
    task = create_task_name_only(client, app["id"], "Export a PDF")
    answers = task["session"]["answers"]
    assert task["name"] == "Export a PDF"
    assert answers["teaching_goal"] == ""
    assert answers["teaching_done"] == ""
    assert answers["teaching_task_name"] == "Export a PDF"
    assert answers["teaching_recording_confirmed"] == "no"
    assert task["session"].get("media_url") is None


def test_name_only_task_rejects_blank_name(client):
    app = create_app_task(client)
    assert client.post(f"/api/training/apps/{app['id']}/tasks", json={"name": "   "}).status_code == 422
    assert client.post(f"/api/training/apps/{app['id']}/tasks", json={}).status_code == 422


def test_explicit_description_and_done_still_supported(client):
    app = create_app_task(client)
    task = create_task(client, app["id"], "Save a draft")
    answers = task["session"]["answers"]
    assert answers["teaching_goal"] == "Save the requested item"
    assert answers["teaching_done"] == "Receipt matches inputs"


def test_duplicate_task_name_is_rejected_per_app(client):
    app_a = create_app_task(client, "App A")
    app_b = create_app_task(client, "App B")
    create_task_name_only(client, app_a["id"], "Export a PDF")
    dup = client.post(f"/api/training/apps/{app_a['id']}/tasks", json={"name": "Export a PDF"})
    assert dup.status_code == 409, dup.text
    assert "already exists" in dup.text.lower()
    # The same label in a different app is allowed; uniqueness is per app.
    ok = client.post(f"/api/training/apps/{app_b['id']}/tasks", json={"name": "Export a PDF"})
    assert ok.status_code == 200, ok.text


def test_quick_record_name_collision_appends_versions_and_preserves_recordings(client):
    def record(media_bytes):
        response = client.post("/api/quick-record", json={
            "app_name": "Editor", "task_name": "Save monthly report",
        })
        assert response.status_code == 200, response.text
        data = response.json()
        upload = client.post(
            f"/api/sessions/{data['session_id']}/media",
            content=media_bytes,
            headers={"content-type": "video/webm"},
        )
        assert upload.status_code == 200, upload.text
        return data

    first = record(b"recording-one")
    renamed = client.post(f"/api/sessions/{first['session_id']}/name", json={
        "app_name": "Editor", "task_name": "Save monthly report v2",
    })
    assert renamed.status_code == 200, renamed.text
    task_id = renamed.json()["task_id"]
    assert task_id == first["task_id"]
    assert client.get(f"/api/training/tasks/{task_id}").json()["latest_version"] == 1
    from holdmybeer.hybrid import HybridRecipe, HybridStep, list_hybrid_recipes, save_hybrid_recipe
    target_recipe = HybridRecipe(
        task_id=task_id, title="Save monthly report v2", app_name="Editor",
        steps=[HybridStep(id="keep", action="file_organize_by_ext", goal="Keep existing target recipe")],
    )
    save_hybrid_recipe(client.app.state.store, task_id, target_recipe)

    # Repeating the same name request is idempotent and does not create a version.
    repeated_name = client.post(f"/api/sessions/{first['session_id']}/name", json={
        "app_name": "Editor", "task_name": "Save monthly report v2",
    })
    assert repeated_name.status_code == 200, repeated_name.text
    assert len(client.get(f"/api/training/tasks/{task_id}").json()["versions"]) == 1

    second = record(b"recording-two")
    assert second["task_id"] != task_id
    review = client.post(f"/api/sessions/{second['session_id']}/auto-review", json={
        "window_title": "Browser", "duration_seconds": 3,
    })
    assert review.status_code == 200, review.text
    assert set(recipe.task_id for recipe in list_hybrid_recipes(client.app.state.store)) == {task_id, second["task_id"]}

    joined = client.post(f"/api/sessions/{second['session_id']}/name", json={
        "app_name": "Editor", "task_name": "SAVE MONTHLY REPORT V2",
    })
    assert joined.status_code == 200, joined.text
    assert joined.json()["task_id"] == task_id
    assert joined.json()["task_name"] == "Save monthly report v2"
    recipes_after_attach = list_hybrid_recipes(client.app.state.store)
    assert [recipe.task_id for recipe in recipes_after_attach] == [task_id]
    assert recipes_after_attach[0].recipe_id == target_recipe.recipe_id
    assert recipes_after_attach[0].steps[0].id == "keep"

    task = client.get(f"/api/training/tasks/{task_id}").json()
    assert task["latest_version"] == 2
    assert [(v["version"], v["session_id"], v["parent_version"]) for v in task["versions"]] == [
        (1, first["session_id"], None), (2, second["session_id"], 1),
    ]
    assert client.get(f"/api/sessions/{first['session_id']}/media").content == b"recording-one"
    assert client.get(f"/api/sessions/{second['session_id']}/media").content == b"recording-two"

    saved_choices = client.post(f"/api/sessions/{second['session_id']}/answer-choices", json={
        "choices": {"q_action": "recorded_flow", "q_input": "ask_each_time"},
        "run_sandbox": False,
    })
    assert saved_choices.status_code == 200, saved_choices.text
    recipes_after_save = list_hybrid_recipes(client.app.state.store)
    assert [recipe.task_id for recipe in recipes_after_save] == [task_id]

    third = record(b"recording-three")
    joined_again = client.post(f"/api/sessions/{third['session_id']}/name", json={
        "app_name": "Editor", "task_name": "Save monthly report v2",
    })
    assert joined_again.status_code == 200, joined_again.text
    assert joined_again.json()["task_id"] == task_id
    final_task = client.get(f"/api/training/tasks/{task_id}").json()
    assert final_task["latest_version"] == 3
    assert [(v["version"], v["session_id"], v["parent_version"]) for v in final_task["versions"]] == [
        (1, first["session_id"], None),
        (2, second["session_id"], 1),
        (3, third["session_id"], 2),
    ]
    assert len(client.get("/api/training/apps").json()["apps"][0]["tasks"]) == 1
    assert client.get(f"/api/sessions/{third['session_id']}/media").content == b"recording-three"


def test_quick_rename_rejects_existing_task_name_without_losing_history(client):
    app = create_app_task(client, "Editor")
    source = create_task_name_only(client, app["id"], "Draft report")
    target = create_task_name_only(client, app["id"], "Final report")

    conflict = client.put(f"/api/tasks/{source['id']}/quick-rename", json={"task_name": "Final report"})
    assert conflict.status_code == 409, conflict.text
    assert client.get(f"/api/training/tasks/{source['id']}").json()["name"] == "Draft report"
    assert client.get(f"/api/training/tasks/{source['id']}").json()["versions"] == source["versions"]
    assert client.get(f"/api/training/tasks/{target['id']}").json()["name"] == "Final report"


def test_name_route_refuses_to_move_a_working_provisional_task(client):
    app = create_app_task(client, "Editor")
    source = client.post("/api/quick-record", json={"app_name": "Editor", "task_name": "Working draft"}).json()
    target = client.post("/api/quick-record", json={"app_name": "Editor", "task_name": "Final draft"}).json()
    with client.app.state.store.connect() as db:
        db.execute("UPDATE training_tasks SET working_version=1 WHERE id=?", (source["task_id"],))

    refused = client.post(f"/api/sessions/{source['session_id']}/name", json={
        "app_name": app["name"], "task_name": target["task_name"],
    })
    assert refused.status_code == 422, refused.text
    assert client.get(f"/api/training/tasks/{source['task_id']}").json()["working_version"] == 1
    assert client.get(f"/api/training/tasks/{source['task_id']}").json()["versions"][0]["session_id"] == source["session_id"]
    assert client.get(f"/api/training/tasks/{target['task_id']}").json()["versions"][0]["session_id"] == target["session_id"]


def test_archive_is_reversible_persistent_and_blocks_mutations_until_restored(client, tmp_path):
    app = create_app_task(client, "Editor")
    task = create_task_name_only(client, app["id"], "Archive me")
    first_sid = task["session"]["id"]
    first_media = client.post(f"/api/sessions/{first_sid}/media", content=b"version-one",
                              headers={"content-type": "video/webm"})
    assert first_media.status_code == 200
    second = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1})
    assert second.status_code == 200, second.text
    second_sid = second.json()["session"]["id"]
    second_media = client.post(f"/api/sessions/{second_sid}/media", content=b"version-two",
                               headers={"content-type": "video/webm"})
    assert second_media.status_code == 200

    archived = client.post(f"/api/training/tasks/{task['id']}/archive")
    assert archived.status_code == 200, archived.text
    archived_task = archived.json()
    assert archived_task["archived"] is True
    assert archived_task["archived_at"]
    assert client.post(f"/api/training/tasks/{task['id']}/archive").json()["archived_at"] == archived_task["archived_at"]
    assert client.get(f"/api/training/tasks/{task['id']}").json()["archived"] is True
    assert client.get("/api/training/apps").json()["apps"][0]["tasks"] == []
    visible = client.get("/api/training/apps?include_archived=true").json()["apps"][0]["tasks"]
    assert len(visible) == 1 and visible[0]["archived"] is True
    assert client.get(f"/api/sessions/{first_sid}/media").content == b"version-one"
    assert client.get(f"/api/sessions/{second_sid}/media").content == b"version-two"

    edit = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 2})
    assert edit.status_code == 409 and "restore" in edit.text.lower()
    version_restore = client.post(f"/api/training/tasks/{task['id']}/restore", json={
        "base_version": 2, "source_version": 1,
    })
    assert version_restore.status_code == 409 and "restore" in version_restore.text.lower()
    session_edit = client.put(f"/api/sessions/{second_sid}", json={"notes": "should be refused"})
    assert session_edit.status_code == 409 and "restore" in session_edit.text.lower()
    upload = client.post(f"/api/sessions/{second_sid}/media", content=b"blocked",
                         headers={"content-type": "video/webm"})
    assert upload.status_code == 409 and "restore" in upload.text.lower()
    quick_rename = client.put(f"/api/tasks/{task['id']}/quick-rename", json={"task_name": "Other name"})
    assert quick_rename.status_code == 409 and "restore" in quick_rename.text.lower()

    new_capture = client.post("/api/quick-record", json={"app_name": "Editor", "task_name": "New capture"}).json()
    merge = client.post(f"/api/sessions/{new_capture['session_id']}/name", json={
        "app_name": "Editor", "task_name": "Archive me",
    })
    assert merge.status_code == 409 and "restore" in merge.text.lower()
    assert len(client.get(f"/api/training/tasks/{task['id']}").json()["versions"]) == 2

    # Reopening the app reads persisted archive state from the migrated database.
    restarted = TestClient(create_app(tmp_path / "data"))
    assert restarted.get(f"/api/training/tasks/{task['id']}").json()["archived"] is True
    unarchived = restarted.post(f"/api/training/tasks/{task['id']}/unarchive")
    assert unarchived.status_code == 200 and unarchived.json()["archived"] is False
    assert unarchived.json()["archived_at"] is None
    assert restarted.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 2}).status_code == 200


def test_archive_column_migrates_existing_training_schema(client, tmp_path):
    app = create_app_task(client, "Editor")
    task = create_task_name_only(client, app["id"], "Legacy task")
    with client.app.state.store.connect() as db:
        db.execute("ALTER TABLE training_tasks DROP COLUMN archived_at")

    restarted = TestClient(create_app(tmp_path / "data"))
    detail = restarted.get(f"/api/training/tasks/{task['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["archived"] is False
    assert detail.json()["archived_at"] is None


def test_settings_save_creates_one_editable_version_atomically_and_rejects_collisions(client):
    app = create_app_task(client, "Editor")
    task = create_task(client, app["id"], "Old title")
    sid = task["session"]["id"]
    procedure = {"revision": 2, "steps": [
        {"goal": "Select report", "check": "Report is selected", "action": "select_media", "target": "Media", "input": "filename"},
        {"goal": "Enter details", "check": "Details are visible", "action": "fill", "target": "Report", "input": "caption"},
        {"goal": "Save report", "check": "Report is saved", "action": "click", "target": "Save"},
        {"goal": "Verify report", "check": "Saved report matches", "action": "verify_draft"},
    ]}
    original_update = client.put(f"/api/sessions/{sid}", json={
        "notes": "original notes", "procedure": procedure,
    })
    assert original_update.status_code == 200, original_update.text
    upload = client.post(f"/api/sessions/{sid}/media", content=b"retained source media",
                         headers={"content-type": "video/webm"})
    assert upload.status_code == 200
    other = create_task_name_only(client, app["id"], "Taken title")

    saved = client.put(f"/api/training/tasks/{task['id']}/settings", json={
        "base_version": 1, "name": "New title", "description": "New goal",
        "done": "New check", "notes": "Updated notes",
    })
    assert saved.status_code == 200, saved.text
    latest = saved.json()
    assert latest["latest_version"] == 2
    assert latest["name"] == "New title"
    assert latest["session"]["title"] == "New title"
    assert latest["session"]["answers"]["teaching_task_name"] == "New title"
    assert latest["session"]["answers"]["teaching_goal"] == "New goal"
    assert latest["session"]["answers"]["teaching_done"] == "New check"
    assert latest["session"]["notes"] == "Updated notes"
    assert latest["session"]["procedure"] == procedure
    assert latest["session"]["media_url"] == f"/api/sessions/{latest['session']['id']}/media"
    assert client.get(f"/api/sessions/{latest['session']['id']}/media").content == b"retained source media"
    assert client.get(f"/api/sessions/{sid}").json()["notes"] == "original notes"
    assert client.get(f"/api/sessions/{sid}").json()["title"] == "Old title"
    assert client.get(f"/api/sessions/{sid}").json()["procedure"] == procedure
    listed_tasks = client.get("/api/training/apps").json()["apps"][0]["tasks"]
    assert any(item["id"] == task["id"] and item["name"] == "New title" for item in listed_tasks)

    no_op = client.put(f"/api/training/tasks/{task['id']}/settings", json={
        "base_version": 2, "name": "New title", "description": "New goal",
        "done": "New check", "notes": "Updated notes",
    })
    assert no_op.status_code == 200 and no_op.json()["latest_version"] == 2
    assert len(no_op.json()["versions"]) == 2
    stale = client.put(f"/api/training/tasks/{task['id']}/settings", json={
        "base_version": 1, "name": "Stale title", "description": "", "done": "", "notes": "",
    })
    assert stale.status_code == 409
    duplicate = client.put(f"/api/training/tasks/{task['id']}/settings", json={
        "base_version": 2, "name": "Taken title", "description": "", "done": "", "notes": "",
    })
    assert duplicate.status_code == 409
    assert client.get(f"/api/training/tasks/{other['id']}").json()["name"] == "Taken title"


def test_name_only_approval_blocked_until_recording_confirmed(client):
    app = create_app_task(client)
    task = create_task_name_only(client, app["id"], "Export a PDF")
    sid = task["session"]["id"]
    # Fill goal/done but leave the recording unconfirmed: still pending intent, approval denied.
    client.put(f"/api/sessions/{sid}", json={"answers": {
        "teaching_goal": "Export the file", "teaching_done": "PDF saved",
        "teaching_recording_confirmed": "no"}})
    denied = client.post(f"/api/sessions/{sid}/teaching-review/approve",
                         json={"proposal_id": "00000000-0000-4000-8000-000000000000", "consent": True})
    assert denied.status_code == 409
    assert "confirm your complete recording" in denied.text.lower()


def test_pending_interpretation_binding_and_correction_states(client):
    """Post-record states stay honest: pending until an agent binds a proposal to the
    exact recording/context, and any later media/context change revokes the pending
    proposal (stale) so approval can never imply an unexamined or executed understanding."""
    app = create_app_task(client)
    task = create_task_name_only(client, app["id"], "Export a PDF")
    sid = task["session"]["id"]
    # Confirm the whole recording, then upload the only evidence an agent can inspect.
    client.put(f"/api/sessions/{sid}", json={"answers": {"teaching_recording_confirmed": "yes"}})
    media = client.post(f"/api/sessions/{sid}/media", content=b"recording-bytes-1",
                        headers={"content-type": "video/webm"})
    assert media.status_code == 200

    procedure = {"revision": 1, "steps": [
        {"goal": "Select media", "check": "File selected", "action": "select_media", "target": "Media", "input": "filename"},
        {"goal": "Enter caption", "check": "Caption visible", "action": "fill", "target": "Caption", "input": "caption"},
        {"goal": "Save", "check": "Receipt appears", "action": "click", "target": "Save draft"},
        {"goal": "Verify", "check": "Inputs match", "action": "verify_draft"}]}

    # 1) No agent proposal yet: the honest pending state, never a placeholder intent.
    assert client.get(f"/api/sessions/{sid}/teaching-review").json()["status"] == "waiting"

    # 2) A connected agent binds a proposal to the current recording/context snapshot.
    proposal = create_proposal(client.app.state.store.root, sid,
                               [{"timestamp": 0.5, "text": "The save control follows the request fields."}],
                               [], procedure)
    assert client.get(f"/api/sessions/{sid}/teaching-review").json()["status"] == "ready"

    # 3) Binding: replacing the recording invalidates the pending proposal (stale),
    #    so an approval can only ever follow the exact media an agent reviewed.
    client.post(f"/api/sessions/{sid}/media", content=b"recording-bytes-2-CHANGED",
                headers={"content-type": "video/webm"})
    assert client.get(f"/api/sessions/{sid}/teaching-review").json()["status"] == "stale"

    # 4) Binding also covers context: a fresh proposal plus a saved correction is stale
    #    until the agent re-examines; and approval is refused while stale (no silent intent).
    client.put(f"/api/sessions/{sid}", json={"answers": {"teaching_recording_confirmed": "yes"}})
    fresh = create_proposal(client.app.state.store.root, sid,
                            [{"timestamp": 1.0, "text": "Re-examine after the correction."}], [], procedure)
    assert client.get(f"/api/sessions/{sid}/teaching-review").json()["status"] == "ready"
    client.put(f"/api/sessions/{sid}", json={"answers": {"teaching_correction": "use the real Save button"}})
    assert client.get(f"/api/sessions/{sid}/teaching-review").json()["status"] == "stale"
    denied = client.post(f"/api/sessions/{sid}/teaching-review/approve",
                         json={"proposal_id": fresh["id"], "consent": True})
    assert denied.status_code == 409
    assert "stale" in denied.text.lower() or "resolve" in denied.text.lower() or "review" in denied.text.lower()

    # 5) Approval clears staleness only after the agent re-binds to the corrected context,
    #    and it records consent without executing anything (runs stay empty).
    again = create_proposal(client.app.state.store.root, sid,
                            [{"timestamp": 2.0, "text": "Corrected understanding."}], [], procedure)
    approved = client.post(f"/api/sessions/{sid}/teaching-review/approve",
                           json={"proposal_id": again["id"], "consent": True})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    after = client.get(f"/api/sessions/{sid}").json()
    assert after["runs"] == []
    assert (client.app.state.store.artifacts / f"{sid}.{again['id']}.understanding.json").is_file()


def test_legacy_session_is_preserved_and_never_treated_as_intent(tmp_path):
    import json as _json
    from holdmybeer.app import Store
    root = tmp_path / "data"
    (root / "artifacts").mkdir(parents=True)
    # A pre-existing legacy session: old goal/done notes, no recording-confirmation key.
    legacy = {
        "id": "00000000-0000-4000-8000-000000000001",
        "title": "Legacy task",
        "created_at": "2020-01-01T00:00:00+00:00",
        "notes": "",
        "answers": {
            "teaching_task_name": "Legacy task",
            "teaching_goal": "Old recorded goal",
            "teaching_done": "Old recorded done",
        },
        "procedure": {"revision": 1, "steps": []},
        "media_url": None,
        "runs": [],
    }
    store = Store(root)
    with store.connect() as db:
        db.execute("INSERT INTO sessions(id,data) VALUES(?,?)",
                   (legacy["id"], _json.dumps(legacy)))
    # Re-initializing runs the legacy migration; it must not alter or drop the session.
    Store(root)
    preserved = store.get_session(legacy["id"])
    assert preserved == legacy
    # Old goal/done are legacy notes only: no confirmation key means intent is still pending.
    assert "teaching_recording_confirmed" not in preserved["answers"]
    assert preserved["answers"]["teaching_goal"] == "Old recorded goal"


def test_legacy_session_migration_survives_missing_or_corrupt_procedure(tmp_path):
    """A legacy session with missing/corrupt procedure data must not abort the whole
    migration: it stays preserved and accessible, only a well-formed procedure gains a
    procedure_revisions row."""
    import json as _json
    root = tmp_path / "data"
    (root / "artifacts").mkdir(parents=True)
    missing = {"id": "00000000-0000-4000-8000-0000000000aa", "title": "No procedure",
               "created_at": "2019-01-01T00:00:00+00:00", "notes": "", "answers": {},
               "media_url": None, "runs": []}
    corrupt = {"id": "00000000-0000-4000-8000-0000000000bb", "title": "Bad json",
               "created_at": "2019-01-01T00:00:00+00:00", "notes": "", "answers": {},
               "procedure": {"bad": True}, "media_url": None, "runs": []}
    store = Store(root)
    with store.connect() as db:
        db.execute("INSERT INTO sessions(id,data) VALUES(?,?)",
                   (missing["id"], _json.dumps(missing)))
        db.execute("INSERT INTO sessions(id,data) VALUES(?,?)",
                   (corrupt["id"], _json.dumps(corrupt)))
    # Re-initializing runs the migration; previously this raised KeyError/JSONDecodeError.
    Store(root)
    # Both sessions are still preserved and accessible (legacy notes, not intent).
    assert store.get_session(missing["id"])["title"] == "No procedure"
    assert store.get_session(corrupt["id"])["title"] == "Bad json"
    # A well-formed legacy session still gains its immutable revision.
    good = {"id": "00000000-0000-4000-8000-0000000000cc", "title": "Good",
            "created_at": "2019-01-01T00:00:00+00:00", "notes": "",
            "answers": {"teaching_goal": "g"}, "procedure": {"revision": 1, "steps": []},
            "media_url": None, "runs": []}
    with store.connect() as db:
        db.execute("INSERT INTO sessions(id,data) VALUES(?,?)",
                   (good["id"], _json.dumps(good)))
    Store(root)
    with store.connect() as db:
        rows = db.execute(
            "SELECT session_id,revision,source FROM procedure_revisions WHERE session_id IN (?,?,?)",
            (missing["id"], corrupt["id"], good["id"])).fetchall()
    seen = {r["session_id"]: r["source"] for r in rows}
    assert seen.get(good["id"]) == "legacy_current"
    assert missing["id"] not in seen
    assert corrupt["id"] not in seen


def test_edit_and_restore_conflict_contract(client):
    """Edit/restore compatibility: edit takes only base_version, restore copies a source
    version, and a stale base_version conflicts without creating a session."""
    app = create_app_task(client)
    task = create_task(client, app["id"])
    sid1 = task["session"]["id"]
    (client.app.state.store.artifacts / f"{sid1}.webm").write_bytes(b"v1")
    edited = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1}).json()
    assert edited["latest_version"] == 2
    # Restore requires source_version and copies the chosen source's media.
    restored = client.post(f"/api/training/tasks/{task['id']}/restore",
                           json={"base_version": 2, "source_version": 1})
    assert restored.status_code == 200, restored.text
    value = restored.json()
    assert value["versions"][-1]["parent_version"] == 1
    assert (client.app.state.store.artifacts / f"{value['session']['id']}.webm").read_bytes() == b"v1"
    # Restore from the current (frozen) source is a valid no-content-change copy.
    current = client.post(f"/api/training/tasks/{task['id']}/restore",
                          json={"base_version": 3, "source_version": 3})
    assert current.status_code == 200, current.text
    # Edit rejects an unexpected source_version (StrictModel); restore requires it.
    assert client.post(f"/api/training/tasks/{task['id']}/edit",
                       json={"base_version": 3, "source_version": 1}).status_code == 422
    assert client.post(f"/api/training/tasks/{task['id']}/restore",
                       json={"base_version": 3}).status_code == 422
    # A stale base_version conflicts and creates no new session.
    before = len(client.get("/api/sessions").json()["sessions"])
    conflict = client.post(f"/api/training/tasks/{task['id']}/edit", json={"base_version": 1})
    assert conflict.status_code == 409
    assert len(client.get("/api/sessions").json()["sessions"]) == before


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

