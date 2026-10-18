"""Browser checks for the beginner recording and understanding-review path."""
import os
import re
import sqlite3
import subprocess
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from test_backend import server


def create_app_and_task(page, app_name="Shop", task_name="Save a request"):
    page.get_by_role("button", name="Choose app & task first", exact=True).click()
    expect(page.locator("#trainingAppStage")).to_be_visible()
    expect(page.locator("#trainingAppCreateForm")).to_be_visible()
    page.locator("#trainingAppName").fill(app_name)
    page.locator("#trainingAppCreateForm").get_by_role("button", name="Save app").click()
    expect(page.locator("#trainingTaskStage")).to_be_visible()
    expect(page.locator("#trainingTaskCreateForm")).to_be_visible()
    expect(page.locator("#trainingTaskName")).to_be_focused()
    expect(page.locator("#trainingTaskContinue")).to_be_hidden()
    expect(page.locator("#trainingTaskCreateToggle")).to_be_hidden()
    # Returning to an existing empty app should open the same form directly.
    page.locator("#trainingBackToApps").click()
    page.locator("#trainingAppContinue").click()
    expect(page.locator("#trainingTaskCreateForm")).to_be_visible()
    expect(page.locator("#trainingTaskName")).to_be_focused()
    expect(page.locator("#trainingTaskTitle")).to_have_text("2. Create your first task")
    page.locator("#trainingTaskName").fill(task_name)
    # Single-field task creation: the name is an organizational label, not intent.
    # Creating the task opens the real recording/import path directly (no description
    # stage), so task identity and recording/session linkage are persisted here.
    page.locator("#trainingTaskCreateForm").get_by_role("button", name="Show how you do it").click()
    expect(page.locator("#directedRecordStage")).to_be_visible()
    expect(page.locator("#directedReview")).to_be_disabled()


@pytest.fixture
def one_second_video(tmp_path):
    path = tmp_path / "one-second-example.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=10:d=1",
        "-an", "-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-y", str(path.with_suffix(".webm")),
    ], check=True, timeout=15)
    return path.with_suffix(".webm")


def test_empty_home_requires_app_then_keeps_tasks_separate(server):
    base, _ = server
    assert httpx.get(base + "/api/sessions").json()["sessions"] == []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(base)
            expect(page.get_by_role("heading", name="Teach an assistant your repeat tasks.")).to_be_visible()
            expect(page.get_by_role("button", name="Choose app & task first", exact=True)).to_be_visible()
            expect(page.locator("#oneClickRecordBtn")).to_be_visible()
            expect(page.locator("#oneClickImportLabel")).to_be_visible()
            expect(page.locator("#quickRecordBegin")).to_be_hidden()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert httpx.get(base + "/api/sessions").json()["sessions"] == []

            create_app_and_task(page, "Orders", "Save an order")
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 1
            # A name-only task persists its session on creation (to hold the recording),
            # so each task has exactly one session and no duplicate is made on reload/reopen.
            app_id = httpx.get(base + "/api/training/apps").json()["apps"][0]["id"]
            page.locator("#directedView [data-view=home]").click()
            page.get_by_role("button", name="Choose app & task first", exact=True).click()
            expect(page.locator("#trainingAppStage")).to_be_visible()
            page.locator("#trainingAppSelect").select_option(app_id)
            page.locator("#trainingAppContinue").click()
            expect(page.locator("#trainingTaskStage")).to_be_visible()
            expect(page.locator("#trainingTaskCreateForm")).to_be_hidden()
            expect(page.locator("#trainingTaskContinue")).to_be_visible()
            page.locator("#trainingTaskCreateToggle").click()
            page.locator("#trainingTaskName").fill("Send a receipt")
            # Second name-only task opens the same recording/import path directly.
            page.locator("#trainingTaskCreateForm").get_by_role("button", name="Show how you do it").click()
            expect(page.locator("#directedRecordStage")).to_be_visible()
            app = httpx.get(base + "/api/training/apps").json()["apps"][0]
            assert app["name"] == "Orders"
            assert len(app["tasks"]) == 2
            assert len({task["session_id"] for task in app["tasks"]}) == 2
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 2
            # Already on the recording/import path for the second task; opening it via the
            # same task identity must not create a third session.
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 2
        finally:
            browser.close()


