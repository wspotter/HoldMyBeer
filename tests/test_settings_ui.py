"""Everyday navigation keeps the developer bench optional and explains review handoff."""
import os
import json
import re
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from test_backend import server
from test_directed_ui import one_second_video
from test_saved_workspace import seed_task


def test_settings_separates_connection_examples_and_developer_tools(server):
    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            nav = page.get_by_role("navigation", name="Main navigation")
            expect(nav.get_by_role("button", name="Advanced", exact=True)).to_have_count(0)
            nav.get_by_role("button", name="Settings", exact=True).click()
            expect(page.locator("#settingsView")).to_be_visible()
            expect(page.locator("#advancedView")).to_be_hidden()
            expect(page.locator("#settingsView")).to_contain_text("likethis-mcp")
            expect(page.locator("#settingsDeveloperTools")).not_to_have_attribute("open", "")
            expect(page.locator("#openDeveloperTools")).to_be_hidden()
            assert httpx.get(base + "/api/sessions").json()["sessions"] == []
            page.locator("#demoBegin").click()
            expect(page.locator("#demoView")).to_be_visible()
            expect(page.locator("#demoRun")).to_be_disabled()
            nav.get_by_role("button", name="Settings", exact=True).click()
            page.locator("#settingsDeveloperTools > summary").click()
            page.locator("#openDeveloperTools").click()
            expect(page.locator("#advancedView")).to_be_visible()
            nav.get_by_role("button", name="Settings", exact=True).click()
            expect(page.locator("#advancedView")).to_be_hidden()
            evidence = os.environ.get("HMB_BROWSER_EVIDENCE")
            if evidence:
                Path(evidence).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(evidence) / "settings-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            if evidence:
                page.screenshot(path=str(Path(evidence) / "settings-mobile.png"), full_page=True)
            assert not errors
        finally:
            browser.close()


def test_saved_recording_handoff_is_specific_and_does_not_dispatch(server, one_second_video):
    base, data_dir = server
    task = seed_task(base, "Orders", "Save an order", one_second_video)
    sid = task["session"]["id"]
    other = seed_task(base, "Images", "Resize an image")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            mutations = []
            page.on("request", lambda req: mutations.append(req.url) if req.method in ["POST", "PUT", "DELETE"] else None)
            page.goto(base)
            page.get_by_role("button", name="Saved tasks", exact=True).click()
            page.locator(f"#savedTree [data-task-id='{task['id']}']").click()
            request = page.locator("#savedReviewRequest")
            expect(request).to_have_value(re.compile(sid))
            expect(request).to_have_value(re.compile("Training version: 1"))
            page.locator("#savedReviewCopy").click()
            assert sid in page.evaluate("navigator.clipboard.readText()")
            page.locator("#savedReviewRefresh").click()
            expect(page.locator("#savedReviewStatus")).to_contain_text("No assistant review")
            assert not mutations
            # Persist through the same proposal store used by MCP; show actual inbox output.
            from likethis.proposals import create_proposal
            procedure = json.loads((Path(__file__).resolve().parents[1] / "docs/examples/fixture-draft.json").read_text())
            create_proposal(data_dir, sid, [{"timestamp": 0.1, "text": "The order appears in the list."}], [], procedure)
            page.locator("#savedReviewRefresh").click()
            expect(page.locator("#savedReviewResult")).to_contain_text("The order appears in the list.")
            assert not mutations
            page.locator("#savedTaskNotes").fill("Unsaved change to the task")
            expect(page.locator("#savedReviewCopy")).to_be_disabled()
            expect(page.locator("#savedReviewRefresh")).to_be_disabled()
            page.locator("#savedReviewSettings").click()
            expect(page.locator("#savedDirtyPrompt")).to_be_visible()
            page.locator("#savedKeepEditing").click()
            expect(page.locator("#savedTaskNotes")).to_have_value("Unsaved change to the task")
            # No-media tasks cannot produce a review request or claim review readiness.
            page.locator(f"#savedTree [data-task-id='{other['id']}']").click()
            page.locator("#savedDiscardChanges").click()
            expect(page.locator("#savedTaskName")).to_have_value("Resize an image")
            expect(page.locator("#savedReviewCopy")).to_be_disabled()
            expect(page.locator("#savedReviewRefresh")).to_be_disabled()
            assert not mutations
        finally:
            browser.close()
