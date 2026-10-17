# Spec: HoldMyBeer Mass-Adoption Hybrid Engine, 1-Button UX & Universal Agent Adapters

**Status:** Approved for Isolated Mass-Adoption Sprint (`2026-10-17`)  
**Baseline:** `checkpoint/weekend-20261016-ea02929` (`holdmybeer 0.3.0a3`, 120/120 tests green)  
**Target Release:** `holdmybeer 0.4.0a1` (Isolated staging in `mass-adoption-20261017`)

---

## Phase 0: Capability Map

| Module id | Responsibility | Depends on |
|---|---|---|
| `hybrid-engine` | "AI Thinks, Script Executes" runtime, deterministic recipe runner, and mandatory sandbox dry-run diff generator | — |
| `one-button-ux` | Zero-form 1-button recording/drop entry, auto-titling, and unified Hybrid + Sandbox Diff review card | `hybrid-engine` |
| `universal-adapters` | Dynamic MCP tool registration, CLI `hmb run` / `hmb export`, portable `SKILL.md` exporter, and OpenAI strict tool schema generator | `hybrid-engine` |
| `starter-recipes` | Top 10 deterministic + hybrid starter recipes with local fixture verification and rollback manifests | `hybrid-engine`, `universal-adapters` |

Build order: `hybrid-engine` → `one-button-ux`, `universal-adapters` → `starter-recipes`

---

## 1. Objective

HoldMyBeer `0.3.0a3` proved an honest local scaffold for **App → Task → Versioned Recording → Connected-Agent Review**, while explicitly documenting two hard adoption bottlenecks identified during architecture review:
1. **Pure GUI pixel replay is brittle and unverified** on local models that receive text markers instead of raw video streams, whereas users actually want **reliable, repeatable execution** on messy real-world inputs.
2. **Pre-recording setup friction** (picking/creating an App, naming a Task before showing the workflow, and locking approved workflows inside a single custom web UI) blocks 30-second first success and prevents developers from invoking learned workflows from their existing daily agents (Claude Code, Cursor, Codex, Antigravity, Hermes, Octo, OpenAI/llama.cpp).

### The Mass-Adoption Solution

1. **Hybrid "AI Thinks, Script Executes" Architecture (`hybrid-engine`)**:
   - **AI Thinks (Cognitive Extraction Layer):** An LLM or connected agent inspects messy inputs, recordings, or unstructured files once to extract typed parameters (`inputs_schema`) and synthesize a deterministic execution plan.
   - **Script Executes (Deterministic Execution Layer):** Approved tasks compile into deterministic, auditable Python/shell/Playwright recipe steps that execute inside an isolated local sandbox without LLM hallucination in the loop.
   - **Mandatory Sandbox Dry-Run Diff:** Every recipe execution defaults to `--dry-run` in a temporary shadow directory, producing a structured `SandboxDiff` (files added/renamed/modified, unified line diffs, row counts, and rollback manifest) before a single byte of user data is touched.

2. **1-Button Zero-Form UX (`one-button-ux`)**:
   - Landing page opens with **one primary action button** (`Hold My Beer — Show or Drop a Task`) requiring zero pre-record form fields.
   - If the user starts recording or drops a file/example immediately, HoldMyBeer auto-creates a draft session under a default `Quick Tasks` workspace, auto-generates a recognizable title from the artifact/action, and opens the **Hybrid Review & Sandbox Diff** view.
   - Full `0.3.0a3` App → Task → Versioned Training hierarchy remains 100% intact and accessible for organizing multi-task apps.

3. **Universal Agent Adapter Architecture (`universal-adapters`)**:
   - **MCP Dynamic Tools:** Approved hybrid recipes are exposed via `holdmybeer.mcp_server` (`hmb_list_recipes`, `hmb_dry_run_recipe`, `hmb_run_recipe`, and dynamic tool schemas) with explicit `ToolAnnotations`.
   - **CLI `hmb run` & `hmb export`:** Run any approved task or starter recipe from the terminal (`holdmybeer run <recipe_or_task_id> --dry-run|--apply --input key=val`) or export it (`holdmybeer export <id> --format skill|openai|mcp`).
   - **Portable `SKILL.md` Exporter:** Generates a standard `SKILL.md` markdown bundle with YAML frontmatter (`name`, `description`, `inputs`, `safety_gate: sandbox_dry_run`) and embedded deterministic runner commands so any `SKILL.md`-compatible agent can invoke it.
   - **OpenAI Tool Schema Exporter:** Emits strict JSON Schema function definitions (`strict: true`) ready for OpenAI, llama.cpp (`Huihui-Qwen3.6-35B-A3B`), vLLM, and LiteLLM tool calling.

