"""Slice 3 TDD tests: Universal Agent Interoperability (Dynamic MCP, SKILL.md Exporter, OpenAI Tools, Agent Discovery)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import likethis.cli as cli
from likethis.app import create_app
from likethis.hybrid import (
    HybridAssertion,
    HybridParameter,
    HybridRecipe,
    HybridStep,
    save_hybrid_recipe,
)
from likethis.mcp_server import hmb_list_universal_workflows


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    return TestClient(app)


def test_dynamic_mcp_exposes_universal_workflows_and_executes_dry_run(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    create_app(data_dir)
    monkeypatch.setenv("HMB_DATA_DIR", str(data_dir))

    target_dir = tmp_path / "target_docs"
    target_dir.mkdir()
    (target_dir / "doc1.txt").write_text("Alpha", encoding="utf-8")
    (target_dir / "doc2.txt").write_text("Beta", encoding="utf-8")

    recipe = HybridRecipe(
        task_id="task-mcp-1",
        title="Tag Text Docs",
        app_name="Files",
        parameters=[
            HybridParameter(name="prefix", type="string", description="Tag prefix", default="TAGGED_", required=True),
        ],
        steps=[
            HybridStep(
                id="s1",
                action="file_rename_batch",
                goal="Tag .txt files",
                check="Files renamed with prefix",
                params={"pattern": r"^.+\.txt$", "prefix": "{prefix}"},
            )
        ],
        assertions=[
            HybridAssertion(type="count_matches", target="{prefix}*.txt", expected=2, phase="post"),
        ],
    )
    save_hybrid_recipe(data_dir, "task-mcp-1", recipe)

    # Direct call to hmb_list_universal_workflows
    listed = hmb_list_universal_workflows()
    assert len(listed["workflows"]) == 1
    assert listed["workflows"][0]["tool_name"] == "hmb_workflow_tag_text_docs"

    # Stdio MCP check: list_tools() dynamically includes hmb_list_universal_workflows and hmb_workflow_tag_text_docs
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "likethis.mcp_server"],
            env={**os.environ, "HMB_DATA_DIR": str(data_dir)},
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert "hmb_list_universal_workflows" in names
                assert "hmb_workflow_tag_text_docs" in names

                wf_tool = next(t for t in tools.tools if t.name == "hmb_workflow_tag_text_docs")
                schema = wf_tool.inputSchema
                assert "prefix" in schema["properties"]
                assert schema["properties"]["dry_run"]["default"] is True

                # Call the dynamic tool via MCP (defaults to dry_run=True)
                call_res = await session.call_tool(
                    "hmb_workflow_tag_text_docs",
                    {"prefix": "MCP_", "target_dir": str(target_dir)},
                )
                assert not call_res.isError
                payload = json.loads(call_res.content[0].text)
                assert payload["status"] == "verified"
                assert payload["dry_run"] is True
                assert payload["real_files_mutated"] is False
                assert "MCP_doc1.txt" in payload["before_after_diff"]["files_after"]
                # Real file untouched
                assert (target_dir / "doc1.txt").exists()
                assert not (target_dir / "MCP_doc1.txt").exists()

    anyio.run(exercise)


def test_export_skill_bundle_api_and_standalone_runner(client, tmp_path):
    qr = client.post("/api/quick-record", json={"hint": "Summarize sales CSV"}).json()
    task_id = qr["task_id"]

    out_dir = tmp_path / "exported_skills"
    res = client.post(
        f"/api/tasks/{task_id}/export-skill",
        json={"output_dir": str(out_dir)},
    )
    assert res.status_code == 200, res.text
    bundle = res.json()
    skill_dir = Path(bundle["skill_dir"])
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "recipe.json").is_file()
    assert (skill_dir / "run_recipe.py").is_file()

    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert skill_md.startswith("---\nname: ")
    for agent_name in ("Hermes", "Octo", "Antigravity", "Claude Code", "Codex", "Cursor"):
        assert agent_name in skill_md

    # Run the standalone exported run_recipe.py in dry-run mode
    sample_target = tmp_path / "sample_run"
    sample_target.mkdir()
    (sample_target / "item.txt").write_text("item", encoding="utf-8")
    (sample_target / "sales.csv").write_text("item,amount\nBook,15.0\nPen,5.0\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(skill_dir / "run_recipe.py"), "--target-dir", str(sample_target), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    run_out = json.loads(proc.stdout)
    assert run_out["status"] == "verified"
    assert run_out["dry_run"] is True
    assert not (sample_target / "summary.md").exists()


def test_openai_tools_schema_and_universal_agent_discovery(client, tmp_path, capsys):
    qr = client.post("/api/quick-record", json={"task_name": "Organize Downloads Folder"}).json()
    assert qr["task_id"]

    # 1. GET /api/tools/openai
    tools_resp = client.get("/api/tools/openai")
    assert tools_resp.status_code == 200, tools_resp.text
    tools_data = tools_resp.json()
    assert len(tools_data["tools"]) >= 1
    first_tool = tools_data["tools"][0]
    assert first_tool["type"] == "function"
    assert first_tool["function"]["name"] == "hmb_workflow_organize_downloads_folder"
    assert "dry_run" in first_tool["function"]["parameters"]["properties"]

    # 2. GET /api/universal-agents
    agents_resp = client.get("/api/universal-agents")
    assert agents_resp.status_code == 200, agents_resp.text
    agents_data = agents_resp.json()
    agent_ids = {a["id"] for a in agents_data["agents"]}
    assert {"claude", "cursor", "codex", "hermes", "ollama"} <= agent_ids
    assert all("connect_one_liner" in a for a in agents_data["agents"])

    # 3. CLI `holdmybeer agents` and `holdmybeer universal-status`
    code_agents = cli.main(["agents"])
    assert code_agents == cli.EXIT_OK
    out_agents = capsys.readouterr().out
    assert "Claude Code" in out_agents
    assert "Hermes" in out_agents
    assert "Ollama" in out_agents

    code_status = cli.main(["universal-status"])
    assert code_status == cli.EXIT_OK
    out_status = capsys.readouterr().out
    assert "/api/tools/openai" in out_status
