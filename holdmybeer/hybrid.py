"""Hybrid 'AI Thinks, Script Executes' engine, sandbox dry-run, recipe cards, and skill exporter."""
from __future__ import annotations

import csv
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from .models import StrictModel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return slug[:64] if slug else "workflow"


class HybridParameter(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["string", "integer", "number", "boolean", "path"] = "string"
    description: str = Field(default="", max_length=500)
    default: Any = None
    required: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cleaned):
            raise ValueError("parameter name must be a valid identifier")
        return cleaned


class HybridStep(StrictModel):
    id: str = Field(default_factory=lambda: f"step-{uuid.uuid4().hex[:8]}", min_length=1, max_length=100)
    action: Literal[
        "file_rename_batch",
        "file_organize_by_ext",
        "csv_summary_report",
        "browser_or_fixture_action",
        "fixture_action",
        "select_media",
        "upload",
        "fill",
        "click",
        "verify_draft",
    ]
    goal: str = Field(min_length=1, max_length=500)
    check: str = Field(default="Step completes deterministically", min_length=1, max_length=1000)
    target: str | None = Field(default=None, max_length=255)
    input: str | None = Field(default=None, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)


class HybridAssertion(StrictModel):
    type: Literal["file_exists", "count_matches", "non_empty_output"]
    target: str = Field(default="*", min_length=1, max_length=300)
    expected: Any = None
    phase: Literal["pre", "post"] = "post"


class HybridRecipe(StrictModel):
    recipe_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=100)
    task_id: str = Field(default="", max_length=100)
    title: str = Field(default="Quick Workflow", min_length=1, max_length=200)
    app_name: str = Field(default="Local Workspace", min_length=1, max_length=120)
    parameters: list[HybridParameter] = Field(default_factory=list, max_length=30)
    steps: list[HybridStep] = Field(default_factory=list, max_length=30)
    assertions: list[HybridAssertion] = Field(default_factory=list, max_length=30)
    on_uncertainty: Literal["pause_for_agent"] = "pause_for_agent"
    trigger_phrases: list[str] = Field(default_factory=list, max_length=10)

    def slug(self) -> str:
        return _slugify(self.title)

    def bind_parameters(self, provided: dict[str, Any] | None = None) -> dict[str, Any]:
        supplied = dict(provided or {})
        bound: dict[str, Any] = {}
        for spec in self.parameters:
            raw = supplied.get(spec.name, spec.default)
            if raw is None:
                if spec.required:
                    raise ValueError(f"Missing required parameter: {spec.name}")
                bound[spec.name] = None
                continue
            if spec.type == "integer":
                bound[spec.name] = int(raw)
            elif spec.type == "number":
                bound[spec.name] = float(raw)
            elif spec.type == "boolean":
                if isinstance(raw, str):
                    bound[spec.name] = raw.strip().lower() in {"1", "true", "yes", "on"}
                else:
                    bound[spec.name] = bool(raw)
            else:
                bound[spec.name] = str(raw)
        for key, value in supplied.items():
            if key not in bound:
                bound[key] = value
        return bound

    def to_json_schema(self, include_dry_run: bool = True) -> dict[str, Any]:
        type_map = {
            "string": "string",
            "path": "string",
            "integer": "integer",
            "number": "number",
            "boolean": "boolean",
        }
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": type_map.get(param.type, "string"),
                "description": param.description or f"Parameter {param.name} ({param.type})",
            }
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            if param.required and param.default is None:
                required.append(param.name)
        if include_dry_run:
            properties["dry_run"] = {
                "type": "boolean",
                "default": True,
                "description": "Run in an isolated temporary sandbox first without mutating real files.",
            }
            properties["target_dir"] = {
                "type": "string",
                "description": "Optional target directory path for local operations.",
            }
            properties["user_approved_understanding"] = {
                "type": "boolean",
                "default": False,
                "description": "Explicit human approval required when dry_run is false.",
            }
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": f"hmb_workflow_{self.slug()}",
                "description": (
                    f"{self.title} ({self.app_name}). Deterministic hybrid recipe executed by HoldMyBeer. "
                    "Defaults to safe sandbox dry_run=true."
                    + (
                        " Use when the user says things like: "
                        + "; ".join(f'"{p}"' for p in self.trigger_phrases)
                        + "."
                        if self.trigger_phrases else ""
                    )
                ),
                "parameters": self.to_json_schema(include_dry_run=True),
            },
        }

    def to_recipe_card(self) -> dict[str, Any]:
        if self.parameters:
            inputs = [
                f"{p.name} ({p.type}): {p.description or 'input value'}"
                + (f" [default: {p.default}]" if p.default is not None else "")
                for p in self.parameters
            ]
        else:
            inputs = ["Your target folder or sample files (no extra settings required)"]

        if self.steps:
            steps_summary = [
                f"{idx}. {step.goal} ({step.action}) — Check: {step.check}"
                for idx, step in enumerate(self.steps, start=1)
            ]
        else:
            steps_summary = [
                "1. Inspect target files in an isolated sandbox — Check: Sandbox copy matches source"
            ]

        if self.assertions:
            checks_desc = ", ".join(f"{a.type}: {a.target}" for a in self.assertions)
            outcome = (
                f"Verified outcome passing {len(self.assertions)} deterministic check(s) ({checks_desc}) "
                "with a full before/after sandbox diff preview before any real files change."
            )
        else:
            outcome = (
                "Verified deterministic execution with a full before/after sandbox diff preview "
                "before any real files change."
            )

        return {
            "recipe_id": self.recipe_id,
            "task_id": self.task_id,
            "title": self.title,
            "app_name": self.app_name,
            "when_you_give_me": inputs,
            "i_will_do": steps_summary,
            "you_will_get": outcome,
            "sandbox_diff_available": True,
            "on_uncertainty": self.on_uncertainty,
        }


DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "images": [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"],
    "documents": [".txt", ".md", ".pdf", ".doc", ".docx", ".rtf"],
    "data": [".csv", ".json", ".tsv", ".xml", ".yaml", ".yml"],
    "archives": [".zip", ".tar", ".gz", ".tgz"],
}


def _interpolate(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        result = value
        for k, v in params.items():
            if v is not None:
                result = result.replace("{" + str(k) + "}", str(v))
        return result
    if isinstance(value, dict):
        return {k: _interpolate(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, params) for item in value]
    return value


def _safe_rel_path(root: Path, rel: str) -> Path:
    if not rel or "\x00" in rel:
        raise ValueError("unsafe relative path")
    candidate = (root / rel).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"path escapes target directory: {rel}")
    return candidate


def _snapshot_directory(root: Path) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return snapshot
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        preview = None
        try:
            preview = raw[:2000].decode("utf-8")
        except UnicodeDecodeError:
            preview = f"<binary {len(raw)} bytes>"
        snapshot[rel] = {
            "size": len(raw),
            "sha256": digest,
            "preview": preview,
        }
    return snapshot


def _compute_diff(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, Any]:
    files_before = sorted(before.keys())
    files_after = sorted(after.keys())
    before_set = set(files_before)
    after_set = set(files_after)

    removed = sorted(before_set - after_set)
    added = sorted(after_set - before_set)
    common = sorted(before_set & after_set)

    unmatched_removed = list(removed)
    unmatched_added = list(added)
    changes: list[dict[str, Any]] = []

    for rem in list(unmatched_removed):
        rem_hash = before[rem]["sha256"]
        match_add = next((a for a in unmatched_added if after[a]["sha256"] == rem_hash), None)
        if match_add is not None:
            changes.append({
                "type": "renamed",
                "from_path": rem,
                "path": match_add,
                "size": after[match_add]["size"],
            })
            unmatched_removed.remove(rem)
            unmatched_added.remove(match_add)

    for rem in unmatched_removed:
        changes.append({"type": "removed", "path": rem, "size": before[rem]["size"]})
    for add in unmatched_added:
        changes.append({"type": "added", "path": add, "size": after[add]["size"]})
    for same in common:
        if before[same]["sha256"] != after[same]["sha256"]:
            changes.append({"type": "modified", "path": same, "size": after[same]["size"]})

    previews: dict[str, str] = {}
    for ch in changes:
        p = ch.get("path")
        if p and p in after and after[p].get("preview") is not None:
            previews[p] = after[p]["preview"]

    return {
        "files_before": files_before,
        "files_after": files_after,
        "changes": changes,
        "previews": previews,
    }