def test_imported_recording_waiting_review_saved_restore_and_approval_never_runs(server, one_second_video):
    from holdmybeer.proposals import create_proposal

    base, data_dir = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            create_app_and_task(page)
            # A name-only task lands directly on the recording/import path (no description stage).
            expect(page.locator("#directedRecordStage")).to_be_visible()
            expect(page.locator("#directedReview")).to_be_disabled()

            page.locator("#directedImport").set_input_files(str(one_second_video))
            expect(page.locator("#directedStatus")).to_contain_text("Recording saved locally")
            expect(page.locator("#directedVideo")).to_be_visible()
            page.wait_for_function("document.querySelector('#directedVideo').readyState >= 1")
            assert page.locator("#directedVideo").evaluate("video => Math.abs(video.duration - 1) < 0.2")
            initial_session = httpx.get(base + "/api/sessions").json()["sessions"][0]
            first_media_revision = initial_session["media_revision"]
            expect(page.locator("#directedComplete")).not_to_be_checked()
            expect(page.locator("#directedReview")).to_be_disabled()

            page.locator("#directedComplete").check()
            expect(page.locator("#directedReview")).to_be_enabled()
            page.locator("#directedReview").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Assistant review is not connected automatically")
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Refresh review")).to_be_visible()
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_have_count(0)

            # Replacing the recording, even with the same bytes, revokes the
            # previous whole-recording confirmation.
            page.locator("#directedReviewPanel").get_by_role("button", name="← Back to recording").click()
            page.locator("#directedImport").set_input_files(str(one_second_video))
            expect(page.locator("#directedStatus")).to_contain_text("Recording saved locally")
            expect(page.locator("#directedComplete")).not_to_be_checked()
            expect(page.locator("#directedReview")).to_be_disabled()

            saved = httpx.get(base + "/api/sessions").json()["sessions"]
            assert len(saved) == 1
            sid = saved[0]["id"]
            before = httpx.get(base + f"/api/sessions/{sid}").json()
            assert before["media_revision"] != first_media_revision
            assert before["procedure"]["steps"] == []
            assert before["runs"] == []
            assert before["answers"]["teaching_recording_confirmed"] == "no"
            page.locator("#directedComplete").check()
            page.locator("#directedReview").click()
            expect(page.locator("#directedReviewPanel")).to_be_visible()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Assistant review is not connected automatically")

            procedure = {"revision": 2, "steps": [
                {"goal": "Select media", "check": "Requested file is selected", "action": "select_media", "target": "Media", "input": "filename"},
                {"goal": "Enter caption", "check": "Caption is visible", "action": "fill", "target": "Caption", "input": "caption"},
                {"goal": "Save draft", "check": "Draft is saved", "action": "click", "target": "Save draft"},
                {"goal": "Verify draft", "check": "Saved values match", "action": "verify_draft"},
            ]}
            proposal = create_proposal(data_dir, sid, [{"timestamp": 0.5, "text": "The save control follows the request fields."}], [], procedure)
            assert httpx.get(base + f"/api/sessions/{sid}/teaching-review").json()["status"] == "ready"
            page.locator("#directedReviewPanel").get_by_role("button", name="Refresh review").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Here’s what I understood")

            # A reload returns to the home screen; Saved tasks must restore the
            # imported video and require the user to confirm it again.
            page.reload()
            page.get_by_role("button", name="Saved tasks", exact=True).click()
            expect(page.locator("#savedList .saved-task")).to_have_count(1)
            page.locator("#savedList .saved-task").click()
            expect(page.locator("#directedView")).to_be_visible()
            expect(page.locator("#trainingDescriptionStage")).to_be_visible()
            expect(page.locator("#trainingDescriptionText")).to_contain_text("Save a request")
            page.locator("#trainingRecordContinue").click()
            expect(page.locator("#directedRecordStage")).to_be_visible()
            expect(page.locator("#directedVideo")).to_be_visible()
            expect(page.locator("#directedComplete")).not_to_be_checked()
            expect(page.locator("#directedReview")).to_be_disabled()

            # Reload/reopen returns to the SAME named task/session: no duplicate
            # session was created and the same recording (unchanged media_revision,
            # as captured just before the reload at line ~133) is still here.
            reopened = httpx.get(base + "/api/sessions").json()["sessions"]
            assert len(reopened) == 1
            assert reopened[0]["id"] == initial_session["id"]
            assert reopened[0]["media_revision"] == before["media_revision"]
            assert reopened[0]["media_url"] == before["media_url"]

            page.locator("#directedComplete").check()
            page.locator("#directedReview").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Here’s what I understood")
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_be_visible()
            page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Nothing has been executed.")
            expect(page.locator("#directedReviewPanel").get_by_role("button", name=re.compile("Run|Replay"))).to_have_count(0)

            after = httpx.get(base + f"/api/sessions/{sid}").json()
            assert after["procedure"] == before["procedure"]
            assert after["runs"] == before["runs"] == []
            assert (data_dir / "artifacts" / f"{sid}.{proposal['id']}.understanding.json").is_file()

            # A task edit creates a new isolated session/version and keeps the
            # existing working pointer. The old recording and procedure stay
            # intact; restoring history copies it into another draft.
            task_id = httpx.get(base + "/api/training/apps").json()["apps"][0]["tasks"][0]["id"]
            with sqlite3.connect(data_dir / "holdmybeer.sqlite3") as db:
                db.execute("UPDATE training_tasks SET working_version=1 WHERE id=?", (task_id,))
            old_media = (data_dir / "artifacts" / f"{sid}.webm").read_bytes()
            page.locator("#directedReviewPanel").get_by_role("button", name="← Back to recording").click()
            page.locator("#directedEditDetails").click()
            expect(page.locator("#trainingDescriptionStage")).to_be_visible()
            page.locator("#trainingRecordContinue").click()
            expect(page.locator("#directedRecordStage")).to_be_visible()
            expect(page.locator("#directedVersionSummary")).to_contain_text("Last tested version")
            expect(page.locator("#directedVideo")).to_be_visible()
            page.wait_for_function("document.querySelector('#directedVideo').readyState >= 2")
            expect(page.locator("#directedImport")).to_be_disabled()
            expect(page.locator("#directedReview")).to_have_text("View saved understanding")
            page.locator("#directedReview").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("This tested version is read-only")
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_have_count(0)
            page.locator("#directedReviewPanel").get_by_role("button", name="← Back to recording").click()
            page.locator("#directedEditDetails").click()
            expect(page.locator("#trainingDescriptionStage")).to_be_visible()
            page.locator("#trainingEdit").click()
            expect(page.locator("#trainingEditForm")).to_be_visible()
            page.locator("#trainingEditName").fill("Save an updated request")
            page.locator("#trainingEditGoal").fill("Save the revised requested item")
            page.locator("#trainingEditDone").fill("The revised receipt matches the request")
            page.locator("#trainingEditForm").get_by_role("button", name="Save new version").click()
            edited = httpx.get(base + f"/api/training/tasks/{task_id}").json()
            sid2 = edited["session"]["id"]
            assert edited["latest_version"] == 2
            assert edited["working_version"] == 1
            assert sid2 != sid
            assert (data_dir / "artifacts" / f"{sid}.webm").read_bytes() == old_media
            assert (data_dir / "artifacts" / f"{sid2}.webm").read_bytes() == old_media
            assert httpx.get(base + f"/api/sessions/{sid}").json()["procedure"] == before["procedure"]
            assert httpx.get(base + f"/api/sessions/{sid}/media").content == old_media
            retained_write = httpx.put(base + f"/api/sessions/{sid}", json={"notes": "must remain read-only"})
            assert retained_write.status_code == 409
            # The old working version remains viewable after v2 exists. Opening
            # it is a read-only GET, including its saved understanding receipt.
            approval_path = data_dir / "artifacts" / f"{sid}.{proposal['id']}.understanding.json"
            approval_before = approval_path.read_bytes()
            version1_before = httpx.get(base + f"/api/sessions/{sid}").json()
            version2_before = httpx.get(base + f"/api/sessions/{sid2}").json()
            page.locator("#trainingHistory").select_option("1")
            page.locator("#trainingViewVersion").click()
            expect(page.locator("#directedRecordStage")).to_be_visible()
            expect(page.locator("#directedVersionSummary")).to_contain_text("Last tested version")
            expect(page.locator("#directedVideo")).to_be_visible()
            page.wait_for_function("document.querySelector('#directedVideo').readyState >= 2")
            expect(page.locator("#directedReview")).to_have_text("View saved understanding")
            page.locator("#directedReview").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Understanding approved")
            expect(page.locator("#directedReviewPanel")).to_contain_text("Nothing has been executed.")
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_have_count(0)
            assert httpx.get(base + f"/api/sessions/{sid}").json() == version1_before
            assert httpx.get(base + f"/api/sessions/{sid2}").json() == version2_before
            assert approval_path.read_bytes() == approval_before
            assert httpx.get(base + f"/api/sessions/{sid}/teaching-review").json()["status"] == "approved"
            page.locator("#directedReviewPanel").get_by_role("button", name="← Back to recording").click()
            expect(page.locator("#directedRecordStage")).to_be_visible()
            page.locator("#directedEditDetails").click()
            expect(page.locator("#trainingDescriptionStage")).to_be_visible()
            expect(page.locator("#trainingDescriptionText")).to_contain_text("Save an updated request")
            assert httpx.get(base + f"/api/training/tasks/{task_id}").json()["session"]["id"] == sid2
            assert httpx.get(base + f"/api/sessions/{sid}").json() == version1_before

            page.locator("#trainingHistory").select_option("1")
            page.locator("#trainingRestore").click()
            expect(page.locator("#trainingDescriptionStatus")).to_contain_text("Copied as training version 3")
            restored = httpx.get(base + f"/api/training/tasks/{task_id}").json()
            sid3 = restored["session"]["id"]
            assert restored["latest_version"] == 3
            assert restored["working_version"] == 1
            assert restored["versions"][-1]["parent_version"] == 1
            assert restored["session"]["training"] == {"version": 3}
            assert restored["session"]["runs"] == []
            assert restored["session"]["answers"]["teaching_recording_confirmed"] == "no"
            assert (data_dir / "artifacts" / f"{sid3}.webm").read_bytes() == old_media
        finally:
            browser.close()


