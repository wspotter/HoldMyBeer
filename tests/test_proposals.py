import json
import sqlite3
import uuid

import pytest

from likethis.proposals import create_proposal, latest_proposal


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "data"
    (root / "artifacts").mkdir(parents=True)
    sid = str(uuid.uuid4())
    original = {"id": sid, "title": "Teaching", "procedure": {"revision": 3, "steps": []}}
    with sqlite3.connect(root / "holdmybeer.sqlite3") as db:
        db.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL)")
        db.execute("CREATE TABLE runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,data TEXT NOT NULL)")
        db.execute("INSERT INTO sessions VALUES (?,?)", (sid, json.dumps(original)))
    return root, sid, original


def procedure(revision=4):
    return {
        "revision": revision,
        "steps": [
            {"goal": "Upload the file", "check": "Filename is visible", "action": "upload", "target": "media-input", "input": "filename"},
            {"goal": "Enter caption", "check": "Caption is visible", "action": "fill", "target": "caption-input", "input": "caption"},
            {"goal": "Save draft", "check": "Draft is saved", "action": "click", "target": "save-draft"},
            {"goal": "Verify draft", "check": "Draft id appears", "action": "verify_draft"},
        ],
    }


def test_proposal_is_separate_and_latest_helper_returns_valid_review_file(store):
    root, sid, original = store
    observation = [{"timestamp": 12.5, "text": "Save button is below the caption field."}]
    questions = [{"id": "button-position", "question": "Should the procedure scroll before saving?"}]
    first = create_proposal(root, sid, observation, questions, procedure())
    second = create_proposal(root, sid, observation, [], procedure(revision=5))

    path = root / "artifacts" / f"{sid}.{first['id']}.proposal.json"
    assert path.is_file()
    assert json.loads(path.read_text())["procedure"] == first["procedure"]
    with sqlite3.connect(root / "holdmybeer.sqlite3") as db:
        persisted = json.loads(db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()[0])
    assert persisted == original
    latest = latest_proposal(root, sid)
    assert latest["id"] == second["id"]
    assert latest["procedure"]["revision"] == 5


@pytest.mark.parametrize("observations", [[], [{"timestamp": -1, "text": "bad"}], [{"timestamp": float("nan"), "text": "bad"}],
                                             [{"timestamp": 86401, "text": "bad"}], [
                                                 {"timestamp": 0, "text": "x"} for _ in range(7)
                                             ]])
def test_invalid_observations_are_rejected(store, observations):
    root, sid, _ = store
    with pytest.raises(ValueError):
        create_proposal(root, sid, observations, [], procedure())
    assert latest_proposal(root, sid) is None


def test_unknown_session_invalid_questions_and_non_executable_procedure_rejected(store):
    root, sid, _ = store
    observation = [{"timestamp": 0, "text": "Observed save button."}]
    with pytest.raises(ValueError, match="session not found"):
        create_proposal(root, str(uuid.uuid4()), observation, [], procedure())
    with pytest.raises(ValueError):
        create_proposal(root, sid, observation, [{"id": "Bad ID", "question": "A question?"}], procedure())
    with pytest.raises(ValueError):
        create_proposal(root, sid, observation, [{"id": "same", "question": "One?"}, {"id": "same", "question": "Two?"}], procedure())
    with pytest.raises(ValueError, match="invalid teaching proposal"):
        create_proposal(root, sid, observation, [], {"revision": 1, "steps": procedure()["steps"][:3]})
    bad = procedure()
    bad["steps"][2]["action"] = "publish"
    with pytest.raises(ValueError):
        create_proposal(root, sid, observation, [], bad)
    assert latest_proposal(root, sid) is None


def test_unknown_fields_and_oversized_text_are_rejected(store):
    root, sid, _ = store
    with pytest.raises(ValueError):
        create_proposal(root, sid, [{"timestamp": 0, "text": "ok", "path": "/etc/passwd"}], [], procedure())
    with pytest.raises(ValueError):
        create_proposal(root, sid, [{"timestamp": 0, "text": "x" * 501}], [], procedure())
    with pytest.raises(ValueError):
        create_proposal(root, sid, [{"timestamp": 0, "text": "ok"}], [{"id": "question", "question": "?" * 301}], procedure())
    too_many_questions = [{"id": f"question-{index}", "question": "A question?"} for index in range(7)]
    with pytest.raises(ValueError):
        create_proposal(root, sid, [{"timestamp": 0, "text": "ok"}], too_many_questions, procedure())
    assert latest_proposal(root, sid) is None


def test_select_media_procedure_is_valid_and_retained(store):
    root, sid, _ = store
    selected = procedure(revision=6)
    selected["steps"][0]["action"] = "select_media"
    proposal = create_proposal(root, sid, [{"timestamp": 1, "text": "The retained filename was selected."}], [], selected)
    assert proposal["procedure"]["steps"][0]["action"] == "select_media"
    assert latest_proposal(root, sid)["id"] == proposal["id"]