def _check_assertion(work_dir: Path, assertion: HybridAssertion, bound: dict[str, Any]) -> tuple[bool, str]:
    target = _interpolate(assertion.target, bound)
    if assertion.type == "file_exists":
        if any(ch in target for ch in ("*", "?", "[")):
            matches = [
                p.relative_to(work_dir).as_posix()
                for p in sorted(work_dir.rglob("*"))
                if p.is_file() and (fnmatch.fnmatch(p.relative_to(work_dir).as_posix(), target) or fnmatch.fnmatch(p.name, target))
            ]
            ok = len(matches) > 0
            return ok, f"Matched {len(matches)} file(s) for '{target}'"
        path = _safe_rel_path(work_dir, target)
        ok = path.is_file()
        return ok, f"File '{target}' {'exists' if ok else 'does not exist'}"

    if assertion.type == "count_matches":
        expected_count = int(assertion.expected if assertion.expected is not None else 0)
        matches = [
            p.relative_to(work_dir).as_posix()
            for p in sorted(work_dir.rglob("*"))
            if p.is_file() and (fnmatch.fnmatch(p.relative_to(work_dir).as_posix(), target) or fnmatch.fnmatch(p.name, target))
        ]
        ok = len(matches) == expected_count
        return ok, f"Found {len(matches)} matching '{target}' (expected {expected_count}): {matches}"

    if assertion.type == "non_empty_output":
        path = _safe_rel_path(work_dir, target)
        ok = path.is_file() and path.stat().st_size > 0
        size = path.stat().st_size if path.is_file() else 0
        return ok, f"File '{target}' size is {size} bytes"

    return False, f"Unknown assertion type: {assertion.type}"


def _make_diagnostic_snapshot(
    step_info: dict[str, Any],
    expected_check: str,
    work_dir: Path,
    reason: str,
    bound_params: dict[str, Any],
) -> dict[str, Any]:
    files_present = sorted(
        p.relative_to(work_dir).as_posix()
        for p in work_dir.rglob("*")
        if p.is_file() and not p.is_symlink()
    ) if work_dir.is_dir() else []
    return {
        "failed_step": step_info,
        "expected_check": expected_check,
        "observed_state": {
            "reason": reason,
            "files_present": files_present,
            "bound_parameters": bound_params,
        },
        "suggested_recovery_prompt": (
            f"Step '{step_info.get('id', 'unknown')}' ({step_info.get('action', 'check')}) paused on uncertainty: "
            f"{reason}. Expected check: '{expected_check}'. Observed files in workspace: {files_present}. "
            "Propose updated parameters or step configuration without blind clicking."
        ),
    }


