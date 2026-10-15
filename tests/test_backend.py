import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

import holdmybeer.app as backend
from holdmybeer.app import create_app


@pytest.fixture
def server(tmp_path):
    app = create_app(tmp_path / "data")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, log_level="error", lifespan="off")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/api/status", timeout=.2).status_code == 200: break
        except Exception: time.sleep(.03)
    else: pytest.fail("local test server did not start")
    yield base, tmp_path / "data"
    instance.should_exit = True
    thread.join(timeout=3)
    sock.close()


def test_sessions_persist_and_unknown_ids_are_rejected(server):
    base, data_dir = server
    created = httpx.post(base + "/api/sessions", json={"title": "Printer test"}).json()
    updated = httpx.put(base + f"/api/sessions/{created['id']}", json={"notes": "first observation", "answers": {"noise": "steady"}})
    assert updated.status_code == 200
    restarted = create_app(data_dir)
    # A separate app instance opens the same on-disk store.
    assert restarted.state.store.get_session(created["id"])["notes"] == "first observation"
    assert httpx.get(base + "/api/sessions/not-a-session").status_code == 404
    assert httpx.get(base + f"/api/sessions/{created['id']}/runs/not-a-run").status_code == 404
    assert httpx.post(base + "/api/sessions", json={"title": "x", "surprise": True}).status_code == 422
    assert httpx.put(base + f"/api/sessions/{created['id']}", json={"procedure": {"revision": 0, "steps": []}}).status_code == 422
    assert httpx.put(base + f"/api/sessions/{created['id']}", json={"procedure": {"revision": True, "steps": []}}).status_code == 422
    assert httpx.put(base + f"/api/sessions/{created['id']}", json={"procedure": {"revision": 1, "steps": [{"goal": "click", "check": "saved", "action": "publish"}]}}).status_code == 422
    assert httpx.put(base + f"/api/sessions/{created['id']}", json={"answers": {"q": "x" * 2001}}).status_code == 422
    good_procedure = {"revision": 2, "steps": [{"goal": "Save draft", "check": "Draft id appears"}]}
    assert httpx.put(base + f"/api/sessions/{created['id']}", json={"procedure": good_procedure}).status_code == 200


def test_browser_saves_changed_steps_as_new_revision_and_preserves_conflicting_edits(server):
    from playwright.sync_api import sync_playwright, expect

    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            page.locator('[data-tab="teach"]').click()
            page.locator('#loadPractice').click()
            page.locator('#save').click()
            expect(page.locator('#revision')).to_have_text('2')
            # Loading the same local steps again must not manufacture a change.
            page.locator('#loadPractice').click()
            with page.expect_response(lambda response: '/api/sessions/' in response.url and response.request.method == 'PUT'):
                page.locator('#save').click()
            expect(page.locator('#revision')).to_have_text('2')
            page.locator('#step-0-goal').fill('Choose a fresh file')
            page.locator('#save').click()
            expect(page.locator('#revision')).to_have_text('3')
            page.get_by_text('Saved procedure revisions', exact=True).click()
            expect(page.locator('#procedureHistory > details')).to_have_count(3)
            page.locator('#procedureHistory > details').nth(1).locator('summary').click()
            expect(page.locator('#procedureHistory > details').nth(1)).to_contain_text('Select the requested media')
            session = httpx.get(base + '/api/sessions').json()['sessions'][0]
            original = session['procedure']
            newer = {**original, 'revision': 4}
            url = base + f"/api/sessions/{session['id']}"
            assert httpx.put(url, json={'procedure': newer}).status_code == 200
            page.locator('#step-0-goal').fill('Keep this unsaved edit')
            with page.expect_response(lambda response: response.request.method == 'PUT') as conflict:
                page.locator('#save').click()
            assert conflict.value.status == 409
            expect(page.locator('#step-0-goal')).to_have_value('Keep this unsaved edit')
            expect(page.locator('#revision')).to_have_text('3')
            assert httpx.get(url).json()['procedure'] == newer
        finally:
            browser.close()


