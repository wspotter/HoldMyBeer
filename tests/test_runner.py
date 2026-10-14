from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from holdmybeer.runner import execute


@pytest.mark.parametrize("stage, goal", [
    ("navigate", "Open local fixture"),
    ("upload", "Upload selected file"),
    ("caption", "Fill caption"),
    ("save", "Find save control"),
    ("confirm", "Confirm saved draft"),
])
@pytest.mark.parametrize("variant", ["normal", "changed"])
def test_timeout_identifies_observed_step(monkeypatch, tmp_path, stage, goal, variant):
    page = MagicMock()
    media, caption, button = MagicMock(), MagicMock(), MagicMock()
    page.get_by_label.side_effect = lambda label: media if label == "Media" else caption
    page.get_by_role.return_value = button
    operations = {
        "navigate": page.goto,
        "upload": media.set_input_files,
        "caption": caption.fill,
        "save": button.click,
        "confirm": page.wait_for_function,
    }
    operations[stage].side_effect = PlaywrightTimeout("synthetic timeout")
    browser = MagicMock()
    browser.new_page.return_value = page
    manager = MagicMock()
    manager.__enter__.return_value = SimpleNamespace(
        chromium=SimpleNamespace(launch=lambda **kwargs: browser))
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: manager)

    result = execute("http://127.0.0.1:1234", tmp_path, "run", "caption", "fixture.txt", variant, False)

    status = "needs_teaching" if variant == "changed" and stage == "save" else "failed"
    assert result["status"] == status
    assert result["steps"][-1]["goal"] == goal
    assert result["steps"][-1]["status"] == status
    assert "cause has not been confirmed" in result["steps"][-1]["evidence"]
    assert "label changed" not in result["failure"]
    assert "screenshot" in result["failure"]
    assert result["draft_id"] is None
    browser.close.assert_called_once()
    assert list(tmp_path.glob("hmb-upload-*")) == []
