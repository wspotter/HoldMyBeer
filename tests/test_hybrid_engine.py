"""Slice 1 TDD tests: Hybrid 'AI Thinks, Script Executes' Engine & Safe Sandbox Dry-Run."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from holdmybeer.app import create_app
from holdmybeer.hybrid import (
    HybridAssertion,
    HybridParameter,
    HybridRecipe,
    HybridStep,
    run_hybrid_recipe,
)
from holdmybeer import runner


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app)


def test_hybrid_recipe_contract_and_parameter_binding():
    recipe = HybridRecipe(
        task_id="task-001",
        title="Batch Rename Invoices",
        app_name="Finder / Files",
        parameters=[
            HybridParameter(name="prefix", type="string", description="Prefix to add", default="INV_", required=True),
            HybridParameter(name="pattern", type="string", description="Filename glob or regex", default=r".*\.txt$", required=False),
        ],
        steps=[
            HybridStep(
                id="rename-txt",
                action="file_rename_batch",
                goal="Add prefix to all text invoices",
                check="All matching .txt files start with prefix",
                params={"prefix": "{prefix}", "pattern": "{pattern}"},
            )
        ],
        assertions=[
            HybridAssertion(type="count_matches", target="*.txt", expected=2, phase="post"),
        ],
        on_uncertainty="pause_for_agent",
    )
    assert recipe.on_uncertainty == "pause_for_agent"
    bound = recipe.bind_parameters({"prefix": "2026_"})
    assert bound["prefix"] == "2026_"
    assert bound["pattern"] == r".*\.txt$"


def test_sandbox_dry_run_file_rename_batch_does_not_mutate_real_files(tmp_path):
    target_dir = tmp_path / "invoices"
    target_dir.mkdir()
    (target_dir / "april.txt").write_text("Invoice April: 20\n", encoding="utf-8")
    (target_dir / "may.txt").write_text("Invoice May: 50\n", encoding="utf-8")
    (target_dir / "notes.md").write_text("Keep untouched\n", encoding="utf-8")

    recipe = HybridRecipe(
        task_id="task-rename",
        title="Rename Monthly Invoices",
        app_name="Files",
        parameters=[
            HybridParameter(name="prefix", type="string", description="Prefix for renamed files", default="PAID_"),
        ],
        steps=[
            HybridStep(
                id="step-rename",
                action="file_rename_batch",
                goal="Prefix .txt invoices with PAID_",
                check="Renamed files exist in target folder",
                params={"pattern": r"^.+\.txt$", "prefix": "{prefix}"},
            )
        ],
        assertions=[
            HybridAssertion(type="file_exists", target="PAID_april.txt", phase="post"),
            HybridAssertion(type="file_exists", target="PAID_may.txt", phase="post"),
            HybridAssertion(type="count_matches", target="PAID_*.txt", expected=2, phase="post"),
        ],
    )

    # Dry run (default) runs inside an isolated sandbox and leaves target_dir untouched
    result = run_hybrid_recipe(recipe, parameters={"prefix": "PAID_"}, target_dir=target_dir, dry_run=True)
    assert result["status"] == "verified"
    assert result["dry_run"] is True
    assert result["real_files_mutated"] is False
    diff = result["before_after_diff"]
    assert "april.txt" in diff["files_before"]
    assert "PAID_april.txt" in diff["files_after"]
    assert "PAID_may.txt" in diff["files_after"]
    assert any(c["type"] == "renamed" or c["path"] == "PAID_april.txt" for c in diff["changes"])

    # Real files on disk were NOT mutated during dry_run!
    assert (target_dir / "april.txt").exists()
    assert not (target_dir / "PAID_april.txt").exists()


def test_file_organize_by_ext_and_csv_summary_report_in_sandbox_and_live(tmp_path):
    workspace = tmp_path / "downloads"
    workspace.mkdir()
    (workspace / "photo.png").write_bytes(b"fakepng")
    (workspace / "readme.txt").write_text("hello world", encoding="utf-8")
    (workspace / "sales.csv").write_text("item,amount\nWidget,10.5\nGadget,29.5\n", encoding="utf-8")

    recipe = HybridRecipe(
        task_id="task-org-csv",
        title="Organize and Summarize Sales",
        app_name="Local Workspace",
        parameters=[
            HybridParameter(name="csv_file", type="string", description="CSV input filename", default="sales.csv"),
            HybridParameter(name="report_file", type="string", description="Output markdown report", default="summary.md"),
        ],
        steps=[
            HybridStep(
                id="step-csv",
                action="csv_summary_report",
                goal="Summarize sales CSV into Markdown and JSON",
                check="Report file is written and non-empty",
                params={"csv_file": "{csv_file}", "output_file": "{report_file}", "numeric_column": "amount"},
            ),
            HybridStep(
                id="step-org",
                action="file_organize_by_ext",
                goal="Organize files into category folders by extension",
                check="Files are sorted into images, documents, and data folders",
                params={},
            ),
        ],
        assertions=[
            HybridAssertion(type="non_empty_output", target="documents/summary.md", phase="post"),
            HybridAssertion(type="file_exists", target="images/photo.png", phase="post"),
            HybridAssertion(type="file_exists", target="data/sales.csv", phase="post"),
        ],
    )

    # 1. Dry-run via runner.execute_hybrid
    dry = runner.execute_hybrid(recipe, parameters={}, target_dir=workspace, dry_run=True)
    assert dry["status"] == "verified"
    assert dry["real_files_mutated"] is False
    assert (workspace / "photo.png").is_file()
    assert not (workspace / "images" / "photo.png").exists()
    assert "40.0" in dry["before_after_diff"]["previews"].get("documents/summary.md", "")

    # 2. Live execution requires explicit user_approved_understanding=True
    with pytest.raises(PermissionError):
        runner.execute_hybrid(
            recipe,
            parameters={},
            target_dir=workspace,
            dry_run=False,
            user_approved_understanding=False,
        )

    # 3. Live execution with user_approved_understanding=True mutates target_dir and verifies
    live = runner.execute_hybrid(
        recipe,
        parameters={},
        target_dir=workspace,
        dry_run=False,
        user_approved_understanding=True,
    )
    assert live["status"] == "verified"
    assert live["real_files_mutated"] is True
    assert (workspace / "images" / "photo.png").is_file()
    assert (workspace / "documents" / "summary.md").is_file()
    assert "40.0" in (workspace / "documents" / "summary.md").read_text(encoding="utf-8")


def test_uncertainty_pauses_cleanly_with_diagnostic_snapshot(tmp_path):
    workspace = tmp_path / "broken_dir"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("no csv here", encoding="utf-8")

    recipe = HybridRecipe(
        task_id="task-uncertain",
        title="Summarize Missing CSV",
        app_name="Data Tools",
        parameters=[
            HybridParameter(name="csv_file", type="string", default="missing_orders.csv"),
        ],
        steps=[
            HybridStep(
                id="step-read-csv",
                action="csv_summary_report",
                goal="Read missing_orders.csv and write summary.md",
                check="missing_orders.csv exists and has rows",
                params={"csv_file": "{csv_file}", "output_file": "summary.md"},
            )
        ],
        assertions=[
            HybridAssertion(type="non_empty_output", target="summary.md", phase="post"),
        ],
        on_uncertainty="pause_for_agent",
    )

    result = run_hybrid_recipe(recipe, parameters={}, target_dir=workspace, dry_run=True)
    assert result["status"] == "needs_agent_assist"
    snap = result["diagnostic_snapshot"]
    assert snap["failed_step"]["id"] == "step-read-csv"
    assert "missing_orders.csv" in snap["expected_check"]
    assert "notes.txt" in snap["observed_state"]["files_present"]
    assert "missing_orders.csv" in snap["suggested_recovery_prompt"]


def test_api_hybrid_run_endpoint_enforces_sandbox_default_and_approval_gate(client, tmp_path):
    app_resp = client.post("/api/training/apps", json={"name": "Backoffice"}).json()
    task_resp = client.post(
        f"/api/training/apps/{app_resp['id']}/tasks",
        json={"name": "Batch Rename Receipts"},
    ).json()
    task_id = task_resp["id"]

    target_dir = tmp_path / "receipts"
    target_dir.mkdir()
    (target_dir / "r1.txt").write_text("Receipt 1", encoding="utf-8")
    (target_dir / "r2.txt").write_text("Receipt 2", encoding="utf-8")

    recipe_payload = {
        "title": "Batch Rename Receipts",
        "app_name": "Backoffice",
        "parameters": [
            {"name": "prefix", "type": "string", "description": "File prefix", "default": "OK_", "required": True}
        ],
        "steps": [
            {
                "id": "s1",
                "action": "file_rename_batch",
                "goal": "Prefix receipt files",
                "check": "All .txt files prefixed",
                "params": {"pattern": r"^r\d+\.txt$", "prefix": "{prefix}"},
            }
        ],
        "assertions": [
            {"type": "count_matches", "target": "OK_*.txt", "expected": 2, "phase": "post"}
        ],
    }

    save_resp = client.put(f"/api/tasks/{task_id}/hybrid-recipe", json=recipe_payload)
    assert save_resp.status_code == 200, save_resp.text

    # 1. Default POST /api/tasks/{task_id}/hybrid-run uses dry_run=True
    dry_resp = client.post(
        f"/api/tasks/{task_id}/hybrid-run",
        json={"target_dir": str(target_dir), "parameters": {"prefix": "ARCHIVED_"}},
    )
    assert dry_resp.status_code == 200, dry_resp.text
    dry_data = dry_resp.json()
    assert dry_data["dry_run"] is True
    assert dry_data["real_files_mutated"] is False
    assert "ARCHIVED_r1.txt" in dry_data["before_after_diff"]["files_after"]
    assert (target_dir / "r1.txt").exists()
    assert not (target_dir / "ARCHIVED_r1.txt").exists()

    # 2. Calling with dry_run=False without user_approved_understanding=True is rejected with 409
    blocked = client.post(
        f"/api/tasks/{task_id}/hybrid-run",
        json={
            "target_dir": str(target_dir),
            "parameters": {"prefix": "OK_"},
            "dry_run": False,
            "user_approved_understanding": False,
        },
    )
    assert blocked.status_code == 409
    assert (target_dir / "r1.txt").exists()

    # 3. Calling with dry_run=False AND user_approved_understanding=True executes on target_dir
    live_resp = client.post(
        f"/api/tasks/{task_id}/hybrid-run",
        json={
            "target_dir": str(target_dir),
            "parameters": {"prefix": "OK_"},
            "dry_run": False,
            "user_approved_understanding": True,
        },
    )
    assert live_resp.status_code == 200, live_resp.text
    live_data = live_resp.json()
    assert live_data["status"] == "verified"
    assert live_data["dry_run"] is False
    assert live_data["real_files_mutated"] is True
    assert (target_dir / "OK_r1.txt").exists()
    assert (target_dir / "OK_r2.txt").exists()