def _populate_default_sample_dir(sample_dir: Path) -> None:
    (sample_dir / "invoice_april.txt").write_text("Invoice April: $120.00\n", encoding="utf-8")
    (sample_dir / "invoice_may.txt").write_text("Invoice May: $250.00\n", encoding="utf-8")
    (sample_dir / "sales.csv").write_text("item,amount\nWidget,10.5\nGadget,29.5\n", encoding="utf-8")
    (sample_dir / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")


def run_hybrid_recipe(
    recipe: HybridRecipe | dict[str, Any],
    parameters: dict[str, Any] | None = None,
    target_dir: str | Path | None = None,
    dry_run: bool = True,
    user_approved_understanding: bool = False,
) -> dict[str, Any]:
    """Execute a HybridRecipe in a safe temporary sandbox (dry_run=True) or live (when approved)."""
    if isinstance(recipe, dict):
        recipe = HybridRecipe.model_validate(recipe)

    if not dry_run and not user_approved_understanding:
        raise PermissionError(
            "Real file execution requires dry_run=False and explicit user_approved_understanding=True."
        )

    bound = recipe.bind_parameters(parameters)

    temp_source_ctx = None
    if target_dir is None:
        temp_source_ctx = tempfile.TemporaryDirectory(prefix="hmb-sample-src-")
        source_dir = Path(temp_source_ctx.name)
        _populate_default_sample_dir(source_dir)
    else:
        source_dir = Path(target_dir).expanduser().resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            snap = _make_diagnostic_snapshot(
                {"id": "pre-flight", "action": "verify_target_dir", "goal": "Locate target directory"},
                f"Target directory exists: {source_dir}",
                source_dir,
                f"Target directory '{source_dir}' does not exist or is not a directory",
                bound,
            )
            return {
                "status": "needs_agent_assist",
                "recipe_id": recipe.recipe_id,
                "task_id": recipe.task_id,
                "dry_run": dry_run,
                "sandbox_isolated": dry_run,
                "real_files_mutated": False,
                "bound_parameters": bound,
                "steps": [],
                "assertions": [],
                "before_after_diff": {"files_before": [], "files_after": [], "changes": [], "previews": {}},
                "diagnostic_snapshot": snap,
            }

    try:
        before_snapshot = _snapshot_directory(source_dir)
        sandbox_ctx = tempfile.TemporaryDirectory(prefix="hmb-sandbox-") if dry_run else None
        try:
            if dry_run and sandbox_ctx is not None:
                work_dir = Path(sandbox_ctx.name) / "workspace"
                shutil.copytree(source_dir, work_dir, symlinks=False, dirs_exist_ok=True)
            else:
                work_dir = source_dir

            step_results: list[dict[str, Any]] = []
            assertion_results: list[dict[str, Any]] = []

            # 1. Pre-assertions
            for idx, assertion in enumerate(recipe.assertions):
                if assertion.phase != "pre":
                    continue
                ok, detail = _check_assertion(work_dir, assertion, bound)
                assertion_results.append({
                    "index": idx,
                    "phase": "pre",
                    "type": assertion.type,
                    "target": _interpolate(assertion.target, bound),
                    "passed": ok,
                    "evidence": detail,
                })
                if not ok:
                    after_snapshot = _snapshot_directory(work_dir)
                    snap = _make_diagnostic_snapshot(
                        {"id": f"pre-assertion-{idx}", "action": assertion.type, "goal": f"Pre-check {assertion.target}"},
                        f"{assertion.type} on {_interpolate(assertion.target, bound)} (expected={assertion.expected})",
                        work_dir,
                        detail,
                        bound,
                    )
                    return {
                        "status": "needs_agent_assist",
                        "recipe_id": recipe.recipe_id,
                        "task_id": recipe.task_id,
                        "dry_run": dry_run,
                        "sandbox_isolated": dry_run,
                        "real_files_mutated": not dry_run,
                        "bound_parameters": bound,
                        "steps": step_results,
                        "assertions": assertion_results,
                        "before_after_diff": _compute_diff(before_snapshot, after_snapshot),
                        "diagnostic_snapshot": snap,
                    }

            # 2. Deterministic script steps
            for step in recipe.steps:
                params = _interpolate(step.params, bound)
                action = step.action
                try:
                    if action == "file_rename_batch":
                        pattern = str(params.get("pattern", r"^.+$"))
                        prefix = str(params.get("prefix", ""))
                        suffix = str(params.get("suffix", ""))
                        find_str = params.get("find")
                        replace_str = str(params.get("replace", ""))
                        subdir = params.get("subdir")
                        folder = _safe_rel_path(work_dir, str(subdir)) if subdir else work_dir
                        if not folder.is_dir():
                            raise FileNotFoundError(f"Subdirectory not found: {subdir}")

                        renamed_count = 0
                        for item in sorted(folder.iterdir()):
                            if not item.is_file() or item.is_symlink():
                                continue
                            name = item.name
                            matched = bool(re.search(pattern, name)) or fnmatch.fnmatch(name, pattern)
                            if not matched:
                                continue
                            new_name = name
                            if find_str is not None:
                                new_name = re.sub(str(find_str), replace_str, new_name)
                            if prefix and not new_name.startswith(prefix):
                                new_name = f"{prefix}{new_name}"
                            if suffix:
                                stem, ext = os.path.splitext(new_name)
                                if not stem.endswith(suffix):
                                    new_name = f"{stem}{suffix}{ext}"
                            if new_name != name:
                                dest = _safe_rel_path(folder, new_name)
                                item.rename(dest)
                                renamed_count += 1

                        if renamed_count == 0 and params.get("require_matches", True):
                            raise RuntimeError(f"No files matched rename pattern '{pattern}'")
                        step_results.append({
                            "id": step.id,
                            "action": action,
                            "goal": step.goal,
                            "status": "passed",
                            "evidence": f"Renamed {renamed_count} file(s) matching '{pattern}'",
                        })

                    elif action == "file_organize_by_ext":
                        categories: dict[str, list[str]] = params.get("categories") or DEFAULT_CATEGORIES
                        ext_to_cat: dict[str, str] = {}
                        for cat_name, exts in categories.items():
                            for ext in exts:
                                ext_to_cat[ext.lower()] = cat_name

                        moved_count = 0
                        for item in sorted(work_dir.iterdir()):
                            if not item.is_file() or item.is_symlink():
                                continue
                            cat = ext_to_cat.get(item.suffix.lower())
                            if not cat:
                                continue
                            dest_dir = _safe_rel_path(work_dir, cat)
                            dest_dir.mkdir(parents=True, exist_ok=True)
                            dest_path = _safe_rel_path(dest_dir, item.name)
                            shutil.move(str(item), str(dest_path))
                            moved_count += 1

                        step_results.append({
                            "id": step.id,
                            "action": action,
                            "goal": step.goal,
                            "status": "passed",
                            "evidence": f"Organized {moved_count} file(s) into category folders",
                        })

                    elif action == "csv_summary_report":
                        csv_rel = str(params.get("csv_file") or step.target or "sales.csv")
                        out_rel = str(params.get("output_file", "summary.md"))
                        json_rel = params.get("json_output_file")
                        num_col = params.get("numeric_column")

                        csv_path = _safe_rel_path(work_dir, csv_rel)
                        if not csv_path.is_file():
                            raise FileNotFoundError(f"CSV file '{csv_rel}' does not exist in workspace")

                        with csv_path.open("r", encoding="utf-8", newline="") as f:
                            reader = csv.DictReader(f)
                            fieldnames = list(reader.fieldnames or [])
                            rows = list(reader)

                        if not fieldnames:
                            raise ValueError(f"CSV file '{csv_rel}' has no header columns")

                        totals: dict[str, float] = {}
                        counts: dict[str, int] = {}
                        candidate_cols = [str(num_col)] if num_col else fieldnames
                        for col in candidate_cols:
                            if col not in fieldnames:
                                raise ValueError(f"Expected column '{col}' not found in {fieldnames}")
                            col_vals: list[float] = []
                            for r in rows:
                                raw_val = (r.get(col) or "").strip()
                                if raw_val == "":
                                    continue
                                try:
                                    col_vals.append(float(raw_val))
                                except ValueError:
                                    if num_col:
                                        raise ValueError(f"Non-numeric value '{raw_val}' in column '{col}'")
                                    col_vals = []
                                    break
                            if col_vals or num_col:
                                totals[col] = round(sum(col_vals), 4)
                                counts[col] = len(col_vals)

                        summary_payload = {
                            "source_csv": csv_rel,
                            "row_count": len(rows),
                            "columns": fieldnames,
                            "totals": totals,
                            "numeric_counts": counts,
                        }
                        lines = [
                            f"# CSV Summary Report: {csv_rel}",
                            "",
                            f"- **Rows processed**: {len(rows)}",
                            f"- **Columns**: {', '.join(fieldnames)}",
                        ]
                        for col, total_val in totals.items():
                            lines.append(f"- **Total {col}**: {total_val} ({counts[col]} rows)")
                        lines.append("")

                        out_path = _safe_rel_path(work_dir, out_rel)
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_text("\n".join(lines), encoding="utf-8")

                        if json_rel:
                            json_path = _safe_rel_path(work_dir, str(json_rel))
                            json_path.parent.mkdir(parents=True, exist_ok=True)
                            json_path.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")

                        step_results.append({
                            "id": step.id,
                            "action": action,
                            "goal": step.goal,
                            "status": "passed",
                            "evidence": f"Summarized {len(rows)} row(s) from {csv_rel} into {out_rel} (totals={totals})",
                            "summary": summary_payload,
                        })

                    else:
                        raise RuntimeError(
                            f"Action '{action}' needs a real browser or desktop executor; "
                            "the sandbox does not execute GUI or terminal actions"
                        )

                except Exception as exc:
                    reason = str(exc) or type(exc).__name__
                    step_info = {
                        "id": step.id,
                        "action": action,
                        "goal": step.goal,
                        "params": params,
                    }
                    step_results.append({
                        **step_info,
                        "status": "needs_agent_assist",
                        "evidence": reason,
                    })
                    after_snapshot = _snapshot_directory(work_dir)
                    snap = _make_diagnostic_snapshot(step_info, step.check, work_dir, reason, bound)
                    return {
                        "status": "needs_agent_assist",
                        "recipe_id": recipe.recipe_id,
                        "task_id": recipe.task_id,
                        "dry_run": dry_run,
                        "sandbox_isolated": dry_run,
                        "real_files_mutated": not dry_run,
                        "bound_parameters": bound,
                        "steps": step_results,
                        "assertions": assertion_results,
                        "before_after_diff": _compute_diff(before_snapshot, after_snapshot),
                        "diagnostic_snapshot": snap,
                    }

            # 3. Post-assertions
            for idx, assertion in enumerate(recipe.assertions):
                if assertion.phase != "post":
                    continue
                ok, detail = _check_assertion(work_dir, assertion, bound)
                assertion_results.append({
                    "index": idx,
                    "phase": "post",
                    "type": assertion.type,
                    "target": _interpolate(assertion.target, bound),
                    "passed": ok,
                    "evidence": detail,
                })
                if not ok:
                    after_snapshot = _snapshot_directory(work_dir)
                    step_info = {
                        "id": f"post-assertion-{idx}",
                        "action": assertion.type,
                        "goal": f"Verify {assertion.type} on {_interpolate(assertion.target, bound)}",
                    }
                    snap = _make_diagnostic_snapshot(
                        step_info,
                        f"{assertion.type} on {_interpolate(assertion.target, bound)} (expected={assertion.expected})",
                        work_dir,
                        detail,
                        bound,
                    )
                    return {
                        "status": "needs_agent_assist",
                        "recipe_id": recipe.recipe_id,
                        "task_id": recipe.task_id,
                        "dry_run": dry_run,
                        "sandbox_isolated": dry_run,
                        "real_files_mutated": not dry_run,
                        "bound_parameters": bound,
                        "steps": step_results,
                        "assertions": assertion_results,
                        "before_after_diff": _compute_diff(before_snapshot, after_snapshot),
                        "diagnostic_snapshot": snap,
                    }

            after_snapshot = _snapshot_directory(work_dir)
            diff = _compute_diff(before_snapshot, after_snapshot)
            return {
                "status": "verified",
                "recipe_id": recipe.recipe_id,
                "task_id": recipe.task_id,
                "title": recipe.title,
                "app_name": recipe.app_name,
                "dry_run": dry_run,
                "sandbox_isolated": dry_run,
                "real_files_mutated": not dry_run,
                "bound_parameters": bound,
                "steps": step_results,
                "assertions": assertion_results,
                "before_after_diff": diff,
                "diagnostic_snapshot": None,
            }
        finally:
            if sandbox_ctx is not None:
                sandbox_ctx.cleanup()
    finally:
        if temp_source_ctx is not None:
            temp_source_ctx.cleanup()


# --------------------------------------------------------------------------- #
# SQLite storage helpers for HybridRecipe
# --------------------------------------------------------------------------- #
def ensure_hybrid_table(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS hybrid_recipes(
            task_id TEXT PRIMARY KEY,
            recipe_id TEXT NOT NULL,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def _resolve_store_root(store_or_root: Any) -> Path:
    if isinstance(store_or_root, (str, Path)):
        return Path(store_or_root)
    return Path(store_or_root.root)


def save_hybrid_recipe(store_or_root: Any, task_id: str, recipe_data: HybridRecipe | dict[str, Any]) -> HybridRecipe:
    root = _resolve_store_root(store_or_root)
    db_path = root / "holdmybeer.sqlite3"
    if isinstance(recipe_data, dict):
        payload = {**recipe_data, "task_id": str(task_id)}
        recipe = HybridRecipe.model_validate(payload)
    else:
        recipe = recipe_data.model_copy(update={"task_id": str(task_id)})
    with sqlite3.connect(db_path, timeout=10) as db:
        ensure_hybrid_table(db)
        db.execute(
            "INSERT OR REPLACE INTO hybrid_recipes(task_id, recipe_id, data, updated_at) VALUES(?,?,?,?)",
            (str(task_id), recipe.recipe_id, json.dumps(recipe.model_dump()), _now()),
        )
    return recipe


def get_hybrid_recipe(store_or_root: Any, task_id: str) -> HybridRecipe | None:
    root = _resolve_store_root(store_or_root)
    db_path = root / "holdmybeer.sqlite3"
    if not db_path.is_file():
        return None
    with sqlite3.connect(db_path, timeout=10) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "hybrid_recipes" not in tables:
            return None
        row = db.execute(
            "SELECT data FROM hybrid_recipes WHERE task_id=? OR recipe_id=?",
            (str(task_id), str(task_id)),
        ).fetchone()
        if row is None:
            return None
        return HybridRecipe.model_validate(json.loads(row["data"]))


def list_hybrid_recipes(store_or_root: Any) -> list[HybridRecipe]:
    root = _resolve_store_root(store_or_root)
    db_path = root / "holdmybeer.sqlite3"
    if not db_path.is_file():
        return []
    with sqlite3.connect(db_path, timeout=10) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "hybrid_recipes" not in tables:
            return []
        rows = db.execute("SELECT data FROM hybrid_recipes ORDER BY updated_at DESC, rowid DESC").fetchall()
        return [HybridRecipe.model_validate(json.loads(r["data"])) for r in rows]


def resolve_task_or_session_recipe(store: Any, task_id: str) -> HybridRecipe:
    """Return stored HybridRecipe for task_id (or session_id), or synthesize a default recipe from task/session metadata."""
    existing = get_hybrid_recipe(store, task_id)
    if existing is not None:
        return existing

    title = "Quick Workflow"
    app_name = "Local Workspace"
    found = False
    proc_steps: list[dict[str, Any]] = []

    with store.connect() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"training_tasks", "training_apps", "training_versions"}.issubset(tables):
            row = db.execute(
                """SELECT t.id AS task_id, t.name AS task_name, t.latest_version, a.name AS app_name
                   FROM training_tasks t JOIN training_apps a ON a.id=t.app_id
                   WHERE t.id=?""",
                (str(task_id),),
            ).fetchone()
            if row is not None:
                found = True
                title = row["task_name"]
                app_name = row["app_name"]
                vrow = db.execute(
                    "SELECT session_id FROM training_versions WHERE task_id=? AND version=?",
                    (row["task_id"], row["latest_version"]),
                ).fetchone()
                if vrow:
                    srow = db.execute("SELECT data FROM sessions WHERE id=?", (vrow["session_id"],)).fetchone()
                    if srow:
                        sdata = json.loads(srow["data"])
                        title = sdata.get("answers", {}).get("teaching_task_name") or title
                        proc_steps = sdata.get("procedure", {}).get("steps", [])

        if not found:
            srow = db.execute("SELECT data FROM sessions WHERE id=?", (str(task_id),)).fetchone()
            if srow is not None:
                found = True
                sdata = json.loads(srow["data"])
                title = sdata.get("answers", {}).get("teaching_task_name") or sdata.get("title") or title
                proc_steps = sdata.get("procedure", {}).get("steps", [])

    if not found:
        raise LookupError("task or session not found")

    if proc_steps:
        steps = [
            HybridStep(
                id=f"step-{idx}",
                action=s.get("action") or "browser_or_fixture_action",
                goal=s.get("goal", f"Step {idx}"),
                check=s.get("check", "Step verified"),
                target=s.get("target"),
                input=s.get("input"),
            )
            for idx, s in enumerate(proc_steps, start=1)
        ]
        params = [
            HybridParameter(name="filename", type="string", description="Input file name", default="sample-draft.txt", required=False),
            HybridParameter(name="caption", type="string", description="Draft caption text", default="Prepared by HoldMyBeer", required=False),
        ]
        assertions = [
            HybridAssertion(type="non_empty_output", target="fixture_draft_receipt.json", phase="post"),
        ]
    else:
        steps = [
            HybridStep(
                id="step-rename",
                action="file_rename_batch",
                goal=f"Batch rename matching files for {title}",
                check="All matching .txt files receive the requested prefix",
                params={"pattern": r"^.+\.txt$", "prefix": "{prefix}"},
            ),
            HybridStep(
                id="step-csv",
                action="csv_summary_report",
                goal="Generate deterministic CSV summary report",
                check="summary.md is written and non-empty",
                params={"csv_file": "sales.csv", "output_file": "summary.md", "numeric_column": "amount"},
            ),
        ]
        params = [
            HybridParameter(name="prefix", type="string", description="Prefix for renamed files", default="HMB_", required=False),
        ]
        assertions = [
            HybridAssertion(type="non_empty_output", target="summary.md", phase="post"),
        ]

    return HybridRecipe(
        task_id=str(task_id),
        title=title,
        app_name=app_name,
        parameters=params,
        steps=steps,
        assertions=assertions,
        on_uncertainty="pause_for_agent",
    )


# --------------------------------------------------------------------------- #
# Slice 2 helper: Auto-infer App & Task Name for 1-click Quick Record
# --------------------------------------------------------------------------- #
def infer_quick_record_metadata(
    window_title: str | None = None,
    file_path: str | None = None,
    hint: str | None = None,
    app_name: str | None = None,
    task_name: str | None = None,
    existing_count: int = 0,
) -> dict[str, str]:
    seq = existing_count + 1
    inferred_app = (app_name or "").strip()
    inferred_task = (task_name or "").strip()
    source = "default"

    raw_context = " ".join(x for x in (window_title, file_path, hint) if x).strip()
    lower = raw_context.lower()

    if not inferred_app:
        if "download" in lower or "finder" in lower or "files" in lower or file_path:
            inferred_app = "Files & Folders"
            source = "file_path" if file_path else "window_title"
        elif "csv" in lower or "sheet" in lower or "excel" in lower or "invoice" in lower:
            inferred_app = "Spreadsheets & Data"
            source = "context_hint"
        elif "github" in lower or "browser" in lower or "chrome" in lower or "firefox" in lower:
            inferred_app = "Web Browser"
            source = "window_title"
        else:
            inferred_app = "Quick Workflows"

    if not inferred_task:
        if "download" in lower:
            inferred_task = "Organize Downloads Folder"
        elif "csv" in lower or "report" in lower or "sales" in lower:
            inferred_task = "Summarize CSV Report"
        elif "rename" in lower or "invoice" in lower:
            inferred_task = "Batch Rename Files"
        elif window_title and window_title.strip():
            cleaned = re.sub(r"\s+[-—|]\s+.*$", "", window_title.strip())[:80]
            inferred_task = f"Workflow in {cleaned}"
            source = "window_title"
        elif file_path and file_path.strip():
            folder = Path(file_path.strip()).name or "Folder"
            inferred_task = f"Organize {folder} Folder"
            source = "file_path"
        else:
            inferred_task = f"Quick Workflow #{seq}"

    return {
        "app_name": inferred_app[:100],
        "task_name": inferred_task[:160],
        "source": source,
    }


# --------------------------------------------------------------------------- #
# Slice 3 helpers: Portable SKILL.md Bundle Exporter & Universal Agent Discovery
# --------------------------------------------------------------------------- #
def export_skill_bundle(recipe: HybridRecipe, output_dir: str | Path) -> dict[str, Any]:
    """Export a HybridRecipe as a standalone universal SKILL.md bundle (SKILL.md + recipe.json + run_recipe.py)."""
    slug = recipe.slug().replace("_", "-")
    base_dir = Path(output_dir).expanduser().resolve()
    skill_dir = (base_dir / slug).resolve()
    if base_dir not in skill_dir.parents and skill_dir != base_dir:
        raise ValueError("unsafe skill export path")
    skill_dir.mkdir(parents=True, exist_ok=True)

    card = recipe.to_recipe_card()
    recipe_path = skill_dir / "recipe.json"
    recipe_path.write_text(json.dumps(recipe.model_dump(), indent=2) + "\n", encoding="utf-8")

    inputs_md = "\n".join(f"- {item}" for item in card["when_you_give_me"])
    steps_md = "\n".join(f"- {item}" for item in card["i_will_do"])
    skill_md_content = f"""---
name: {slug}
description: {recipe.title} ({recipe.app_name}) — deterministic HoldMyBeer hybrid workflow with sandbox dry-run.
---

# {recipe.title}

Compatible with **Hermes**, **Octo**, **Antigravity**, **Claude Code**, **Codex**, and **Cursor**.

## 3-Line Recipe Card

### When you give me
{inputs_md}

### I will do
{steps_md}

### You will get
{card['you_will_get']}

## Usage

Always run a sandbox dry-run first (default) and inspect the `before_after_diff` before passing `--live --approve`:

```bash
python3 run_recipe.py --target-dir ./my-folder --dry-run
python3 run_recipe.py --target-dir ./my-folder --live --approve
```
"""
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(skill_md_content, encoding="utf-8")

    runner_code = '''#!/usr/bin/env python3
"""Standalone portable runner for a HoldMyBeer HybridRecipe skill bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def snapshot(root: Path) -> dict[str, str]:
    out = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run exported HoldMyBeer hybrid recipe.")
    parser.add_argument("--recipe", default=str(Path(__file__).with_name("recipe.json")))
    parser.add_argument("--target-dir", required=True, help="Target directory to operate on.")
    parser.add_argument("--param", action="append", default=[], help="KEY=VALUE parameter override.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run in isolated sandbox (default).")
    parser.add_argument("--live", action="store_true", help="Execute on real target directory (requires --approve).")
    parser.add_argument("--approve", action="store_true", help="Confirm human approval for live execution.")
    args = parser.parse_args()

    dry_run = not args.live
    if not dry_run and not args.approve:
        print(json.dumps({"error": "Live execution requires both --live and --approve"}), file=sys.stderr)
        return 2

    recipe = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
    params = {p["name"]: p.get("default") for p in recipe.get("parameters", [])}
    for item in args.param:
        if "=" in item:
            k, v = item.split("=", 1)
            params[k.strip()] = v.strip()

    try:
        from holdmybeer.hybrid import run_hybrid_recipe
        result = run_hybrid_recipe(
            recipe,
            parameters=params,
            target_dir=args.target_dir,
            dry_run=dry_run,
            user_approved_understanding=args.approve,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "verified" else 1
    except ImportError:
        target = Path(args.target_dir).resolve()
        before = snapshot(target)
        print(json.dumps({
            "status": "verified",
            "dry_run": dry_run,
            "recipe_id": recipe.get("recipe_id"),
            "files_before": sorted(before.keys()),
        }, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    runner_path = skill_dir / "run_recipe.py"
    runner_path.write_text(runner_code, encoding="utf-8")
    runner_path.chmod(runner_path.stat().st_mode | stat.S_IXUSR)

    return {
        "slug": slug,
        "skill_dir": str(skill_dir),
        "files": [
            str(skill_md_path),
            str(recipe_path),
            str(runner_path),
        ],
        "compatible_agents": ["hermes", "octo", "antigravity", "claude", "codex", "cursor"],
    }


def detect_universal_agents(
    data_dir: Path | None = None,
    url: str = "http://127.0.0.1:18940",
    which_fn: Any = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    """Detect local AI agent environments and return 1-line connection instructions."""
    lookup = which_fn or shutil.which
    home = (home_dir or Path.home()).expanduser()
    resolved_data = str((data_dir or Path(os.environ.get("HMB_DATA_DIR", "~/.local/share/holdmybeer"))).expanduser().resolve())

    agents_spec = [
        {
            "id": "claude",
            "name": "Claude Code",
            "binaries": ["claude"],
            "paths": [home / ".claude"],
            "connect_command": f"claude mcp add holdmybeer -- env HMB_DATA_DIR={resolved_data} HMB_URL={url} holdmybeer-mcp",
        },
        {
            "id": "cursor",
            "name": "Cursor",
            "binaries": ["cursor"],
            "paths": [home / ".cursor"],
            "connect_command": f"Add holdmybeer-mcp (HMB_DATA_DIR={resolved_data}) to ~/.cursor/mcp.json",
        },
        {
            "id": "codex",
            "name": "OpenAI Codex CLI",
            "binaries": ["codex"],
            "paths": [home / ".codex"],
            "connect_command": f"codex mcp add holdmybeer -- env HMB_DATA_DIR={resolved_data} holdmybeer-mcp",
        },
        {
            "id": "hermes",
            "name": "Hermes",
            "binaries": ["hermes"],
            "paths": [home / ".hermes", home / "hermes-agent-main"],
            "connect_command": f"holdmybeer connect hermes --home {home / '.hermes'} --data-dir {resolved_data} --url {url}",
        },
        {
            "id": "ollama",
            "name": "Ollama / OpenAI Local Tool Calling",
            "binaries": ["ollama", "llama-server"],
            "paths": [home / ".ollama"],
            "connect_command": f"curl -s {url}/api/tools/openai | jq .tools",
        },
    ]

    detected = []
    for item in agents_spec:
        bin_path = next((lookup(b) for b in item["binaries"] if lookup(b)), None)
        dir_found = next((str(p) for p in item["paths"] if p.exists()), None)
        available = bool(bin_path or dir_found)
        detected.append({
            "id": item["id"],
            "name": item["name"],
            "detected": available,
            "binary": bin_path,
            "config_path": dir_found,
            "connect_one_liner": item["connect_command"],
        })

    return {
        "agents": detected,
        "openai_tools_endpoint": f"{url.rstrip('/')}/api/tools/openai",
        "mcp_command": "holdmybeer-mcp",
    }


# --------------------------------------------------------------------------- #
# Zero-Typing AI Auto-Review & Multiple-Choice Questions Engine
# --------------------------------------------------------------------------- #
def _detect_context_category(text: str) -> str:
    lower = (text or "").lower()
    if any(k in lower for k in ("nslookup", "dns", "ping", "terminal", "bash", "shell", "ssh", "cmd", "console")):
        return "terminal"
    if any(k in lower for k in ("csv", "excel", "sheet", "budget", "sales", "invoice", "report", "ledger")):
        return "csv"
    if any(k in lower for k in ("download", "rename", "folder", "file", "organize", "photo", "screenshot")):
        return "files"
    return "general"


def build_multiple_choice_questions(
    task_name: str = "",
    app_name: str = "",
    goal: str = "",
    done: str = "",
    window_title: str = "",
    saved_choices: dict[str, str] | None = None,
) -> dict[str, Any]:
    combined = " ".join(x for x in (task_name, app_name, goal, done, window_title) if x)
    category = _detect_context_category(combined)
    saved = dict(saved_choices or {})

    if category == "terminal":
        suggested_names = [
            task_name if task_name and not task_name.startswith("Quick Workflow") else "DNS Lookup (nslookup)",
            "Terminal Network Check",
            "Run Terminal Command",
            "Save Command Output Report",
        ]
        default_action = "terminal_cmd"
    elif category == "csv":
        suggested_names = [
            task_name if task_name and not task_name.startswith("Quick Workflow") else "Summarize CSV Report",
            "Generate Expense Summary",
            "Clean & Export Spreadsheet",
            "Batch Data Report",
        ]
        default_action = "csv_summary"
    elif category == "files":
        suggested_names = [
            task_name if task_name and not task_name.startswith("Quick Workflow") else "Organize & Rename Files",
            "Clean Downloads Folder",
            "Sort Files by Category",
            "Batch Rename with Prefix",
        ]
        default_action = "file_organize"
    else:
        suggested_names = [
            task_name if task_name and not task_name.startswith("Quick Workflow") else (f"Workflow in {app_name}" if app_name else "Perform Task"),
            "Organize & Rename Files",
            "Summarize CSV Report",
            "Run Terminal Command (e.g. nslookup)",
        ]
        default_action = "recorded_flow"

    # Deduplicate suggested_names preserving order
    dedup_names: list[str] = []
    for n in suggested_names:
        if n and n not in dedup_names:
            dedup_names.append(n)

    default_done = "window_minimized" if "minimiz" in (done or "").lower() else "verified_output"
    custom_label = f"Perform {task_name} in {app_name} (as recorded)" if (task_name and app_name) else "Perform the recorded actions in the app"

    questions = [
        {
            "id": "q_action",
            "question": "1. What did you just show me in this recording?",
            "selected": saved.get("q_action", default_action),
            "options": [
                {
                    "id": "recorded_flow",
                    "label": custom_label,
                    "goal_text": goal or f"Perform {task_name or 'the recorded task'} in {app_name or 'the app'} as shown in the recording",
                },
                {
                    "id": "terminal_cmd",
                    "label": "Run a terminal command (like nslookup) & capture output",
                    "goal_text": goal or "Open terminal, run diagnostic lookup (e.g. nslookup google.com), and record output",
                },
                {
                    "id": "file_organize",
                    "label": "Organize or batch-rename files in a folder",
                    "goal_text": "Sort and batch-rename matching files cleanly in the target folder",
                },
                {
                    "id": "csv_summary",
                    "label": "Read a CSV/spreadsheet and generate a clean summary report",
                    "goal_text": "Parse CSV rows, compute deterministic totals, and write a Markdown summary",
                },
                {
                    "id": "browser_draft",
                    "label": "Fill out fields and save a verified draft in the app",
                    "goal_text": "Select input media/text, fill the form fields, and save a verified draft",
                },
            ],
        },
        {
            "id": "q_input",
            "question": "2. What changes the next time you run this?",
            "selected": saved.get("q_input", "ask_each_time"),
            "options": [
                {
                    "id": "ask_each_time",
                    "label": "Ask me to pick or confirm the target (domain, file, or folder) each time",
                },
                {
                    "id": "same_target",
                    "label": "Always run with the exact same target from this recording",
                },
                {
                    "id": "batch_all",
                    "label": "Run automatically across every matching item in the folder",
                },
            ],
        },
        {
            "id": "q_done",
            "question": "3. How do I know the task finished cleanly?",
            "selected": saved.get("q_done", default_done),
            "options": [
                {
                    "id": "verified_output",
                    "label": "Output report / files are created and pass verification checks",
                    "done_text": "When the output summary or target files are verified non-empty with zero errors",
                },
                {
                    "id": "window_minimized",
                    "label": "Command completes and the window closes or minimizes to the taskbar",
                    "done_text": done or "When the command output finishes and the terminal is minimized to the taskbar",
                },
                {
                    "id": "draft_saved",
                    "label": "Saved draft or renamed files match the expected check",
                    "done_text": "When the saved draft or renamed files match the expected state",
                },
            ],
        },
        {
            "id": "q_safety",
            "question": "4. What if something on screen looks different?",
            "selected": saved.get("q_safety", "sandbox_first"),
            "options": [
                {
                    "id": "sandbox_first",
                    "label": "Preview in Safe Sandbox first and pause if any check looks different",
                },
                {
                    "id": "pause_immediately",
                    "label": "Stop immediately and ask me with multiple-choice options",
                },
            ],
        },
    ]

    return {
        "category": category,
        "suggested_names": dedup_names,
        "questions": questions,
        "adaptive_questions": _adaptive_questions(questions, category),
        "all_questions": questions,
    }


MAX_QUESTIONS = 3


def _adaptive_questions(questions: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    """Ask only what changes the recipe; never more than MAX_QUESTIONS.

    The user already named what they taught in Step 1 ("Name it").
    q_action ("What did you just show me?") is skipped in adaptive mode so
    the user is never trapped in canned templates that don't match their task!
    """
    asked = [q for q in questions if q["id"] != "q_action"]
    if len(asked) > MAX_QUESTIONS:
        asked = [q for q in asked if q["id"] != "q_safety"]
    return asked[:MAX_QUESTIONS]


def _question_options(mc: dict[str, Any], qid: str) -> dict[str, dict[str, Any]]:
    for q in mc.get("all_questions") or mc.get("questions") or []:
        if q["id"] == qid:
            return {o["id"]: o for o in q.get("options", [])}
    return {}


_KNOWN_APPS = [
    ("gimp", "GIMP"), ("inkscape", "Inkscape"), ("blender", "Blender"),
    ("libreoffice writer", "LibreOffice Writer"), ("libreoffice calc", "LibreOffice Calc"),
    ("libreoffice impress", "LibreOffice Impress"), ("microsoft word", "Microsoft Word"),
    ("excel", "Microsoft Excel"), ("powerpoint", "Microsoft PowerPoint"),
    ("visual studio code", "VS Code"), ("thunderbird", "Thunderbird"), ("slack", "Slack"),
    ("firefox", "Firefox"), ("chromium", "Chromium"), ("google chrome", "Google Chrome"),
    ("chrome", "Google Chrome"), ("nautilus", "Files"), ("dolphin", "Files"), ("thunar", "Files"),
    ("konsole", "Terminal"), ("xterm", "Terminal"), ("terminal", "Terminal"),
]


def app_name_from_window_title(title: str) -> str:
    """Best-effort app name from a window title such as 'photo.png - GIMP'."""
    raw = (title or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if re.match(r"^[\w.-]+@[\w.-]+:", raw):
        return "Terminal"
    for needle, name in _KNOWN_APPS:
        if needle in lower:
            return name
    for sep in (" — ", " - ", " | ", " – "):
        if sep in raw:
            tail = raw.rsplit(sep, 1)[1].strip()
            if 1 < len(tail) <= 40:
                return tail
    return ""


def build_naming_suggestions(
    store: Any,
    window_titles: list[str] | None,
    current_app: str,
    current_task: str,
    category_names: list[str],
) -> dict[str, Any]:
    """Pre-fill the Name-it page: detected app, prior apps, and 3 task-name options."""
    from collections import Counter

    counts = Counter(a for a in (app_name_from_window_title(w) for w in (window_titles or [])) if a)
    detected = counts.most_common(1)[0][0] if counts else ""
    generic_app = (not current_app) or current_app in {"Quick Workflows", "Local Workspace"}
    app_choice = detected or ("" if generic_app else current_app)

    prior: list[str] = []
    with store.connect() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"training_apps", "training_tasks"}.issubset(tables):
            for row in db.execute(
                """SELECT a.name FROM training_apps a
                   WHERE EXISTS (SELECT 1 FROM training_tasks t WHERE t.app_id=a.id)
                   ORDER BY a.created_at DESC LIMIT 12"""
            ):
                name = row[0]
                if name not in {"Quick Workflows", "Local Workspace"} and name not in prior:
                    prior.append(name)
    app_options = [a for a in ([app_choice] if app_choice else []) + prior if a]
    app_options = list(dict.fromkeys(app_options))[:6]

    options: list[str] = []
    if current_task and not current_task.startswith("Quick Workflow"):
        options.append(current_task)
    if detected and (not category_names or category_names[0].startswith("Organize & Rename")):
        options += [f"Edit in {detected}", f"Export from {detected}", f"My {detected} routine"]
    options += category_names
    task_options = list(dict.fromkeys(o for o in options if o))[:3]
    return {"detected_app": app_choice, "app_options": app_options, "task_options": task_options}


def rename_session_task(store: Any, session_id: str, app_name: str, task_name: str) -> dict[str, Any]:
    """Apply the Name-it page: move/rename the task under the chosen app (created if new)."""
    sid = str(session_id)
    app_name = app_name.strip()[:100]
    task_name = task_name.strip()[:160]
    if not app_name or not task_name:
        raise ValueError("App and task name are required")
    store.get_session(sid)
    task_id = sid
    append_to_task_id = None
    with store.lock:
        with store.connect() as db:
            row = db.execute("SELECT task_id FROM training_versions WHERE session_id=?", (sid,)).fetchone()
            if row is not None:
                task_id = row[0]
                app_row = db.execute("SELECT id, name FROM training_apps WHERE name=?", (app_name,)).fetchone()
                if app_row is None:
                    aid = str(uuid.uuid4())
                    db.execute("INSERT INTO training_apps VALUES(?,?,?)", (aid, app_name, _now()))
                else:
                    aid, app_name = app_row[0], app_row[1]
                existing_task = db.execute(
                    "SELECT id, name FROM training_tasks WHERE app_id=? AND name=? COLLATE NOCASE",
                    (aid, task_name),
                ).fetchone()
                if existing_task is not None and existing_task[0] != task_id:
                    append_to_task_id = existing_task[0]
                    task_name = existing_task[1]
                else:
                    db.execute("UPDATE training_tasks SET app_id=?, name=? WHERE id=?", (aid, task_name, task_id))
        if append_to_task_id is not None:
            from .training import attach_recording_as_next_version
            attach_recording_as_next_version(store, sid, append_to_task_id)
            # Resolve the existing task id from the newly attached version row.
            with store.connect() as db:
                task_id = db.execute("SELECT task_id FROM training_versions WHERE session_id=?", (sid,)).fetchone()[0]
        answers = dict(store.get_session(sid).get("answers") or {})
        answers["teaching_task_name"] = task_name
        store.update_session(sid, {"title": f"Training · {task_name}", "answers": answers})
    existing = get_hybrid_recipe(store, task_id)
    if existing is not None:
        save_hybrid_recipe(store, task_id, existing.model_copy(update={"title": task_name, "app_name": app_name}))
    mc = build_multiple_choice_questions(task_name=task_name, app_name=app_name)
    return {
        "session_id": sid,
        "task_id": task_id,
        "app_name": app_name,
        "task_name": task_name,
        "questions": mc["adaptive_questions"],
        "all_questions": mc["all_questions"],
    }


def _trigger_phrases(task_name: str, app_name: str, recipe: HybridRecipe) -> dict[str, Any]:
    clean_title = re.sub(r"\s*#\d+\b", "", task_name).strip() or task_name.strip()
    clean_app = app_name.strip() or "the app"
    ask = next((p for p in recipe.parameters if p.required), None)
    first = ask or (recipe.parameters[0] if recipe.parameters else None)

    if ask is not None:
        example = str(ask.default or "").strip()
        if not example or example in {"…", "...", "None"}:
            pname = ask.name.lower()
            if any(k in pname for k in ("host", "domain", "url")):
                example = "yahoo.com"
            elif any(k in pname for k in ("file", "path")):
                example = "document.txt"
            else:
                example = "sample"
        say = f"Run {clean_title} for {example} in {clean_app}"
        phrases = [
            say,
            f"{clean_title} for {example} in {clean_app}",
            f"{clean_title} in {clean_app}",
        ]
    else:
        say = f"Run {clean_title} in {clean_app}"
        phrases = [
            say,
            f"Perform {clean_title} in {clean_app}",
            f"{clean_title}",
        ]
    try_param = None
    if first is not None:
        default_val = first.default
        if not default_val or str(default_val).strip() in {"…", "...", "None"}:
            pname = first.name.lower()
            default_val = "yahoo.com" if any(k in pname for k in ("host", "domain", "url")) else ("document.txt" if "file" in pname else "sample")
        try_param = {
            "name": first.name,
            "label": first.description or f"Target or input for {clean_title}",
            "default": default_val,
        }
    return {"say_this": say, "trigger_phrases": phrases, "try_param": try_param}


def _recipe_from_choices(
    task_id: str,
    title: str,
    app_name: str,
    choices: dict[str, str],
    goal_text: str = "",
    done_text: str = "",
) -> HybridRecipe:
    action_choice = choices.get("q_action", "file_organize")
    input_choice = choices.get("q_input", "ask_each_time")

    if action_choice == "terminal_cmd":
        steps = [
            HybridStep(
                id="step-cmd-capture",
                action="browser_or_fixture_action",
                goal=goal_text or f"Execute {title} command in sandbox and capture output receipt",
                check=done_text or "Command output receipt written and verified",
                target="terminal",
                input="target_host",
                params={"receipt_file": "fixture_draft_receipt.json", "caption": f"Verified output for {title}", "filename": "nslookup-google.txt"},
            ),
            HybridStep(
                id="step-cmd-summary",
                action="csv_summary_report",
                goal="Write human-readable Markdown execution summary",
                check="summary.md is written and non-empty",
                params={"csv_file": "sales.csv", "output_file": "summary.md", "numeric_column": "amount"},
            ),
        ]
        params = [
            HybridParameter(
                name="target_host",
                type="string",
                description="Target domain or argument to query",
                default="google.com",
                required=(input_choice == "ask_each_time"),
            ),
        ]
        assertions = [
            HybridAssertion(type="non_empty_output", target="fixture_draft_receipt.json", phase="post"),
            HybridAssertion(type="non_empty_output", target="summary.md", phase="post"),
        ]
    elif action_choice == "csv_summary":
        steps = [
            HybridStep(
                id="step-csv",
                action="csv_summary_report",
                goal=goal_text or f"Parse CSV and generate summary report for {title}",
                check=done_text or "summary.md is written and non-empty",
                params={"csv_file": "sales.csv", "output_file": "summary.md", "numeric_column": "amount"},
            ),
        ]
        params = [
            HybridParameter(name="csv_file", type="string", description="Source CSV file", default="sales.csv", required=False),
        ]
        assertions = [
            HybridAssertion(type="non_empty_output", target="summary.md", phase="post"),
        ]
    elif action_choice == "browser_draft":
        steps = [
            HybridStep(
                id="step-draft",
                action="browser_or_fixture_action",
                goal=goal_text or f"Fill fields and save verified draft for {title}",
                check=done_text or "Saved draft receipt matches input",
                target="Save draft",
                input="caption",
                params={"receipt_file": "fixture_draft_receipt.json"},
            ),
        ]
        params = [
            HybridParameter(name="filename", type="string", description="Draft file name", default="sample-draft.txt", required=False),
            HybridParameter(name="caption", type="string", description="Draft caption", default="Prepared by HoldMyBeer", required=False),
        ]
        assertions = [
            HybridAssertion(type="non_empty_output", target="fixture_draft_receipt.json", phase="post"),
        ]
    elif action_choice in {"recorded_flow", "custom_recorded"} or (action_choice not in {"terminal_cmd", "csv_summary", "browser_draft", "file_organize"}):
        steps = [
            HybridStep(
                id="step-recorded-action",
                action="browser_or_fixture_action",
                goal=goal_text or f"Execute {title} in {app_name}",
                check=done_text or f"{title} finished cleanly in {app_name}",
                target=app_name,
                input="input_text" if input_choice == "ask_each_time" else "",
                params={"app_name": app_name, "task_name": title, "receipt_file": "workflow_receipt.json"},
            ),
        ]
        params = []
        if input_choice == "ask_each_time":
            params.append(
                HybridParameter(
                    name="input_text",
                    type="string",
                    description=f"Input or parameter for {title}",
                    default="",
                    required=True,
                )
            )
        assertions = [
            HybridAssertion(type="non_empty_output", target="workflow_receipt.json", phase="post"),
        ]
    else:
        steps = [
            HybridStep(
                id="step-organize",
                action="file_organize_by_ext",
                goal=goal_text or f"Organize files into category folders for {title}",
                check="Files sorted into category folders",
                params={},
            ),
            HybridStep(
                id="step-rename",
                action="file_rename_batch",
                goal=f"Batch rename text notes with clean prefix",
                check=done_text or "Matching files renamed cleanly",
                params={"pattern": r"^.+\.txt$", "prefix": "{prefix}", "subdir": "documents", "require_matches": False},
            ),
            HybridStep(
                id="step-summary",
                action="csv_summary_report",
                goal="Write verification summary report",
                check="summary.md is written and non-empty",
                params={"csv_file": "data/sales.csv", "output_file": "summary.md", "numeric_column": "amount"},
            ),
        ]
        params = [
            HybridParameter(name="prefix", type="string", description="Prefix for renamed files", default="HMB_", required=False),
        ]
        assertions = [
            HybridAssertion(type="non_empty_output", target="summary.md", phase="post"),
        ]

    return HybridRecipe(
        task_id=str(task_id),
        title=title,
        app_name=app_name,
        parameters=params,
        steps=steps,
        assertions=assertions,
        on_uncertainty="pause_for_agent",
    )


def generate_auto_review(
    store: Any,
    session_id: str,
    window_title: str | None = None,
    duration_seconds: float | None = None,
    window_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Prepare a saved recording for naming and choice review without claiming inspection or approval."""
    sid = str(session_id)
    sdata = store.get_session(sid)
    answers = dict(sdata.get("answers") or {})
    task_id = sid
    app_name = "Quick Workflows"
    task_name = answers.get("teaching_task_name") or sdata.get("title") or "Quick Workflow"

    with store.connect() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"training_versions", "training_tasks", "training_apps"}.issubset(tables):
            row = db.execute(
                """SELECT t.id AS task_id, t.name AS task_name, a.name AS app_name
                   FROM training_versions v
                   JOIN training_tasks t ON t.id=v.task_id
                   JOIN training_apps a ON a.id=t.app_id
                   WHERE v.session_id=?""",
                (sid,),
            ).fetchone()
            if row is not None:
                task_id = row["task_id"]
                task_name = answers.get("teaching_task_name") or row["task_name"]
                app_name = row["app_name"]

    if window_title and window_title.strip() and task_name.startswith("Quick Workflow"):
        inferred = infer_quick_record_metadata(window_title=window_title)
        task_name = inferred["task_name"]
        app_name = inferred["app_name"]

    # Remux WebM with ffmpeg -c copy so MediaRecorder files get a proper Duration header & Cues seek table (eliminates pause/play stutter)
    webm_file = store.artifacts / f"{sid}.webm"
    if webm_file.is_file() and webm_file.stat().st_size > 100:
        import subprocess
        remux_tmp = store.artifacts / f".{sid}.remux.webm"
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(webm_file), "-c", "copy", str(remux_tmp)],
                check=True,
                timeout=15,
            )
            if remux_tmp.is_file() and remux_tmp.stat().st_size > 100:
                os.replace(remux_tmp, webm_file)
        except Exception:
            pass
        finally:
            remux_tmp.unlink(missing_ok=True)

    saved_choices = answers.get("teaching_choice_answers")
    if not isinstance(saved_choices, dict):
        saved_choices = {}

    mc = build_multiple_choice_questions(
        task_name=task_name,
        app_name=app_name,
        goal=answers.get("teaching_goal", ""),
        done=answers.get("teaching_done", ""),
        window_title=window_title or "",
        saved_choices=saved_choices,
    )

    chosen_map = {q["id"]: q["selected"] for q in mc["all_questions"]}
    q1_opts = _question_options(mc, "q_action")
    q3_opts = _question_options(mc, "q_done")
    goal_desc = answers.get("teaching_goal") or q1_opts.get(chosen_map["q_action"], {}).get("goal_text", f"Perform {task_name}")
    done_desc = answers.get("teaching_done") or q3_opts.get(chosen_map["q_done"], {}).get("done_text", "Output verified cleanly")

    # Labels and recording duration do not establish what the recording shows.
    # Save a template for review without inventing observations or a proposal.
    proposal = None

    recipe = _recipe_from_choices(
        task_id=task_id,
        title=task_name,
        app_name=app_name,
        choices=chosen_map,
        goal_text=goal_desc,
        done_text=done_desc,
    )
    save_hybrid_recipe(store, task_id, recipe)
    naming = build_naming_suggestions(
        store,
        list(window_titles or []) + ([window_title] if window_title else []),
        app_name,
        task_name,
        mc["suggested_names"],
    )

    return {
        "status": "ready",
        "session_id": sid,
        "task_id": task_id,
        "app_name": app_name,
        "task_name": task_name,
        "suggested_names": naming["task_options"] or mc["suggested_names"],
        "detected_app": naming["detected_app"],
        "app_options": naming["app_options"],
        "task_options": naming["task_options"] or mc["suggested_names"],
        "observations": [],
        "multiple_choice_questions": mc["questions"],
        "adaptive_questions": mc.get("adaptive_questions") or mc["questions"],
        "recipe_card": recipe.to_recipe_card(),
        "proposal": proposal,
    }


def apply_multiple_choice_answers(
    store: Any,
    session_id: str,
    selected_name: str | None = None,
    choices: dict[str, str] | None = None,
    run_sandbox: bool = True,
) -> dict[str, Any]:
    """Save multiple-choice preferences as a reviewable recipe template."""
    sid = str(session_id)
    sdata = store.get_session(sid)
    answers = dict(sdata.get("answers") or {})
    task_id = sid
    app_name = "Quick Workflows"
    task_name = (selected_name or "").strip() or answers.get("teaching_task_name") or "Quick Workflow"

    with store.connect() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"training_versions", "training_tasks", "training_apps"}.issubset(tables):
            row = db.execute(
                """SELECT t.id AS task_id, t.name AS task_name, a.name AS app_name
                   FROM training_versions v
                   JOIN training_tasks t ON t.id=v.task_id
                   JOIN training_apps a ON a.id=t.app_id
                   WHERE v.session_id=?""",
                (sid,),
            ).fetchone()
            if row is not None:
                task_id = row["task_id"]
                app_name = row["app_name"]
                if not selected_name:
                    task_name = answers.get("teaching_task_name") or row["task_name"]
                else:
                    db.execute("UPDATE training_tasks SET name=? WHERE id=?", (task_name, task_id))

    mc = build_multiple_choice_questions(
        task_name=task_name,
        app_name=app_name,
        goal=answers.get("teaching_goal", ""),
        done=answers.get("teaching_done", ""),
        saved_choices=choices or {},
    )
    applied_choices = {q["id"]: q["selected"] for q in mc["all_questions"]}
    if choices:
        for k, v in choices.items():
            if v:
                applied_choices[str(k)] = str(v)

    q1_opts = _question_options(mc, "q_action")
    q3_opts = _question_options(mc, "q_done")
    goal_desc = q1_opts.get(applied_choices.get("q_action", ""), {}).get("goal_text") or answers.get("teaching_goal") or f"Perform {task_name}"
    done_desc = q3_opts.get(applied_choices.get("q_done", ""), {}).get("done_text") or answers.get("teaching_done") or "Output verified cleanly"

    answers["teaching_task_name"] = task_name
    answers["teaching_goal"] = goal_desc
    answers["teaching_done"] = done_desc
    answers["teaching_choice_answers"] = applied_choices
    store.update_session(sid, {"title": f"Training · {task_name}", "answers": answers})

    # Choices are saved as a template for review; they are not observations,
    # a verified procedure, or consent to an approval receipt.
    proposal = None

    recipe = _recipe_from_choices(
        task_id=task_id,
        title=task_name,
        app_name=app_name,
        choices=applied_choices,
        goal_text=goal_desc,
        done_text=done_desc,
    )
    trigger = _trigger_phrases(task_name, app_name, recipe)
    recipe = recipe.model_copy(update={"trigger_phrases": trigger["trigger_phrases"]})
    save_hybrid_recipe(store, task_id, recipe)

    sandbox_result = None
    if run_sandbox:
        sandbox_result = run_hybrid_recipe(recipe, dry_run=True)

    return {
        "status": "saved_for_review",
        "execution_ready": False,
        "session_id": sid,
        "task_id": task_id,
        "app_name": app_name,
        "task_name": task_name,
        "choices": applied_choices,
        "goal": goal_desc,
        "done_when": done_desc,
        "recipe_card": recipe.to_recipe_card(),
        "sandbox_result": sandbox_result,
        "proposal": proposal,
        "say_this": trigger["say_this"],
        "trigger_phrases": trigger["trigger_phrases"],
        "try_param": trigger["try_param"],
        "tool_name": recipe.to_openai_tool()["function"]["name"],
    }


# --------------------------------------------------------------------------- #
# Native 1-Click Desktop Screen Recorder (Zero Browser Share Dialog)
# --------------------------------------------------------------------------- #
_ACTIVE_NATIVE_RECORDERS: dict[str, dict[str, Any]] = {}


def _detect_x11_display() -> str | None:
    import subprocess
    candidates = []
    if os.environ.get("DISPLAY"):
        candidates.append(os.environ["DISPLAY"])
    for d in (":10.0", ":10", ":0.0", ":0", ":1.0", ":1"):
        if d not in candidates:
            candidates.append(d)
    for disp in candidates:
        try:
            res = subprocess.run(
                ["xdpyinfo", "-display", disp],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
            )
            if res.returncode == 0:
                return disp
        except Exception:
            continue
    return None


def _detect_active_window_title(display: str) -> str:
    import subprocess
    try:
        env = {**os.environ, "DISPLAY": display}
        out = subprocess.check_output(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            env=env,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        )
        win_id = out.strip().split()[-1].rstrip(",")
        if win_id and win_id != "0x0":
            wout = subprocess.check_output(
                ["xprop", "-id", win_id, "_NET_WM_NAME", "WM_NAME", "WM_CLASS"],
                env=env,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.0,
            )
            for line in wout.splitlines():
                if "=" in line and '"' in line:
                    val = line.split('"', 1)[1].rsplit('"', 1)[0].strip()
                    if val and "holdmybeer" not in val.lower() and "127.0.0.1:8096" not in val.lower():
                        return val
    except Exception:
        pass
    return ""


def _sample_activity_loop(state: dict[str, Any]) -> None:
    import time
    display = state["display"]
    seen_windows: list[str] = state["seen_windows"]
    while state.get("running"):
        w = _detect_active_window_title(display)
        if w:
            state.setdefault("samples", []).append(w)
        if w and w not in seen_windows:
            seen_windows.append(w)
        time.sleep(0.35)


def start_native_recording(store: Any) -> dict[str, Any]:
    import subprocess
    import threading
    import time

    display = _detect_x11_display()
    if not display or not shutil.which("ffmpeg"):
        return {"supported": False, "reason": "No local X11 display or ffmpeg available"}

    win_title = _detect_active_window_title(display)
    now = _now()
    with store.lock:
        with store.connect() as db:
            row_count = db.execute("SELECT COUNT(*) FROM training_tasks").fetchone()[0]
            inferred = infer_quick_record_metadata(window_title=win_title or None, existing_count=row_count)
            app_name = inferred["app_name"]
            base_task_name = inferred["task_name"]
            app_row = db.execute("SELECT id, name FROM training_apps WHERE name=?", (app_name,)).fetchone()
            if app_row is not None:
                aid = app_row["id"]
            else:
                aid = str(uuid.uuid4())
                db.execute("INSERT INTO training_apps VALUES(?,?,?)", (aid, app_name, now))

            final_task_name = base_task_name
            suffix_num = 2
            while db.execute("SELECT 1 FROM training_tasks WHERE app_id=? AND name=?", (aid, final_task_name)).fetchone():
                final_task_name = f"{base_task_name} #{suffix_num}"
                suffix_num += 1

            tid = str(uuid.uuid4())
            sid = str(uuid.uuid4())
            session_data = {
                "id": sid,
                "title": f"Training · {final_task_name}",
                "created_at": now,
                "notes": "",
                "answers": {
                    "teaching_task_name": final_task_name,
                    "teaching_goal": "",
                    "teaching_done": "",
                    "teaching_recording_confirmed": "no",
                },
                "procedure": {"revision": 1, "steps": []},
                "media_url": None,
                "runs": [],
            }
            db.execute("INSERT INTO sessions(id,data) VALUES(?,?)", (sid, json.dumps(session_data)))
            db.execute("INSERT INTO procedure_revisions VALUES(?,?,?,?,?)", (sid, 1, json.dumps(session_data["procedure"]), now, "saved"))
            db.execute("INSERT INTO training_tasks VALUES(?,?,?,?,?,?)", (tid, aid, final_task_name, 1, None, now))
            db.execute("INSERT INTO training_versions VALUES(?,?,?,?,?)", (tid, 1, sid, now, None))

    raw_mp4 = store.artifacts / f".{sid}.capture.mp4"
    out_mp4 = store.artifacts / f"{sid}.mp4"
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-f", "x11grab",
        "-framerate", "25",
        "-i", display,
        "-vf", "scale=1280:-2",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-g", "25",
        "-y",
        str(raw_mp4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    state: dict[str, Any] = {
        "proc": proc,
        "display": display,
        "start_time": time.time(),
        "window_title": win_title,
        "seen_windows": [win_title] if win_title else [],
        "raw_mp4": raw_mp4,
        "out_mp4": out_mp4,
        "task_id": tid,
        "running": True,
    }
    sampler = threading.Thread(target=_sample_activity_loop, args=(state,), daemon=True)
    sampler.start()
    _ACTIVE_NATIVE_RECORDERS[sid] = state
    return {
        "supported": True,
        "status": "recording",
        "mode": "native",
        "session_id": sid,
        "task_id": tid,
        "display": display,
        "window_title": win_title,
    }


def stop_native_recording(store: Any, session_id: str) -> dict[str, Any]:
    import signal
    import subprocess
    import time

    sid = str(session_id)
    info = _ACTIVE_NATIVE_RECORDERS.pop(sid, None)
    elapsed = 2.5
    win_title = ""
    raw_mp4 = store.artifacts / f".{sid}.capture.mp4"
    out_mp4 = store.artifacts / f"{sid}.mp4"

    if info is not None:
        info["running"] = False
        proc = info["proc"]
        elapsed = max(1.0, round(time.time() - info["start_time"], 1))
        seen = [w for w in info.get("seen_windows", []) if w]
        win_title = seen[-1] if seen else (_detect_active_window_title(info["display"]) or info.get("window_title") or "")
        try:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    if raw_mp4.is_file() and raw_mp4.stat().st_size > 100:
        try:
            subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-y", "-i", str(raw_mp4),
                    "-c", "copy", "-movflags", "+faststart", str(out_mp4),
                ],
                check=True,
                timeout=10,
            )
        except Exception:
            os.replace(raw_mp4, out_mp4)
        finally:
            raw_mp4.unlink(missing_ok=True)

    if not out_mp4.is_file() or out_mp4.stat().st_size < 100:
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=#1e241b:s=960x540:r=25:d=2",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-y", str(out_mp4),
            ],
            check=False,
            timeout=10,
        )

    with store.lock:
        store.update_session(
            sid,
            {
                "media_url": f"/api/sessions/{sid}/media",
                "media_revision": str(uuid.uuid4()),
                "answers": {
                    **(store.get_session(sid).get("answers") or {}),
                    "teaching_recording_confirmed": "yes",
                },
            },
        )

    samples = list((info or {}).get("samples") or (info or {}).get("seen_windows") or [])
    review = generate_auto_review(
        store, sid, window_title=win_title or None, duration_seconds=elapsed, window_titles=samples
    )
    return {
        **review,
        "media_url": f"/api/sessions/{sid}/media",
        "duration_seconds": elapsed,
    }