def test_correction_marks_interpretation_stale_pending_revision_and_retains_note(server, one_second_video):
    """Slice 5: a saved correction makes the agent's interpretation out of date
    (pending the assistant's revision), removes Approve, and is retained."""
    from holdmybeer.proposals import create_proposal

    base, data_dir = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            create_app_and_task(page)
            expect(page.locator("#directedRecordStage")).to_be_visible()
            expect(page.locator("#directedReview")).to_be_disabled()
            page.locator("#directedImport").set_input_files(str(one_second_video))
            expect(page.locator("#directedStatus")).to_contain_text("Recording saved locally")
            expect(page.locator("#directedVideo")).to_be_visible()
            sid = httpx.get(base + "/api/sessions").json()["sessions"][0]["id"]

            page.locator("#directedComplete").check()
            expect(page.locator("#directedReview")).to_be_enabled()
            page.locator("#directedReview").click()
            # Honest post-record state: no connected agent has inspected the media yet.
            expect(page.locator("#directedReviewPanel")).to_contain_text("Assistant review is not connected automatically")
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_have_count(0)

            # A connected agent submits a proposal bound to this recording.
            procedure = {"revision": 1, "steps": [
                {"goal": "Select media", "check": "Requested file is selected", "action": "select_media", "target": "Media", "input": "filename"},
                {"goal": "Enter caption", "check": "Caption is visible", "action": "fill", "target": "Caption", "input": "caption"},
                {"goal": "Save draft", "check": "Draft is saved", "action": "click", "target": "Save draft"},
                {"goal": "Verify draft", "check": "Saved values match", "action": "verify_draft"},
            ]}
            proposal = create_proposal(data_dir, sid, [{"timestamp": 0.3, "text": "The save control follows the request."}], [], procedure)
            assert httpx.get(base + f"/api/sessions/{sid}/teaching-review").json()["status"] == "ready"
            page.locator("#directedReviewPanel").get_by_role("button", name="Refresh review").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Here’s what I understood")
            # Ready interpretation may be corrected before explicit approval.
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_be_visible()
            correction_text = "Use 'Submit order', not 'Save draft', as the final step."

            # Honest correction state: saving a correction revokes approval and marks
            # the interpretation out of date pending the assistant's revision.
            page.locator("#directedCorrection").fill(correction_text)
            page.locator("#directedReviewPanel").get_by_role("button", name="Save correction").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("This review is out of date")
            expect(page.locator("#directedReviewPanel")).to_contain_text(correction_text)
            expect(page.locator("#directedReviewPanel")).to_contain_text("has not been sent to an assistant")
            # No approval while the interpretation is out of date.
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_have_count(0)

            # The correction is retained on the session and shown again after a reload.
            page.reload()
            page.get_by_role("button", name="Saved tasks", exact=True).click()
            expect(page.locator("#savedList .saved-task")).to_have_count(1)
            page.locator("#savedList .saved-task").click()
            expect(page.locator("#trainingRecordContinue")).to_be_visible()
            page.locator("#trainingRecordContinue").click()
            expect(page.locator("#directedRecordStage")).to_be_visible()
            expect(page.locator("#directedVideo")).to_be_visible()
            page.locator("#directedComplete").check()
            page.locator("#directedReview").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("This review is out of date")
            expect(page.locator("#directedReviewPanel")).to_contain_text(correction_text)
            assert httpx.get(base + f"/api/sessions/{sid}").json()["answers"]["teaching_correction"] == correction_text

            # The agent submits a revised interpretation bound to the same recording;
            # the corrected understanding becomes ready again for explicit approval.
            create_proposal(data_dir, sid, [{"timestamp": 0.3, "text": "The submit control follows the request."}], [], procedure)
            assert httpx.get(base + f"/api/sessions/{sid}/teaching-review").json()["status"] == "ready"
            page.locator("#directedReviewPanel").get_by_role("button", name="Refresh review").click()
            expect(page.locator("#directedReviewPanel")).to_contain_text("Here’s what I understood")
            expect(page.locator("#directedReviewPanel").get_by_role("button", name="Approve this understanding")).to_be_visible()
        finally:
            browser.close()


