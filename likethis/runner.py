from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


def get_data_dir() -> Path:
    raw = os.environ.get("LIKETHIS_DATA_DIR") or os.environ.get("HMB_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    legacy = Path("~/.local/share/holdmybeer").expanduser().resolve()
    if legacy.exists():
        return legacy
    return Path("~/.local/share/likethis").expanduser().resolve()


DATA_DIR = get_data_dir()


def execute(base_url: str, artifacts: Path, run_id: str, caption: str, filename: str,
            variant: str, repair: bool, mode: str = "practice", procedure: dict | None = None,
            media_mode: str = "new") -> dict:
    """Exercise the local fixture in the installed Playwright Chromium browser."""
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    steps = []
    screenshot = artifacts / f"{run_id}.png"
    result = {"status": "failed", "steps": steps, "failure": None,
              "screenshot_url": f"/api/artifacts/{run_id}.png", "draft_id": None}
    deadline = time.monotonic() + 20
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt",
                                     prefix="hmb-upload-", dir=artifacts, delete=False) as media:
        media.write("HoldMyBeer local browser fixture media\n")
        upload_path = Path(media.name)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, timeout=min(8000, max(1, int((deadline - time.monotonic()) * 1000))))
            goal = "Open browser page"
            try:
                page = browser.new_page()
                page.set_default_timeout(2200)
                goal = "Open local fixture"
                page.goto(f"{base_url}/fixture?variant={variant}", wait_until="domcontentloaded", timeout=min(5000, max(1, int((deadline - time.monotonic()) * 1000))))
                if mode == "procedure":
                    payload = None
                    for step in procedure["steps"]:
                        remaining = max(1, int((deadline - time.monotonic()) * 1000))
                        if remaining <= 1:
                            raise TimeoutError(f"whole-run timeout before action {step['action']}")
                        page.set_default_timeout(min(2200, remaining))
                        action = step["action"]
                        try:
                            if action in {"upload", "select_media"}:
                                media = page.get_by_label(step["target"], exact=True)
                                if action == "select_media" and media_mode == "reuse":
                                    media.set_input_files({"name": filename, "mimeType": "text/plain", "buffer": upload_path.read_bytes()})
                                    selected = media.evaluate("el => el.files.length ? el.files[0].name : null")
                                    if (selected is None or isinstance(selected, str)) and selected != filename:
                                        raise RuntimeError("retained filename was not selected in the simulated fixture input")
                                    evidence = f"Reuse simulated fixture file selected from retained draft: {filename}; contents are generated harmless fixture bytes"
                                else:
                                    media.set_input_files({"name": filename, "mimeType": "text/plain", "buffer": upload_path.read_bytes()})
                                    evidence = f"New simulated fixture file selected: {filename}; contents are generated harmless fixture bytes"
                            elif action == "fill":
                                page.get_by_label(step["target"], exact=True).fill(caption)
                                evidence = "Caption field contains requested text"
                            elif action == "click":
                                page.get_by_role("button", name=step["target"], exact=True).click()
                                evidence = f"Clicked button {step['target']}"
                            else:
                                page.wait_for_function("() => { try { return Boolean(JSON.parse(document.querySelector('output').textContent).id) } catch { return false } }")
                                payload = json.loads(page.locator("output").inner_text())
                                if payload.get("filename") != filename or payload.get("caption") != caption or not payload.get("id"):
                                    raise RuntimeError("fixture returned a draft with mismatched fields")
                                response = page.request.get(f"{base_url}/api/fixture/drafts", timeout=min(2500, remaining))
                                retained = next((d for d in response.json().get("drafts", []) if d.get("id") == payload["id"]), None)
                                if response.status != 200 or retained != payload:
                                    raise RuntimeError("saved draft was not present in retained draft list")
                                evidence = f"Draft {payload['id']} appears in API list"
                            steps.append({"goal": step["goal"], "status": "passed", "evidence": evidence, "action": action})
                        except PlaywrightTimeout as exc:
                            result.update(status="needs_teaching", failure=f"Action {action} failed: {step['goal']}; {str(exc)[:250]}")
                            steps.append({"goal": step["goal"], "status": "needs_teaching", "evidence": f"Configured {action} target was not available", "action": action})
                            break
                    else:
                        result.update(status="verified", draft_id=payload["id"])
                else:
                    steps.append({"goal": "Open local fixture", "status": "passed", "evidence": "Fixture page loaded in bundled Chromium"})
                    goal = "Upload selected file"
                    media = page.get_by_label("Media")
                    media.set_input_files({"name": filename, "mimeType": "text/plain", "buffer": upload_path.read_bytes()})
                    selected = media.evaluate("el => el.files.length ? el.files[0].name : null")
                    if (selected is None or isinstance(selected, str)) and selected != filename:
                        raise RuntimeError("simulated fixture file was not selected")
                    media_evidence = ("Reuse simulated fixture file selected from retained draft" if media_mode == "reuse" else "New simulated fixture file selected")
                    steps.append({"goal": "Select media", "status": "passed", "evidence": f"{media_evidence}: {filename}; contents are generated harmless fixture bytes"})
                    goal = "Fill caption"
                    page.get_by_label("Caption").fill(caption)
                    steps.append({"goal": "Fill caption", "status": "passed", "evidence": "Caption field contains requested text"})
                    if variant == "normal":
                        button = page.get_by_role("button", name="Save draft")
                    elif repair:
                        # Reviewed repair for the known changed-label fixture.
                        button = page.get_by_role("button", name="Store draft")
                    else:
                        button = page.get_by_role("button", name="Save draft")
                    goal = "Find save control"
                    button.click(timeout=1600)
                    goal = "Confirm saved draft"
                    page.wait_for_function(
                        "() => { try { return Boolean(JSON.parse(document.querySelector('output').textContent).id) } catch { return false } }",
                        timeout=2500,
                    )
                    payload = json.loads(page.locator("output").inner_text(timeout=1000))
                    if payload.get("filename") != filename or payload.get("caption") != caption or not payload.get("id"):
                        raise RuntimeError("fixture returned a draft with mismatched fields")
                    steps.append({"goal": "Save draft", "status": "passed", "evidence": f"Draft created: {payload['id']}"})
                    goal = "Verify retained draft"
                    response = page.request.get(f"{base_url}/api/fixture/drafts", timeout=2500)
                    drafts = response.json().get("drafts", [])
                    retained = next((d for d in drafts if d.get("id") == payload["id"]), None)
                    if response.status != 200 or retained != payload:
                        raise RuntimeError("saved draft was not present in retained draft list")
                    steps.append({"goal": "Verify retained draft", "status": "passed", "evidence": f"Draft {payload['id']} appears in API list"})
                    result.update(status="verified", draft_id=payload["id"])
            except PlaywrightTimeout as exc:
                if mode == "procedure":
                    result["failure"] = f"Procedure timed out: {str(exc)[:350]}"
                elif variant == "changed" and not repair and goal == "Find save control":
                    result.update(status="needs_teaching", failure="The Save draft control did not become clickable. Review the screenshot, if available: which control should save the draft?")
                    steps.append({"goal": goal, "status": "needs_teaching", "evidence": "Clicking the Save draft control timed out; the cause has not been confirmed"})
                else:
                    result["failure"] = f"{goal} timed out. Review the screenshot, if available, and retry this step."
                    steps.append({"goal": goal, "status": "failed", "evidence": "Browser interaction timed out; the cause has not been confirmed"})
            except Exception as exc:
                result["failure"] = f"Browser run failed: {str(exc)[:350]}"
            finally:
                try:
                    page.screenshot(path=str(screenshot), full_page=True, timeout=2500)
                except Exception:
                    result["screenshot_url"] = None
            browser.close()
    except Exception as exc:
        result["failure"] = f"Bundled browser unavailable or could not start: {str(exc)[:350]}"
        result["screenshot_url"] = None
    finally:
        upload_path.unlink(missing_ok=True)
    return result


def execute_hybrid(
    recipe: dict | object,
    parameters: dict | None = None,
    target_dir: str | Path | None = None,
    dry_run: bool = True,
    user_approved_understanding: bool = False,
) -> dict:
    """Execute a deterministic HybridRecipe in an isolated sandbox (dry_run=True) or live when approved."""
    from .hybrid import run_hybrid_recipe

    return run_hybrid_recipe(
        recipe=recipe,
        parameters=parameters,
        target_dir=target_dir,
        dry_run=dry_run,
        user_approved_understanding=user_approved_understanding,
    )

