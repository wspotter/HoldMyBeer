import threading
import time

import pytest
from fastapi.testclient import TestClient

from holdmybeer.app import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def prepare(client, **changes):
    sid = client.post("/api/sessions", json={"title": "A useful issue brief"}).json()["id"]
    payload = {"session_id": sid, "repository": "wspotter/HoldMyBeer", "keyword": "teaching", "limit": 3}
    payload.update(changes)
    response = client.post("/api/issue-briefs", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, job):
    csrf = client.get("/api/issue-briefs/approval-session").json()["csrf"]
    return client.post(f"/api/issue-briefs/{job['id']}/approve", headers={"X-HMB-Approval": csrf},
                       json={"plan_hash": job["plan_hash"], "consent": True})


def test_approval_binds_exact_plan_and_requires_browser_exchange(client):
    job = prepare(client)
    path = f"/api/issue-briefs/{job['id']}"
    assert client.post(path + "/start").status_code == 409
    body = {"plan_hash": job["plan_hash"], "consent": True}
    assert client.post(path + "/approve", json=body).status_code == 403
    csrf = client.get("/api/issue-briefs/approval-session").json()["csrf"]
    assert client.post(path + "/approve", headers={"X-HMB-Approval": csrf},
                       json={**body, "plan_hash": "0" * 64}).status_code == 409
    assert client.post(path + "/approve", headers={"X-HMB-Approval": csrf},
                       json={**body, "consent": False}).status_code == 409
    assert approve(client, job).json()["status"] == "approved"
    assert approve(client, job).status_code == 409


def test_changed_session_revision_invalidates_approval(client):
    job = prepare(client)
    sid = job["plan"]["session_id"]
    assert client.put(f"/api/sessions/{sid}", json={"procedure": {"revision": 2, "steps": []}}).status_code == 200
    assert approve(client, job).status_code == 409


def test_job_retries_cancel_and_history_survive_reload(client, monkeypatch):
    from holdmybeer import issue_brief
    entered = threading.Event()
    calls = []
    def runner(repo, keyword, limit, artifacts, run_id, event):
        calls.append(run_id)
        entered.set()
        assert event.wait(3)
        return {"status": "cancelled", "issues": []}
    monkeypatch.setattr(issue_brief, "execute_issue_brief", runner)
    job = prepare(client)
    assert approve(client, job).status_code == 200
    path = f"/api/issue-briefs/{job['id']}"
    assert client.post(path + "/start").json()["status"] == "running"
    assert entered.wait(2)
    assert client.post(path + "/start").json()["status"] == "running"
    assert len(calls) == 1
    assert client.post(path + "/cancel").json()["cancel_requested"]
    for _ in range(100):
        done = client.get(path).json()
        if done["status"] != "running": break
        time.sleep(.01)
    assert done["status"] == "cancelled"
    assert client.post(path + "/start").json()["status"] == "cancelled"
    reopened = TestClient(create_app(client.app.state.store.db_path.parent))
    assert reopened.get(path).json()["status"] == "cancelled"
    assert reopened.get("/api/issue-briefs", params={"session_id": job["plan"]["session_id"]}).json()["jobs"][0]["id"] == job["id"]


def test_expiry_running_recovery_and_foreign_origin(client):
    job = prepare(client)
    assert approve(client, job).status_code == 200
    jobs = client.app.state.brief_jobs
    expired = jobs.get(job["id"])
    expired["expires_at"] = 0
    jobs.save(expired)
    assert client.post(f"/api/issue-briefs/{job['id']}/start").status_code == 409
    expired["status"] = "running"
    jobs.save(expired)
    restored = create_app(client.app.state.store.db_path.parent)
    assert restored.state.brief_jobs.get(job["id"])["status"] == "interrupted"
    assert client.post("/api/issue-briefs", headers={"Origin": "https://evil.example"}, json={}).status_code == 403
    assert client.get("/api/issue-briefs/not-a-uuid").status_code == 404


def test_reports_require_retained_verified_result(client):
    job = prepare(client)
    path = f"/api/issue-briefs/{job['id']}/report"
    assert client.get(path).status_code == 404
    retained = client.app.state.store.artifacts / f"{job['id']}-issues.json"
    retained.write_text('{"issues": []}')
    assert client.get(path).status_code == 404
    job["status"] = "verified"
    client.app.state.brief_jobs.save(job)
    assert client.get(path).json() == {"issues": []}


def test_failed_running_receipt_write_releases_browser_lock(client, monkeypatch):
    job = prepare(client)
    assert approve(client, job).status_code == 200
    jobs = client.app.state.brief_jobs
    original_save = jobs.save
    failed_once = False

    def fail_running_receipt(receipt):
        nonlocal failed_once
        if receipt["id"] == job["id"] and receipt["status"] == "running" and not failed_once:
            failed_once = True
            raise OSError("simulated storage failure")
        return original_save(receipt)

    monkeypatch.setattr(jobs, "save", fail_running_receipt)
    with pytest.raises(OSError, match="simulated storage failure"):
        jobs.start(job["id"])

    assert not jobs.runner_lock.locked()
    assert jobs.get(job["id"])["status"] == "failed"
    assert jobs.start(job["id"])["status"] == "failed"