def test_guided_demo_preserves_dirty_workflow_and_requires_explicit_review(server):
    from playwright.sync_api import sync_playwright, expect

    base, _ = server
    personal = httpx.post(base + "/api/sessions", json={"title": "My personal workflow"}).json()
    assert httpx.put(base + f"/api/sessions/{personal['id']}", json={"notes": "Saved personal notes"}).status_code == 200
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            expect(page.locator("#notes")).to_have_value("Saved personal notes")
            page.locator("#notes").fill("Unsaved personal edit")
            page.locator("#guidedStart").click()
            expect(page.locator("#guidedStatus")).to_contain_text("will not replace a workflow with unsaved changes")
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 1
            expect(page.locator("#notes")).to_have_value("Unsaved personal edit")

            page.locator("#save").click()
            expect(page.locator("#guidedStatus")).to_be_visible()
            page.locator("#guidedStart").click()
            expect(page.locator("#steps .step")).to_have_count(4)
            expect(page.locator("#guidedStatus")).to_contain_text("1/4")
            expect(page.locator("#reviewed")).not_to_be_checked()
            expect(page.locator("#reviewed")).to_be_disabled()
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 2

            page.locator("#guidedConfirmInspect").click()
            expect(page.locator("#reviewed")).to_be_enabled()
            expect(page.locator("#reviewed")).not_to_be_checked()
            page.locator("#run").click()
            expect(page.locator("#guidedStatus")).to_contain_text("explicitly check")
            assert httpx.get(base + f"/api/sessions/{personal['id']}").json()["runs"] == []

            page.locator("#reviewed").check()
            expect(page.locator("#guidedStatus")).to_contain_text("3/4")
            with page.expect_response(lambda response: response.url.endswith("/run") and response.request.method == "POST") as trial:
                page.locator("#run").click()
            result = trial.value.json()
            assert result["status"] == "verified", result
            assert result["filename"] == "guided-first-use.txt"
            assert result["caption"] == "A fresh caption for the guided practice draft."
            assert result["draft_id"]
            expect(page.locator("#guidedStatus")).to_contain_text("4/4")
            expect(page.locator("#guidedStatus")).to_contain_text(result["draft_id"])
            drafts = httpx.get(base + "/api/fixture/drafts").json()["drafts"]
            retained = next(draft for draft in drafts if draft["id"] == result["draft_id"])
            assert retained["filename"] == "guided-first-use.txt"
            assert retained["caption"] == "A fresh caption for the guided practice draft."
            saved_personal = httpx.get(base + f"/api/sessions/{personal['id']}").json()
            assert saved_personal["notes"] == "Unsaved personal edit"
            assert saved_personal["runs"] == []

            page.locator("#filename").fill("retry-after-browser-fix.txt")
            page.locator("#reviewed").check()
            page.route("**/api/sessions/*/run", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "failed", "filename": "retry-after-browser-fix.txt",
                    "caption": "A fresh caption for the guided practice draft.", "failure":
                    "Bundled browser unavailable or could not start: Traceback (most recent call last): /private/path"}),
            ))
            page.locator("#run").click()
            expect(page.locator("#guidedStatus")).to_contain_text("holdmybeer doctor")
            expect(page.locator("#guidedStatus")).not_to_contain_text("Traceback")

            page.unroute("**/api/sessions/*/run")
            page.locator("#filename").fill("retry-after-connection-fix.txt")
            page.locator("#reviewed").check()
            page.route("**/api/sessions/*/run", lambda route: route.abort())
            page.locator("#run").click()
            expect(page.locator("#guidedStatus")).to_contain_text("local workspace")
            expect(page.locator("#guidedStatus")).to_contain_text("loopback preview")

            page.locator("#newSession").click()
            expect(page.locator("#title")).to_have_value("New workflow")
            expect(page.locator("#reviewed")).to_be_enabled()
            expect(page.locator("#reviewed")).not_to_be_checked()
            page.locator("#guidedStart").click()
            expect(page.locator("#title")).to_have_value("Guided practice · Save a draft")
            expect(page.locator("#guidedStatus")).to_contain_text("local workspace")
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 3
            page.locator("#guidedStart").dblclick()
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 3
        finally:
            browser.close()


