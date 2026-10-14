from __future__ import annotations

import json
import tempfile
from pathlib import Path


def execute(base_url: str, artifacts: Path, run_id: str, caption: str, filename: str,
            variant: str, repair: bool) -> dict:
    """Exercise the local fixture in the installed Playwright Chromium browser."""
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    steps = []
    screenshot = artifacts / f"{run_id}.png"
    result = {"status": "failed", "steps": steps, "failure": None,
              "screenshot_url": f"/api/artifacts/{run_id}.png", "draft_id": None}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt",
                                     prefix="hmb-upload-", dir=artifacts, delete=False) as media:
        media.write("HoldMyBeer local browser fixture media\n")
        upload_path = Path(media.name)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, timeout=8000)
            goal = "Open browser page"
            try:
                page = browser.new_page()
                page.set_default_timeout(2200)
                goal = "Open local fixture"
                page.goto(f"{base_url}/fixture?variant={variant}", wait_until="domcontentloaded", timeout=5000)
                steps.append({"goal": "Open local fixture", "status": "passed", "evidence": "Fixture page loaded in bundled Chromium"})
                goal = "Upload selected file"
                page.get_by_label("Media").set_input_files({"name": filename, "mimeType": "text/plain", "buffer": upload_path.read_bytes()})
                steps.append({"goal": "Upload selected file", "status": "passed", "evidence": f"File input received {filename}"})
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
            except PlaywrightTimeout:
                if variant == "changed" and not repair and goal == "Find save control":
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
