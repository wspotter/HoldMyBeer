"""Browser checks for the beginner recording and understanding-review path."""
import re
import sqlite3
import subprocess

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from test_backend import server


def create_app_and_task(page, app_name="Shop", task_name="Save a request"):
    page.get_by_role("button", name="I’ll show you", exact=True).click()
    expect(page.locator("#trainingAppStage")).to_be_visible()
    expect(page.locator("#trainingAppCreateForm")).to_be_visible()
    page.locator("#trainingAppName").fill(app_name)
    page.locator("#trainingAppCreateForm").get_by_role("button", name="Save app").click()
    expect(page.locator("#trainingTaskStage")).to_be_visible()
    page.locator("#trainingTaskCreateToggle").click()
    page.locator("#trainingTaskName").fill(task_name)
    page.locator("#trainingTaskDescription").fill("Save the requested item")
    page.locator("#trainingTaskDone").fill("The saved receipt matches the request")
    page.locator("#trainingTaskCreateForm").get_by_role("button", name="Save task").click()
    expect(page.locator("#trainingDescriptionStage")).to_be_visible()


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
            page = browser.new_page()
            page.goto(base)
            expect(page.get_by_role("heading", name="Teach an assistant your repeat tasks.")).to_be_visible()
            expect(page.get_by_role("button", name="I’ll show you", exact=True)).to_be_visible()
            assert httpx.get(base + "/api/sessions").json()["sessions"] == []

            create_app_and_task(page, "Orders", "Save an order")
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 1
            # A newly named task exists in the training hierarchy, but its
            # session is created only when the user explicitly continues.
            app_id = httpx.get(base + "/api/training/apps").json()["apps"][0]["id"]
            page.locator("#directedView [data-view=home]").click()
            page.get_by_role("button", name="I’ll show you", exact=True).click()
            expect(page.locator("#trainingAppStage")).to_be_visible()
            page.locator("#trainingAppSelect").select_option(app_id)
            page.locator("#trainingAppContinue").click()
            expect(page.locator("#trainingTaskStage")).to_be_visible()
            page.locator("#trainingTaskCreateToggle").click()
            page.locator("#trainingTaskName").fill("Send a receipt")
            page.locator("#trainingTaskDescription").fill("Send the customer a receipt")
            page.locator("#trainingTaskDone").fill("The receipt is visible")
            page.locator("#trainingTaskCreateForm").get_by_role("button", name="Save task").click()
            expect(page.locator("#trainingDescriptionStage")).to_be_visible()
            app = httpx.get(base + "/api/training/apps").json()["apps"][0]
            assert app["name"] == "Orders"
            assert len(app["tasks"]) == 2
            assert len({task["session_id"] for task in app["tasks"]}) == 2
            assert len(httpx.get(base + "/api/sessions").json()["sessions"]) == 2
            page.locator("#trainingRecordContinue").click()
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
            page.locator("#trainingRecordContinue").click()
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
            expect(page.locator("#directedVersionSummary")).to_contain_text("Working version 1. Read-only")
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
            expect(page.locator("#directedVersionSummary")).to_contain_text("Working version 1. Read-only")
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
            expect(page.locator("#trainingDescriptionStatus")).to_contain_text("Restored as draft version 3")
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