def test_guided_demo_retry_after_refresh_failure_restores_practice_procedure(server):
    from playwright.sync_api import sync_playwright, expect

    base, _ = server
    httpx.post(base + "/api/sessions", json={"title": "Existing workflow"})
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            expect(page.locator("#title")).to_have_value("Existing workflow")
            failed = {"refresh": False}

            def fail_one_refresh(route):
                if route.request.method == "GET" and route.request.url == f"{base}/api/sessions" and not failed["refresh"]:
                    failed["refresh"] = True
                    route.abort()
                else:
                    route.continue_()

            page.route("**/api/sessions", fail_one_refresh)
            page.locator("#guidedStart").click()
            expect(page.locator("#guidedStatus")).to_contain_text("Could not create the separate practice workflow")
            assert failed["refresh"]
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 2

            page.unroute("**/api/sessions", fail_one_refresh)
            page.locator("#guidedStart").click()
            expect(page.locator("#steps .step")).to_have_count(4)
            expect(page.locator("#title")).to_have_value("Guided practice · Save a draft")
            expect(page.locator("#reviewed")).to_be_disabled()
        finally:
            browser.close()


def test_media_is_bounded_and_origin_is_local_only(server, monkeypatch):
    base, _ = server
    session = httpx.post(base + "/api/sessions", json={"title": "Capture"}).json()
    assert httpx.post(base + f"/api/sessions/{session['id']}/media", content=b"x", headers={"Content-Type": "image/png"}).status_code == 415
    foreign = httpx.get(base + "/api/status", headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    another_local_port = httpx.get(base + "/api/status", headers={"Origin": "http://127.0.0.1:1234"})
    assert another_local_port.status_code == 403
    malformed_origin = httpx.get(base + "/api/status", headers={"Origin": "http://127.0.0.1:bad"})
    assert malformed_origin.status_code == 403
    assert httpx.get(base + "/api/status", headers={"Host": "evil.example"}).status_code == 400
    media_url = base + f"/api/sessions/{session['id']}/media"
    headers = {"Content-Type": "video/webm"}
    uploaded = httpx.post(media_url, content=b"original", headers=headers)
    assert uploaded.status_code == 200
    assert httpx.post(media_url, content=b"", headers=headers).status_code == 422
    monkeypatch.setattr(backend, "MAX_MEDIA_BYTES", 4)
    assert httpx.post(media_url, content=b"too large", headers=headers).status_code == 413
    assert httpx.get(media_url).content == b"original"


def test_real_browser_normal_changed_and_repaired_runs(server):
    base, _ = server
    session = httpx.post(base + "/api/sessions", json={"title": "Fixture exercise"}).json()
    fixture = httpx.get(base + "/fixture?variant=changed").text
    assert "Store draft" in fixture
    assert "Publish now" not in fixture
    normal = httpx.post(base + f"/api/sessions/{session['id']}/run", json={"caption": "A test caption", "filename": "input.mp4", "variant": "normal", "repair": False}).json()
    assert normal["status"] == "verified", normal
    assert normal["draft_id"]
    assert httpx.get(base + normal["screenshot_url"]).headers["content-type"] == "image/png"

    changed = httpx.post(base + f"/api/sessions/{session['id']}/run", json={"caption": "Changed label", "filename": "input.mp4", "variant": "changed", "repair": False}).json()
    assert changed["status"] == "needs_teaching", changed

    repaired = httpx.post(base + f"/api/sessions/{session['id']}/run", json={"caption": "Repaired label", "filename": "input.mp4", "variant": "changed", "repair": True}).json()
    assert repaired["status"] == "verified", repaired
    drafts = httpx.get(base + "/api/fixture/drafts").json()["drafts"]
    assert {normal["draft_id"], repaired["draft_id"]} <= {draft["id"] for draft in drafts}


def test_reviewed_procedure_runs_fresh_inputs_and_uses_saved_targets(server):
    base, _ = server
    session = httpx.post(base + "/api/sessions", json={"title": "Reviewed procedure"}).json()
    procedure = {"revision": 2, "steps": [
        {"goal": "Choose media", "check": "File is selected", "action": "upload", "target": "Media", "input": "filename"},
        {"goal": "Enter caption", "check": "Caption is entered", "action": "fill", "target": "Caption", "input": "caption"},
        {"goal": "Save draft", "check": "Draft is submitted", "action": "click", "target": "Save draft"},
        {"goal": "Confirm saved draft", "check": "Draft is retained", "action": "verify_draft"},
    ]}
    assert httpx.put(base + f"/api/sessions/{session['id']}", json={"procedure": procedure}).status_code == 200
    run_url = base + f"/api/sessions/{session['id']}/run"
    first = httpx.post(run_url, json={"caption": "First caption", "filename": "first.mp4", "variant": "normal", "repair": False, "mode": "procedure"}).json()
    second = httpx.post(run_url, json={"caption": "Second caption", "filename": "second.mp4", "variant": "normal", "repair": False, "mode": "procedure"}).json()
    assert first["status"] == second["status"] == "verified"
    assert first["draft_id"] != second["draft_id"]
    assert first["procedure"] == procedure
    assert [(s["action"], s["status"]) for s in second["steps"]] == [("upload", "passed"), ("fill", "passed"), ("click", "passed"), ("verify_draft", "passed")]

    failed = httpx.post(run_url, json={"caption": "Changed", "filename": "changed.mp4", "variant": "changed", "repair": True, "mode": "procedure"}).json()
    assert failed["status"] == "needs_teaching", failed
    assert "click" in failed["failure"]
    assert failed["procedure"] == procedure
    assert failed["draft_id"] is None

    changed = {**procedure, "revision": 3, "steps": [*procedure["steps"]]}
    changed["steps"][2] = {**changed["steps"][2], "target": "Store draft"}
    assert httpx.put(base + f"/api/sessions/{session['id']}", json={"procedure": changed}).status_code == 200
    taught = httpx.post(run_url, json={"caption": "Changed", "filename": "changed.mp4", "variant": "changed", "repair": False, "mode": "procedure"}).json()
    assert taught["status"] == "verified", taught
    assert taught["procedure"] == changed


def test_procedure_rejects_incomplete_malformed_and_reordered_actions(server):
    base, _ = server
    session = httpx.post(base + "/api/sessions", json={"title": "Validation"}).json()
    url = base + f"/api/sessions/{session['id']}"
    valid_steps = [
        {"goal": "u", "check": "u", "action": "upload", "target": "Media", "input": "filename"},
        {"goal": "f", "check": "f", "action": "fill", "target": "Caption", "input": "caption"},
        {"goal": "c", "check": "c", "action": "click", "target": "Save draft"},
        {"goal": "v", "check": "v", "action": "verify_draft"},
    ]
    malformed = [
        [valid_steps[0], valid_steps[1], valid_steps[2]],
        [valid_steps[1], valid_steps[0], valid_steps[2], valid_steps[3]],
        [{**valid_steps[0], "input": "caption"}, *valid_steps[1:]],
        [*valid_steps[:3], {**valid_steps[3], "target": "output"}],
    ]
    for steps in malformed:
        assert httpx.put(url, json={"procedure": {"revision": 2, "steps": steps}}).status_code == 422

    run_url = base + f"/api/sessions/{session['id']}/run"
    rejected = httpx.post(run_url, json={"caption": "x", "filename": "x.mp4", "variant": "normal", "repair": False, "mode": "procedure"})
    assert rejected.status_code == 422


def test_proposal_inbox_does_not_apply_agent_actions(server):
    from holdmybeer.proposals import create_proposal
    base, data_dir = server
    session = httpx.post(base + '/api/sessions', json={'title': 'Review inbox'}).json()
    steps = [
        {'goal': 'Upload', 'check': 'File selected', 'action': 'upload', 'target': 'Media', 'input': 'filename'},
        {'goal': 'Caption', 'check': 'Text matches', 'action': 'fill', 'target': 'Caption', 'input': 'caption'},
        {'goal': 'Save', 'check': 'Receipt', 'action': 'click', 'target': 'Save draft'},
        {'goal': 'Verify', 'check': 'Retained', 'action': 'verify_draft'},
    ]
    url = base + f"/api/sessions/{session['id']}"
    assert httpx.get(url + '/proposal').json() == {'proposal': None}
    p = create_proposal(data_dir, session['id'], [{'timestamp': 2, 'text': 'Caption visible'}], [{'id': 'fresh-file', 'question': 'Choose a new file?'}], {'revision': 1, 'steps': steps})
    assert httpx.get(url + '/proposal').json()['proposal']['id'] == p['id']
    assert httpx.get(url).json()['procedure']['steps'] == []
    assert httpx.get(base + '/api/sessions/missing/proposal').status_code == 404


def test_select_media_new_then_reuse_retained_filename_in_real_browser(server):
    base, _ = server
    session = httpx.post(base + "/api/sessions", json={"title": "Blended media"}).json()
    procedure = {"revision": 2, "steps": [
        {"goal": "Choose media", "check": "File is selected", "action": "select_media", "target": "Media", "input": "filename"},
        {"goal": "Enter caption", "check": "Caption is entered", "action": "fill", "target": "Caption", "input": "caption"},
        {"goal": "Save draft", "check": "Draft is submitted", "action": "click", "target": "Save draft"},
        {"goal": "Confirm saved draft", "check": "Draft is retained", "action": "verify_draft"},
    ]}
    assert httpx.put(base + f"/api/sessions/{session['id']}", json={"procedure": procedure}).status_code == 200
    url = base + f"/api/sessions/{session['id']}/run"
    new = httpx.post(url, json={"caption": "First caption", "filename": "retained-art.mp4", "variant": "normal", "repair": False, "mode": "procedure"}).json()
    assert new["status"] == "verified", new
    assert "generated harmless fixture bytes" in new["steps"][0]["evidence"]
    reused = httpx.post(url, json={"caption": "Updated caption", "media_mode": "reuse", "existing_draft_id": new["draft_id"], "variant": "normal", "repair": False, "mode": "procedure"}).json()
    assert reused["status"] == "verified", reused
    assert reused["filename"] == "retained-art.mp4"
    assert reused["inputs"]["filename"] == "retained-art.mp4"
    assert reused["media_mode"] == "reuse"
    assert "Reuse simulated fixture file" in reused["steps"][0]["evidence"]
    assert "generated harmless fixture bytes" in reused["steps"][0]["evidence"]
    assert httpx.post(url, json={"caption": "No arbitrary name", "filename": "guess.mp4", "media_mode": "reuse", "existing_draft_id": new["draft_id"], "variant": "normal", "repair": False}).status_code == 422


def test_batch_runs_stop_after_first_failure_and_return_individual_receipts(server):
    base, _ = server
    session = httpx.post(base + "/api/sessions", json={"title": "Batch run"}).json()
    response = httpx.post(base + f"/api/sessions/{session['id']}/run", json={
        "variant": "changed", "repair": False,
        "items": [
            {"caption": "Will need teaching", "filename": "first.mp4"},
            {"caption": "Must not run", "filename": "second.mp4"},
        ],
    })
    assert response.status_code == 200
    batch = response.json()
    assert batch["status"] == "failed"
    assert batch["requested"] == 2
    assert batch["attempted"] == batch["completed"] == 1
    assert batch["verified_count"] == 0
    assert batch["stopped_on_failure"] is True
    assert len(batch["runs"]) == 1
    assert batch["runs"][0]["status"] == "needs_teaching"
    assert batch["runs"][0]["inputs"]["filename"] == "first.mp4"
