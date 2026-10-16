"""Review receipt is bound to the current recording and teaching context."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from holdmybeer.app import create_app
from holdmybeer.proposals import create_proposal


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def make_session(client):
    response = client.post("/api/sessions", json={"title": "Teach a repeat task"})
    assert response.status_code == 200, response.text
    sid = response.json()["id"]
    updated = client.put(f"/api/sessions/{sid}", json={"answers": {
        "teaching_goal": "Save a practice draft", "teaching_done": "The draft receipt matches both inputs",
        "teaching_recording_confirmed": "yes",
    }})
    assert updated.status_code == 200, updated.text
    uploaded = client.post(f"/api/sessions/{sid}/media", content=b"\x1aE\xdf\xa3small-upload",
                           headers={"content-type": "video/webm"})
    assert uploaded.status_code == 200, uploaded.text
    return sid


def make_proposal(client, sid, questions=None):
    procedure = {
        "revision": 2,
        "steps": [
            {"goal": "Select media", "check": "The requested file is selected", "action": "select_media", "target": "Media", "input": "filename"},
            {"goal": "Enter caption", "check": "The caption is visible", "action": "fill", "target": "Caption", "input": "caption"},
            {"goal": "Save draft", "check": "A saved receipt appears", "action": "click", "target": "Save draft"},
            {"goal": "Verify receipt", "check": "Stored inputs match", "action": "verify_draft"},
        ],
    }
    return create_proposal(client.app.state.store.root, sid,
                           [{"timestamp": 1.0, "text": "The draft control follows the caption field."}],
                           questions or [], procedure)


def review(client, sid):
    response = client.get(f"/api/sessions/{sid}/teaching-review")
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, sid, proposal_id, consent=True):
    return client.post(f"/api/sessions/{sid}/teaching-review/approve",
                       json={"proposal_id": proposal_id, "consent": consent})


def test_waiting_then_bound_proposal_ready_and_approval_is_receipt_only(client):
    sid = make_session(client)
    waiting = review(client, sid)
    assert waiting["status"] == "waiting"
    assert waiting["proposal"] is None
    assert waiting["can_execute"] is False

    proposal = make_proposal(client, sid)
    ready = review(client, sid)
    assert ready["status"] == "ready"
    assert ready["proposal"]["id"] == proposal["id"]
    assert ready["can_execute"] is False

    before = client.get(f"/api/sessions/{sid}").json()
    assert approve(client, sid, proposal["id"], consent=False).status_code == 422
    assert approve(client, sid, str(uuid.uuid4())).status_code == 409
    answers = {**before["answers"], "teaching_recording_confirmed": "no"}
    assert client.put(f"/api/sessions/{sid}", json={"answers": answers}).status_code == 200
    assert approve(client, sid, proposal["id"]).status_code == 409
    answers["teaching_recording_confirmed"] = "yes"
    assert client.put(f"/api/sessions/{sid}", json={"answers": answers}).status_code == 200
    approved = approve(client, sid, proposal["id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["can_execute"] is False
    after = client.get(f"/api/sessions/{sid}").json()
    assert after["procedure"] == before["procedure"]
    assert after["runs"] == before["runs"] == []

    receipt = client.app.state.store.artifacts / f"{sid}.{proposal['id']}.understanding.json"
    assert receipt.is_file()
    assert json.loads(receipt.read_text())["proposal_id"] == proposal["id"]


def test_changed_context_or_recording_stales_proposal_and_blocks_approval(client):
    sid = make_session(client)
    proposal = make_proposal(client, sid)
    session = client.get(f"/api/sessions/{sid}").json()
    answers = {**session["answers"], "teaching_goal": "Use another goal"}
    changed = client.put(f"/api/sessions/{sid}", json={"answers": answers})
    assert changed.status_code == 200, changed.text
    assert review(client, sid)["status"] == "stale"
    assert approve(client, sid, proposal["id"]).status_code == 409

    # Refresh the proposal against the new context, then replace the source bytes.
    replacement = make_proposal(client, sid)
    upload = client.post(f"/api/sessions/{sid}/media", content=b"\x1aE\xdf\xa3different-recording",
                         headers={"content-type": "video/webm"})
    assert upload.status_code == 200, upload.text
    assert review(client, sid)["status"] == "stale"
    assert approve(client, sid, replacement["id"]).status_code == 409


def test_unanswered_questions_and_unbound_legacy_proposal_are_not_ready(client):
    sid = make_session(client)
    proposal = make_proposal(client, sid, [{"id": "save-location", "question": "Where should the draft be saved?"}])
    current = review(client, sid)
    assert current["status"] == "questions"
    assert current["can_execute"] is False
    assert approve(client, sid, proposal["id"]).status_code == 409

    # Older proposal files have no source binding and can never authorize a run.
    sid2 = make_session(client)
    legacy = make_proposal(client, sid2)
    path = client.app.state.store.artifacts / f"{sid2}.{legacy['id']}.proposal.json"
    saved = json.loads(path.read_text())
    saved.pop("source_media_sha256", None)
    saved.pop("source_context_sha256", None)
    path.write_text(json.dumps(saved))
    state = review(client, sid2)
    assert state["status"] == "stale"
    assert state["can_execute"] is False
    assert approve(client, sid2, legacy["id"]).status_code == 409


@pytest.mark.parametrize("suffix, expected", [("not-a-uuid", 422), (str(uuid.uuid4()), 404)])
def test_review_invalid_or_unknown_session_is_not_internal_error(client, suffix, expected):
    response = client.get(f"/api/sessions/{suffix}/teaching-review")
    assert response.status_code == expected