---

## 2. Assumptions Surface

1. **Frozen Checkpoint Integrity:** `weekend-20261016` (`ea02929`, `0.3.0a3`) is never modified; all new work lives in `mass-adoption-20261017`.
2. **Backward Compatibility:** All 120 existing tests in `tests/` (covering App/Task hierarchy, version lifecycle, optimistic locking, legacy migration, and honesty gates) must continue to pass without regression.
3. **Honest Capability Reporting:** Where native pixel vision is still unavailable on a given local endpoint, the Hybrid Engine uses structured artifact/file/DOM/transcript extraction and labels vision state truthfully. Dry-run diffs are never fabricated.
4. **Local-Only Safety:** Default bind remains `127.0.0.1:18940`. No outbound network calls, telemetry, or cloud dependencies are added.

---

## 3. Tech Stack

- **Runtime:** Python `>=3.10` (tested on Python `3.12` / `3.14` in virtual environment)
- **Web & API:** FastAPI `>=0.115`, Pydantic v2 (`StrictModel`), Uvicorn
- **Storage:** Local SQLite (`holdmybeer.sqlite3` in `HMB_DATA_DIR`) with WAL-safe atomic transactions and content-addressed sandbox staging
- **Browser & Fixture Runner:** Playwright (`playwright.async_api` / sync runner)
- **Agent Protocols:** MCP (`mcp.server.fastmcp.FastMCP`), OpenAI Function Calling JSON Schema (Draft 2020-12 / strict mode), Portable Agent `SKILL.md` v1 specification
- **Frontend:** Zero-build Vanilla ES6 (`web/index.html`, `web/simple.js`, `web/directed.js`, `web/training.js`, `web/style.css`)

---

## 4. Commands

```bash
# Run full test suite in virtual environment
python3 -m pytest -q

# Run doctor check
holdmybeer doctor --json

# Export an approved task or recipe as a portable SKILL.md bundle
holdmybeer export-skill --task-id <task-id> --output-dir ./exported-skills

# Detect local agents and print connection commands
holdmybeer detect-agents

# Build wheel into dist/
python3 -m pip wheel . --no-deps --wheel-dir ./dist
```

---

## 5. Project Structure

```text
source/
├── holdmybeer/
│   ├── __init__.py          # Package version & exports
│   ├── app.py               # FastAPI routes (sessions, training, hybrid recipes, dry-run diff, adapters)
│   ├── cli.py               # CLI entrypoints: serve, mcp, doctor, export-skill, detect-agents
│   ├── hybrid.py            # Hybrid "AI Thinks, Script Executes" engine, SandboxDiff & SKILL.md exporter
│   ├── mcp_server.py        # MCP stdio server with dynamic recipe/task tools
│   ├── models.py            # Strict Pydantic models for procedures, hybrid recipes, diffs, and exports
│   ├── proposals.py         # Connected-agent review & proposal validation
│   ├── revisions.py         # Immutable revision history
│   ├── runner.py            # Deterministic fixture & sandbox execution runner
│   └── training.py          # App -> Task -> Versioned Training store + 1-button quick-task support
├── web/
│   ├── index.html           # 1-Button Zero-Form entry + Hybrid Sandbox Diff review + App/Task drawer
│   ├── simple.js            # 1-button quick record/drop & dry-run diff preview controller
│   ├── directed.js          # Directed novice flow, 3-Line Recipe Card & Sandbox Dry-Run panel
│   ├── training.js          # App/Task versioned library & universal adapter export UI
│   └── style.css            # Accessible, responsive dark/light styling (320px+ verified)
├── tests/
│   ├── test_backend.py      # Core API & session tests
│   ├── test_cli.py          # CLI launch, doctor, export-skill, detect-agents tests
│   ├── test_directed_ui.py  # Browser E2E flow tests
│   ├── test_hybrid_engine.py # Hybrid engine, sandbox dry-run & rollback tests
│   ├── test_mcp.py          # MCP server & dynamic tool tests
│   ├── test_quick_record_and_recipe_card.py # 1-Button Quick Record & 3-Line Recipe Card tests
│   ├── test_runner.py       # Step-specific browser timeout tests
│   ├── test_training.py     # App/Task versioning tests
│   └── test_universal_interop.py # Universal MCP, SKILL.md export & OpenAI schema tests
└── docs/
    └── specs/
        └── SPEC-hybrid-universal.md
```

