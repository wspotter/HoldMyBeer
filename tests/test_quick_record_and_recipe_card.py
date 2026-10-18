"""Slice 2 TDD tests: 1-Button Quick Record ('Record First, Name Later'), 3-Line Recipe Card, and Sandbox UI."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from holdmybeer.app import create_app
from test_backend import server


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app)


def test_quick_record_creates_session_and_infers_sensible_defaults(client):
    # 1. Zero-input 1-click quick record -> "Quick Workflow #1"
    r1 = client.post("/api/quick-record", json={})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["task_name"] == "Quick Workflow #1"
    assert d1["app_name"] == "Quick Workflows"
    assert d1["session_id"] == d1["session"]["id"]
    assert d1["task_id"] == d1["task"]["id"]
    assert "recipe_card" in d1
    assert set(d1["recipe_card"].keys()) >= {"when_you_give_me", "i_will_do", "you_will_get"}

    # 2. Second zero-input quick record increments -> "Quick Workflow #2"
    r2 = client.post("/api/quick-record", json={})
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["task_name"] == "Quick Workflow #2"
    assert d2["task_id"] != d1["task_id"]

    # 3. Context-hinted quick record (Downloads folder) -> "Organize Downloads Folder"
    r3 = client.post(
        "/api/quick-record",
        json={"file_path": "/Users/alex/Downloads", "window_title": "Downloads — Finder"},
    )
    assert r3.status_code == 200, r3.text
    d3 = r3.json()
    assert d3["task_name"] == "Organize Downloads Folder"
    assert d3["app_name"] == "Files & Folders"
    assert d3["inferred"]["source"] in {"file_path", "window_title"}


def test_recipe_card_endpoint_returns_three_line_zero_jargon_summary(client):
    qr = client.post(
        "/api/quick-record",
        json={"hint": "Summarize monthly sales CSV report"},
    ).json()
    task_id = qr["task_id"]

    resp = client.get(f"/api/tasks/{task_id}/recipe-card")
    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert card["task_id"] == task_id
    assert card["title"] == "Summarize CSV Report"
    assert isinstance(card["when_you_give_me"], list) and len(card["when_you_give_me"]) >= 1
    assert isinstance(card["i_will_do"], list) and len(card["i_will_do"]) >= 1
    assert card["i_will_do"][0].startswith("1.")
    assert "sandbox" in card["you_will_get"].lower()
    assert card["sandbox_diff_available"] is True


def test_browser_instant_record_button_opens_record_stage_with_recipe_card_and_sandbox_preview(server):
    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(base)
            # Both the classic "Show me how" button and the 1-click "🍺 Hold My Beer (Instant Record)" button exist
            expect(page.get_by_role("button", name="Show me how", exact=True)).to_be_visible()
            instant_btn = page.locator("#quickRecordBegin")
            expect(instant_btn).to_be_visible()
            expect(instant_btn).to_contain_text("Hold My Beer (Instant Record)")

            # Clicking Instant Record skips the 3-step App -> Task -> Details wizard and lands directly on #directedRecordStage
            instant_btn.click()
            expect(page.locator("#directedRecordStage")).to_be_visible()
            expect(page.locator("#quickRecordBanner")).to_be_visible()
            expect(page.locator("#quickRecordNameInput")).to_have_value("Quick Workflow #1")

            # User can tweak the auto-inferred name inline in 1 click
            page.locator("#quickRecordNameInput").fill("Organize Monthly Receipts")
            page.locator("#quickRecordSaveName").click()
            expect(page.locator("#directedTaskSummary")).to_contain_text("Organize Monthly Receipts")

            # 3-Line Recipe Card is visible with When you give me / I will do / You will get
            expect(page.locator("#recipeCardPanel")).to_be_visible()
            expect(page.locator("#recipeCardPanel")).to_contain_text("When you give me")
            expect(page.locator("#recipeCardPanel")).to_contain_text("I will do")
            expect(page.locator("#recipeCardPanel")).to_contain_text("You will get")

            # Sandbox Dry-Run Preview button runs a safe dry-run and renders the before/after diff
            expect(page.locator("#sandboxDryRunBtn")).to_be_visible()
            page.locator("#sandboxDryRunBtn").click()
            expect(page.locator("#sandboxDiffOutput")).to_be_visible()
            expect(page.locator("#sandboxDiffOutput")).to_contain_text("Sandbox Dry-Run Verified")
            expect(page.locator("#sandboxDiffOutput")).to_contain_text("summary.md")
        finally:
            browser.close()


def test_zero_typing_auto_review_and_multiple_choice_answers(tmp_path):
    from fastapi.testclient import TestClient
    from holdmybeer.app import create_app

    app = create_app(data_dir=tmp_path)
    client = TestClient(app)

    # 1. Start 1-click quick record
    qr = client.post("/api/quick-record", json={"window_title": "Terminal - nslookup google.com"}).json()
    sid = qr["session_id"]

    # 2. Trigger auto-review immediately after stop
    rev = client.post(f"/api/sessions/{sid}/auto-review", json={"window_title": "Terminal - nslookup", "duration_seconds": 3.2})
    assert rev.status_code == 200
    rev_data = rev.json()
    assert rev_data["status"] == "ready"
    assert len(rev_data["multiple_choice_questions"]) == 4
    assert rev_data["multiple_choice_questions"][0]["selected"] == "terminal_cmd"
    assert rev_data["observations"] == []
    assert rev_data["proposal"] is None

    # 3. Tap multiple-choice answers and confirm with sandbox dry-run
    ans = client.post(
        f"/api/sessions/{sid}/answer-choices",
        json={
            "selected_name": "DNS Lookup (nslookup)",
            "choices": {
                "q_action": "terminal_cmd",
                "q_input": "ask_each_time",
                "q_done": "window_minimized",
                "q_safety": "sandbox_first",
            },
            "run_sandbox": True,
        },
    )
    assert ans.status_code == 200
    ans_data = ans.json()
    assert ans_data["status"] == "saved_for_review"
    assert ans_data["execution_ready"] is False
    assert ans_data["task_name"] == "DNS Lookup (nslookup)"
    assert ans_data["proposal"] is None
    assert ans_data["sandbox_result"]["status"] == "needs_agent_assist"
    assert not list((tmp_path / "artifacts").glob("*.understanding.json"))