def test_easy_recording_saves_directly_to_library_without_execution(server, one_second_video):
    base, data_dir = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            evidence_dir = os.environ.get("HMB_BROWSER_EVIDENCE")
            if evidence_dir:
                evidence_dir = Path(evidence_dir)
                evidence_dir.mkdir(parents=True, exist_ok=True)
            errors, posted = [], []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.on("request", lambda req: posted.append(req.url) if req.method == "POST" else None)
            page.goto(base)
            if evidence_dir:
                page.screenshot(path=str(evidence_dir / "easy-home-390.png"), full_page=True)
            page.locator("#oneClickImportInput").set_input_files(str(one_second_video))
            expect(page.locator("#hmbAppInput")).to_be_visible()
            page.locator("#hmbAppInput").fill("Orders")
            page.locator("#hmbTaskInput").fill("Save a customer order")
            expect(page.locator("#hmbNameNext")).to_have_text("Save recording")
            if evidence_dir:
                page.screenshot(path=str(evidence_dir / "easy-naming-modal-390.png"), full_page=True)
            with page.expect_response(lambda r: "/answer-choices" in r.url) as response:
                page.locator("#hmbNameNext").click()
            assert response.value.request.post_data_json["run_sandbox"] is False
            assert response.value.json()["status"] == "saved_for_review"
            expect(page.locator("#mcModalOverlay")).to_be_hidden()
            expect(page.locator("#savedView")).to_be_visible()
            expect(page.locator("#toast")).to_have_text("Your recording is saved.")
            expect(page.locator("#savedList")).not_to_contain_text("Quick Workflows")
            expect(page.locator("#savedList")).not_to_contain_text("No tasks saved for this app.")
            saved = page.locator("#savedList button").filter(has_text="Save a customer order")
            expect(saved).to_contain_text("needs review or testing")
            expect(page.locator("#savedStatus")).to_contain_text("Choose a task")
            if evidence_dir:
                page.screenshot(path=str(evidence_dir / "easy-saved-tasks-390.png"), full_page=True)
            assert not any("/hybrid-run" in url for url in posted)
            assert not list((data_dir / "artifacts").glob("*.understanding.json"))
            assert page.locator("#hmbRunNowBtn").count() == 0
            assert page.locator("#hmbCliCopyBtn").count() == 0
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            saved.click()
            expect(page.locator("#trainingDescriptionText")).to_contain_text("Save a customer order")
            expect(page.locator("#trainingEdit")).to_be_visible()
            assert not errors
        finally:
            browser.close()