---

## 6. Architecture & Code Contracts

### 6.1 Hybrid Recipe & Sandbox Diff Contract

```python
class HybridParameter(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=64)
    type: Literal["string", "integer", "boolean", "path", "enum"] = "string"
    description: StrictStr = Field(min_length=1, max_length=240)
    required: StrictBool = True
    default: str | int | bool | None = None


class SandboxDiffItem(StrictModel):
    path: StrictStr
    operation: Literal["create", "modify", "rename", "delete", "noop"]
    before_sha256: StrictStr | None = None
    after_sha256: StrictStr | None = None
    summary: StrictStr
    preview_diff: StrictStr = ""


class SandboxRunReceipt(StrictModel):
    recipe_id: StrictStr
    mode: Literal["dry_run", "apply"]
    status: Literal["passed", "failed", "blocked"]
    ai_extracted_params: dict[str, str | int | bool]
    script_command: StrictStr
    diffs: list[SandboxDiffItem]
    rollback_ready: StrictBool = True
```

### 6.2 Universal Adapter Export Formats

1. **Portable `SKILL.md` Export (`export-skill`):**
   ```markdown
   ---
   name: batch-rename-downloads
   description: Deterministically organize and rename messy files by date and category using HoldMyBeer Hybrid Runner.
   ---
   # Batch Rename & Organize Files
   ## Usage
   1. Run sandbox dry-run first and show diff to user:
      `python3 run_recipe.py --target-dir ./my-folder --dry-run`
   2. Only after explicit user confirmation of the diff, apply:
      `python3 run_recipe.py --target-dir ./my-folder --live --approve`
   ```

2. **OpenAI Function Tool Schema (`/api/tools/openai`):**
   ```json
   {
     "type": "function",
     "function": {
       "name": "hmb_workflow_batch_rename_downloads",
       "description": "Run HoldMyBeer deterministic hybrid recipe: Batch Rename & Organize Files. Always run with dry_run=true first.",
       "strict": true,
       "parameters": {
         "type": "object",
         "properties": {
           "dry_run": { "type": "boolean", "description": "Must be true until user approves the sandbox diff." }
         },
         "required": ["dry_run"],
         "additionalProperties": false
       }
     }
   }
   ```

---

## 7. Testing Strategy

- **Unit & Contract Tests (`pytest`):**
  - Validate `HybridRecipe`, `HybridParameter`, `HybridStep`, and `HybridAssertion` strict models.
  - Verify that `dry_run=True` never mutates the target workspace and produces deterministic SHA-256 before/after diffs.
  - Verify that live execution (`dry_run=False`) requires explicit `user_approved_understanding=True` and rolls back on failed post-assertions.
  - Verify universal exports (`SKILL.md`, OpenAI tool JSON, dynamic MCP tool list) for built-in starter recipes and user-approved tasks.
- **UI & Browser Regression Tests (`Playwright`):**
  - Verify 1-Button Zero-Form quick start alongside existing App → Task → Versioned Training flows.
  - Verify zero regressions across all baseline tests.

---

## 8. Boundaries

- **Always do:**
  - Preserve all baseline tests and `0.3.0a3` data/schema compatibility.
  - Default every CLI, API, and MCP recipe invocation to `dry_run=True`.
  - Keep all user/session strings labeled as untrusted data in MCP responses.
- **Ask first:**
  - Any change to external ports, system services, or deployment paths.
  - Adding any new third-party PyPI dependency.
- **Never do:**
  - Claim native video pixel understanding or arbitrary GUI replay where execution is hybrid/script-driven or fixture-scoped.

---

## 9. Success Criteria

- [x] `docs/specs/SPEC-hybrid-universal.md` is retained in `source/docs/specs/`.
- [x] Hybrid Engine supports "AI Thinks (parameter extraction), Script Executes (deterministic sandbox runner)" with mandatory dry-run diff preview and rollback receipt.
- [x] 1-Button Zero-Form UX enables starting a recording or running a starter hybrid recipe in one click without pre-record form friction, while preserving the `0.3.0a3` App/Task training flow.
- [x] Universal Agent Adapters work end-to-end via CLI (`holdmybeer export-skill`, `holdmybeer detect-agents`), HTTP API, and MCP (`mcp_server.py`) for `SKILL.md` and OpenAI tool schemas.
- [x] All baseline + new pytest suites pass (`0` failures).
