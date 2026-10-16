"""Bounded, read-only browser brief for public GitHub issue searches."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit


DEADLINE_SECONDS = 30
SEARCH_SETTLE_MS = 180
MAX_LIMIT = 10
STATIC_HOSTS = {
    "github.githubassets.com",
    "avatars.githubusercontent.com",
    "user-images.githubusercontent.com",
}
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?$")
KEYWORD_RE = re.compile(r"^[A-Za-z0-9 -]{0,80}$", re.ASCII)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$", re.ASCII)
ISSUE_PATH_RE = re.compile(r"^/([^/]+)/([^/]+)/issues/(\d+)$")
EMPTY_TEXT_RE = re.compile(
    r"\b(no results|no issues (?:matched|found)|couldn.t find any issues)\b", re.IGNORECASE
)


def _validate(repository: str, keyword: str, limit: int, run_id: str) -> tuple[str, str, str]:
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ValueError("repository must be owner/name")
    owner, name = repository.split("/", 1)
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(name):
        raise ValueError("repository must be a GitHub-safe owner/name")
    if not isinstance(keyword, str) or not KEYWORD_RE.fullmatch(keyword.strip()):
        raise ValueError("keyword may contain only letters, numbers, spaces, or hyphens (up to 80 characters)")
    clean_keyword = " ".join(keyword.split())
    if len(clean_keyword) > 80:
        raise ValueError("keyword must be at most 80 characters")
    if re.search(r"\b(?:OR|AND|NOT)\b", clean_keyword, re.IGNORECASE):
        raise ValueError("keyword cannot contain GitHub search operators")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be a short filename-safe identifier")
    query = "is:issue state:open" + (f" {clean_keyword}" if clean_keyword else "")
    return f"{owner}/{name}", clean_keyword, query


def validate_inputs(repository: str, keyword: str, limit: int) -> tuple[str, str, int]:
    """Public preflight used by the run API before queueing browser work."""
    clean_repository, clean_keyword, _ = _validate(repository, keyword, limit, "validation")
    return clean_repository, clean_keyword, limit


def _allowed_issue_list_url(url: str, repository: str, expected_query: str,
                            allow_page_parameter: bool = False) -> bool:
    """Allow only the exact public issue-list URL (or its page-one hydration fetch)."""
    try:
        parsed = urlsplit(url)
        values = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "github.com"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path == f"/{repository}/issues"
            and not parsed.fragment
            and set(values) in ({"q"}, {"q", "page"})
            and (allow_page_parameter or set(values) == {"q"})
            and len(values["q"]) == 1
            and values["q"][0] in {"is:issue state:open", expected_query}
            and ("page" not in values or values["page"] == ["1"])
        )
    except (ValueError, TypeError):
        return False


def _is_expected_search_response_url(url: str, repository: str, expected_query: str) -> bool:
    try:
        values = parse_qs(urlsplit(url).query, keep_blank_values=True, strict_parsing=True)
        return (_allowed_issue_list_url(url, repository, expected_query, allow_page_parameter=True)
                and values.get("q") == [expected_query])
    except (ValueError, TypeError):
        return False


def _cancelled(cancel_event: threading.Event) -> bool:
    return cancel_event.is_set()


def _extract_visible_issues(page, repository: str, limit: int) -> tuple[list[dict], bool, bool]:
    links = page.locator("a[href]").evaluate_all(
        "els => els.map(a => ({href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim()}))"
    )
    found: list[dict] = []
    seen: set[int] = set()
    expected_prefix = f"https://github.com/{repository}/issues/"
    for link in links:
        href = link.get("href", "")
        text = " ".join((link.get("text") or "").split())
        parsed = urlsplit(href)
        if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
                or not href.startswith(expected_prefix) or not text or re.fullmatch(r"#\d+", text)):
            continue
        match = ISSUE_PATH_RE.fullmatch(urlsplit(href).path)
        if not match or f"{match.group(1)}/{match.group(2)}" != repository:
            continue
        number = int(match.group(3))
        if number in seen:
            continue
        seen.add(number)
        found.append({"number": number, "title": text[:300], "url": href})
        if len(found) > limit:
            break
    page_text = page.locator("body").inner_text(timeout=1000)
    empty_state = bool(EMPTY_TEXT_RE.search(page_text))
    return found[:limit], len(found) > limit, empty_state


def _settled_results(page, repository: str, limit: int, cancel_event: threading.Event,
                     deadline: float) -> tuple[list[dict], bool, bool] | None:
    previous = None
    stable = 0
    while time.monotonic() < deadline:
        if _cancelled(cancel_event):
            return None
        current = _extract_visible_issues(page, repository, limit)
        signature = json.dumps(current, sort_keys=True)
        if signature == previous:
            stable += 1
            if stable >= 3:
                issues, truncated, empty_state = current
                if issues or empty_state:
                    return current
        else:
            previous, stable = signature, 0
        page.wait_for_timeout(min(SEARCH_SETTLE_MS, max(1, int((deadline - time.monotonic()) * 1000))))
    raise TimeoutError("GitHub issue results did not settle before the run deadline")


def _report_file(artifacts: Path, filename: str, report: dict) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    target = artifacts / filename
    temp = artifacts / (filename + ".tmp")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(target)


def execute_issue_brief(repository: str, keyword: str, limit: int, artifacts: Path,
                        run_id: str, cancel_event: threading.Event) -> dict:
    """Search rendered public GitHub issues without login, writes, or API fallback."""
    repository, keyword, _ = validate_inputs(repository, keyword, limit)
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be a short filename-safe identifier")
    expected_query = "is:issue state:open" + (f" {keyword}" if keyword else "")
    if not isinstance(artifacts, Path):
        artifacts = Path(artifacts)
    if not isinstance(cancel_event, threading.Event):
        raise ValueError("cancel_event must be a threading.Event")

    report = {
        "status": "failed",
        "repository": repository,
        "keyword": keyword,
        "limit": limit,
        "issues": [],
        "source_url": None,
        "read_only": True,
        "truncated": False,
        "failure": None,
        "report_file": f"{run_id}-issues.json",
        "screenshot_file": f"{run_id}.png",
    }
    if _cancelled(cancel_event):
        report["status"] = "cancelled"
        _report_file(artifacts, report["report_file"], report)
        return report

    artifacts.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + DEADLINE_SECONDS
    page = None
    browser = None
    route_was_blocked = False
    popup_attempted = False
    try:
        from playwright.sync_api import sync_playwright

        path = f"/{repository}/issues"
        initial_url = f"https://github.com{path}?q={quote('is:issue state:open', safe='')}"
        expected_url_query = expected_query

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=5000)
            context = browser.new_context()
            context.set_default_timeout(2500)

            def guard_route(route):
                nonlocal route_was_blocked
                request = route.request
                if request.method not in {"GET", "HEAD"}:
                    route.abort()
                    return
                if request.is_navigation_request():
                    try:
                        is_main_frame = request.frame == page.main_frame
                    except Exception:
                        is_main_frame = False
                    if not is_main_frame or not _allowed_issue_list_url(
                        request.url, repository, expected_url_query
                    ):
                        route_was_blocked = True
                        route.abort()
                        return
                    route.fallback()
                    return
                host = urlsplit(request.url).hostname
                if (host == "github.com"
                        and _allowed_issue_list_url(request.url, repository, expected_url_query,
                                                   allow_page_parameter=True)
                        and request.resource_type in {"xhr", "fetch"}):
                    route.fallback()
                    return
                if host not in STATIC_HOSTS:
                    route.abort()
                    return
                route.fallback()

            context.route("**/*", guard_route)
            page = context.new_page()

            def close_popup(popup):
                nonlocal popup_attempted
                popup_attempted = True
                popup.close()

            page.on("popup", close_popup)
            page.goto(initial_url, wait_until="domcontentloaded", timeout=min(7000, max(1, int((deadline - time.monotonic()) * 1000))))
            report["source_url"] = page.url
            if _cancelled(cancel_event):
                report["status"] = "cancelled"
            else:
                initial_results = _settled_results(page, repository, limit, cancel_event, deadline)
                if initial_results is None:
                    report["status"] = "cancelled"
                elif not (initial_results[0] or initial_results[2]):
                    report["status"] = "needs_teaching"
                    report["failure"] = "Could not recognize the initial rendered GitHub issue list."
                else:
                    search = page.get_by_placeholder("Search issues", exact=True)
                    search.wait_for(state="visible", timeout=min(3500, max(1, int((deadline - time.monotonic()) * 1000))))
                    if expected_query == "is:issue state:open":
                        # The initial page already requested the exact approved query.
                        # Re-submitting the same blank search may produce no request at all.
                        report["issues"], report["truncated"], empty_state = initial_results
                        report["status"] = "verified" if report["issues"] or empty_state else "needs_teaching"
                        if not report["issues"] and not empty_state:
                            report["failure"] = "Could not recognize the rendered issue results or an explicit empty state."
                    else:
                        search_responses = []

                        def observe_search_response(response):
                            try:
                                request = response.request
                                if (request.resource_type in {"document", "xhr", "fetch"}
                                        and _is_expected_search_response_url(request.url, repository, expected_query)):
                                    search_responses.append((response.status, request.url))
                            except Exception:
                                pass

                        page.on("response", observe_search_response)
                        search.fill(expected_query)
                        search.press("Enter")
                        page.wait_for_function(
                            "expected => { const u = new URL(location.href); const q = u.searchParams.getAll('q'); "
                            "return q.length === 1 && q[0] === expected && [...u.searchParams.keys()].every(k => k === 'q'); }",
                            arg=expected_query,
                            timeout=min(7000, max(1, int((deadline - time.monotonic()) * 1000))),
                        )
                        page.wait_for_load_state("domcontentloaded", timeout=min(4500, max(1, int((deadline - time.monotonic()) * 1000))))
                        report["source_url"] = page.url
                        settled = _settled_results(page, repository, limit, cancel_event, deadline)
                        if settled is None or _cancelled(cancel_event):
                            report["status"] = "cancelled"
                        else:
                            issues, report["truncated"], empty_state = settled
                            changed = (issues, empty_state) != (initial_results[0], initial_results[2])
                            successful_document = any(200 <= status < 300 for status, _ in search_responses)
                            report["issues"] = issues
                            if not changed and not successful_document:
                                report["status"] = "needs_teaching"
                                report["failure"] = "Search changed the URL but no fresh rendered result state was observed."
                            else:
                                report["status"] = "verified" if issues or empty_state else "needs_teaching"
                                if not issues and not empty_state:
                                    report["failure"] = "Could not recognize the rendered issue results or an explicit empty state."
            if route_was_blocked:
                report["status"] = "needs_teaching"
                report["failure"] = "GitHub requested a method, navigation, or host outside the read-only policy."
            if popup_attempted:
                report["status"] = "needs_teaching"
                report["failure"] = "GitHub attempted to open a popup outside the read-only issue-list workflow."
            try:
                page.screenshot(path=str(artifacts / report["screenshot_file"]), full_page=True,
                                timeout=min(1800, max(1, int((deadline - time.monotonic()) * 1000))))
            except Exception:
                report["screenshot_file"] = None
    except Exception as exc:
        if _cancelled(cancel_event):
            report["status"] = "cancelled"
        elif route_was_blocked:
            report["status"] = "needs_teaching"
            report["failure"] = "GitHub attempted a main-frame navigation outside the read-only issue-list policy."
        elif popup_attempted:
            report["status"] = "needs_teaching"
            report["failure"] = "GitHub attempted to open a popup outside the read-only issue-list workflow."
        elif report["status"] != "needs_teaching":
            report["status"] = "needs_teaching" if type(exc).__name__ == "TimeoutError" else "failed"
            report["failure"] = (
                "GitHub issue search did not settle before the run deadline."
                if type(exc).__name__ == "TimeoutError"
                else f"GitHub issue brief stopped: {type(exc).__name__}."
            )
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
    if _cancelled(cancel_event):
        report["status"] = "cancelled"
        report["issues"] = []
        report["truncated"] = False
        report["failure"] = "Issue search was cancelled before completion."
    _report_file(artifacts, report["report_file"], report)
    return report