def test_admin_mode_persists_and_sample_check_does_not_claim_app_execution(server, one_second_video):
    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.add_init_script("window.__hmbXss = false;")

            def inject_admin_metadata(route):
                response = route.fetch()
                payload = response.json()
                payload.update({
                    "window_title": '<img src=x onerror="window.__hmbXss=true">',
                    "display": '<svg onload="window.__hmbXss=true">',
                    "duration_seconds": '<img src=x onerror="window.__hmbXss=true">',
                })
                route.fulfill(response=response, json=payload)

            page.route("**/api/sessions/*/auto-review", inject_admin_metadata)
            page.goto(base)
            page.locator("#oneClickImportInput").set_input_files(str(one_second_video))
            page.locator("#hmbModeAdminBtn").click()
            page.reload()
            page.locator("#oneClickImportInput").set_input_files(str(one_second_video))
            expect(page.locator("#hmbModeAdminBtn")).to_have_class(re.compile("active"))
            page.locator("#hmbAppInput").fill("Unknown app")
            page.locator("#hmbTaskInput").fill("Take a screenshot")
            admin_metadata = page.locator(".hmb-admin-section")
            expect(admin_metadata).to_contain_text('<img src=x onerror="window.__hmbXss=true">')
            expect(admin_metadata).to_contain_text('<svg onload="window.__hmbXss=true">')
            expect(admin_metadata.locator("img, svg")).to_have_count(0)
            assert page.evaluate("window.__hmbXss") is False
            page.locator("#hmbNameNext").click()
            page.locator("#oneClickApproveBtn").click()
            expect(page.locator("#hmbTryBtn")).to_be_visible()
            page.locator("#hmbTryBtn").click()
            expect(page.locator("#hmbTryResult")).to_contain_text("Needs Attention")
            expect(page.locator("#hmbTryResult")).to_contain_text("needs a real browser or desktop executor")
            expect(page.locator("#hmbTryResult")).not_to_contain_text("[object Object]")
            expect(page.locator("#hmbTryResult")).not_to_contain_text("passed")
            expect(page.locator("#hmbTryResult")).not_to_contain_text("Safe for live use")
            page.locator("#hmbModeEasyBtn").click()
            expect(page.locator("#savedView")).to_be_visible()
            expect(page.locator("#mcModalOverlay")).to_be_hidden()
            assert page.evaluate("localStorage.getItem('hmb_user_mode')") == "easy"
            assert not errors
        finally:
            browser.close()


def test_cancelled_capture_does_not_open_review_or_invent_a_recording(server):
    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/api/native-record/start", lambda route: route.fulfill(json={"supported": False}))
            page.add_init_script("""navigator.mediaDevices.getDisplayMedia = async () => {
                throw new DOMException('User cancelled', 'NotAllowedError');
            };""")
            page.goto(base)
            page.locator("#oneClickRecordBtn").click()
            expect(page.locator("#oneClickStatus")).to_contain_text("Recording wasn’t started")
            expect(page.locator("#mcModalOverlay")).to_be_hidden()
            assert httpx.get(base + "/api/sessions").json()["sessions"] == []
        finally:
            browser.close()
