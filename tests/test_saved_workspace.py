"""Saved workspace selects recordings, versions settings, and archives reversibly."""
import os
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from test_backend import server
from test_directed_ui import one_second_video


def seed_task(base, app_name, task_name, media=None):
    app = httpx.post(base + "/api/training/apps", json={"name": app_name})
    app.raise_for_status()
    task = httpx.post(base + f"/api/training/apps/{app.json()['id']}/tasks", json={
        "name": task_name, "description": "Save the selected order", "done": "The order appears in the list"})
    task.raise_for_status()
    task = task.json()
    if media:
        response = httpx.post(base + f"/api/sessions/{task['session']['id']}/media", content=media.read_bytes(),
                              headers={"Content-Type": "video/webm"})
        response.raise_for_status()
    return task


def test_saved_workspace_edit_history_archive_restore(server, one_second_video):
    base, _ = server
    order = seed_task(base, "Orders", "Save an order", one_second_video)
    image = seed_task(base, "Images", "Resize an image")
    original = httpx.get(base + f"/api/sessions/{order['session']['id']}").json()
    media = httpx.get(base + f"/api/sessions/{order['session']['id']}/media").content
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            page.get_by_role("button", name="Saved tasks", exact=True).click()
            tree = page.locator("#savedTree")
            expect(tree).to_contain_text("Orders")
            expect(tree).to_contain_text("Images")
            order_button = tree.locator(f"button[data-task-id='{order['id']}']")
            order_button.click()
            expect(page.locator("#savedView")).to_be_visible()
            expect(order_button).to_have_attribute("aria-current", "page")
            expect(page.locator("#savedTaskVideo")).to_be_visible()
            expect(page.locator("#savedTaskName")).to_have_value("Save an order")
            assert httpx.get(base + f"/api/training/tasks/{order['id']}").json()["latest_version"] == 1
            page.locator("#savedTaskName").fill("Save a customer order")
            page.locator("#savedTaskGoal").fill("Save the customer’s requested order")
            page.locator("#savedTaskDone").fill("The order confirmation is visible")
            page.locator("#savedTaskNotes").fill("Check the customer name before saving.")
            page.locator("#savedTaskSave").click()
            expect(tree).to_contain_text("Save a customer order")
            saved = httpx.get(base + f"/api/training/tasks/{order['id']}").json()
            assert saved["latest_version"] == 2
            assert saved["session"]["notes"] == "Check the customer name before saving."
            assert saved["session"]["answers"]["teaching_goal"] == "Save the customer’s requested order"
            old_session = httpx.get(base + f"/api/sessions/{order['session']['id']}").json()
            assert {key: value for key, value in old_session.items() if key != "training_task"} == {
                key: value for key, value in original.items() if key != "training_task"}
            assert httpx.get(base + f"/api/sessions/{saved['session']['id']}/media").content == media
            page.locator("#savedHistory").select_option("1")
            expect(page.locator("#savedTaskName")).to_have_value("Save an order")
            expect(page.locator("#savedTaskName")).not_to_be_editable()
            page.locator("#savedHistory").select_option("2")
            expect(page.locator("#savedTaskName")).to_have_value("Save a customer order")
            expect(page.locator("#savedTaskName")).to_be_editable()
            page.locator("#savedArchiveTask").click()
            expect(order_button).to_have_count(0)
            page.locator("#savedShowArchived").check()
            order_button.click()
            expect(page.locator("#savedRestoreTask")).to_be_visible()
            expect(page.locator("#savedTaskName")).not_to_be_editable()
            expect(page.locator("#savedTaskVideo")).to_be_visible()
            page.reload()
            page.get_by_role("button", name="Saved tasks", exact=True).click()
            page.locator("#savedShowArchived").check()
            order_button.click()
            page.locator("#savedRestoreTask").click()
            restored = httpx.get(base + f"/api/training/tasks/{order['id']}").json()
            assert not restored.get("archived_at")
            assert restored["latest_version"] == 2
            assert len(restored["versions"]) == 2
            expect(page.locator("#savedTaskName")).to_be_editable()
            tree.locator(f"button[data-task-id='{image['id']}']").click()
            expect(page.locator("#savedTaskName")).to_have_value("Resize an image")
            order_button.click()
            expect(page.locator("#savedTaskNotes")).to_have_value("Check the customer name before saving.")
            evidence = os.environ.get("HMB_BROWSER_EVIDENCE")
            if evidence:
                Path(evidence).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(evidence) / "saved-workspace-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            evidence = os.environ.get("HMB_BROWSER_EVIDENCE")
            if evidence:
                Path(evidence).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(evidence) / "saved-workspace-390.png"), full_page=True)
            assert not errors
        finally:
            browser.close()


def test_saved_workspace_unsaved_edits_and_late_selection(server):
    base, _ = server
    order = seed_task(base, "Orders", "Save an order")
    image = seed_task(base, "Images", "Resize an image")
    order_detail = httpx.get(base + f"/api/training/tasks/{order['id']}").json()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            page.get_by_role("button", name="Saved tasks", exact=True).click()
            order_button = page.locator(f"#savedTree button[data-task-id='{order['id']}']")
            image_button = page.locator(f"#savedTree button[data-task-id='{image['id']}']")
            pending = []
            page.route(base + f"/api/training/tasks/{order['id']}", lambda route: pending.append(route))
            order_button.click()
            image_button.click()
            expect(page.locator("#savedTaskName")).to_have_value("Resize an image")
            assert len(pending) == 1
            pending[0].fulfill(json=order_detail)
            page.wait_for_load_state("networkidle")
            expect(page.locator("#savedTaskName")).to_have_value("Resize an image")
            page.unroute(base + f"/api/training/tasks/{order['id']}")
            page.locator("#savedTaskNotes").fill("Keep these unsaved notes")
            order_button.click()
            expect(page.locator("#savedDirtyPrompt")).to_be_visible()
            expect(page.locator("#savedTaskName")).to_have_value("Resize an image")
            page.locator("#savedKeepEditing").click()
            expect(page.locator("#savedTaskNotes")).to_have_value("Keep these unsaved notes")
            order_button.click()
            page.locator("#savedDiscardChanges").click()
            expect(page.locator("#savedTaskName")).to_have_value("Save an order")
            assert httpx.get(base + f"/api/training/tasks/{image['id']}").json()["latest_version"] == 1
        finally:
            browser.close()


def test_saved_workspace_locks_pending_writes_and_history(server):
    base, _ = server
    task = seed_task(base, "Orders", "Save an order")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            page.get_by_role("button", name="Saved tasks", exact=True).click()
            page.locator(f"#savedTree button[data-task-id='{task['id']}']").click()
            expect(page.locator("#savedTaskName")).to_have_value("Save an order")
            expect(page.locator("#savedTaskVideo")).to_be_hidden()
            expect(page.locator("#savedEditor")).to_contain_text("No recording saved")
            pending = []
            settings_url = base + f"/api/training/tasks/{task['id']}/settings"
            page.route(settings_url, lambda route: pending.append(route))
            page.locator("#savedTaskNotes").fill("Retain the submitted notes")
            page.locator("#savedTaskSave").click()
            expect(page.locator("#savedTaskNotes")).not_to_be_editable()
            assert len(pending) == 1
            pending[0].fulfill(status=503, json={"detail": "Temporary failure"})
            expect(page.locator("#savedTaskNotes")).to_be_editable()
            expect(page.locator("#savedTaskNotes")).to_have_value("Retain the submitted notes")
            page.locator("#savedTaskSave").click()
            expect(page.locator("#savedTaskNotes")).not_to_be_editable()
            assert len(pending) == 2
            saved = httpx.put(settings_url, json=pending[1].request.post_data_json)
            saved.raise_for_status()
            pending[1].fulfill(json=saved.json())
            expect(page.locator("#savedTaskNotes")).to_be_editable()
            expect(page.locator("#savedTaskNotes")).to_have_value("Retain the submitted notes")
            page.unroute(settings_url)
            old_url = base + f"/api/sessions/{task['session']['id']}"
            history_pending = []
            page.route(old_url, lambda route: history_pending.append(route))
            page.locator("#savedHistory").select_option("1")
            expect(page.locator("#savedTaskNotes")).not_to_be_editable()
            assert len(history_pending) == 1
            history_pending[0].fulfill(json=httpx.get(old_url).json())
            expect(page.locator("#savedHistory")).to_have_value("1")
            expect(page.locator("#savedTaskNotes")).to_have_value("")
            expect(page.locator("#savedTaskNotes")).not_to_be_editable()
            page.locator("#savedHistory").select_option("2")
            expect(page.locator("#savedTaskNotes")).to_be_editable()
            expect(page.locator("#savedTaskNotes")).to_have_value("Retain the submitted notes")
        finally:
            browser.close()
