"""Command line for the HoldMyBeer local preview.

Two commands:

* ``holdmybeer`` (no subcommand) launches the FastAPI preview on loopback.
* ``holdmybeer doctor`` runs a read-only dependency check.

The launcher binds a real socket before creating any application data so a
failed bind never leaves a half-initialised store behind. The preview stays on
loopback by default and never silently falls back to another port.
"""
from __future__ import annotations

import argparse
import errno
import importlib
import json
import os
import shlex
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit

from . import __version__

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18940
DEFAULT_DATA_DIR_ENV = "HMB_DATA_DIR"
DEFAULT_DATA_DIR = "~/.local/share/holdmybeer"
DEFAULT_HMB_URL = "http://127.0.0.1:18940"

# Required runtime imports for the preview and its runner. Optional frame tools
# (ffmpeg/ffprobe) are reported but do not gate launch or the doctor exit code.
REQUIRED_MODULES = {
    "fastapi": "FastAPI",
    "uvicorn": "Uvicorn",
    "playwright": "Playwright",
    "mcp": "MCP SDK",
}

# Map a required module to the pip distribution that installs it, so the doctor
# can hand back a runnable install command per missing module.
PIP_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "playwright": "playwright",
    "mcp": "mcp",
}

# Exit codes.
EXIT_OK = 0
EXIT_ERROR = 2


class PortInUse(OSError):
    """Raised when the requested loopback port cannot be reserved."""

    def __init__(self, port: int, host: str) -> None:
        super().__init__(f"port {port} is already in use on {host}")
        self.port = port
        self.host = host


def _resolve_data_dir(data_dir: str | None) -> Path:
    """Return the data directory, honouring ``HMB_DATA_DIR`` like the app."""
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    fallback = os.environ.get(DEFAULT_DATA_DIR_ENV, DEFAULT_DATA_DIR)
    return Path(fallback).expanduser().resolve()


def _port_type(value: str) -> int:
    """Argparse type: an integer within the valid TCP range."""
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"port must be an integer, got {value!r}") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 0 and 65535, got {port}")
    return port


def _reserve_host_socket(host: str, port: int) -> socket.socket:
    """Bind a listening socket on ``host:port`` or raise :class:`PortInUse`.

    Binding here is the availability check: a second caller bound to the same
    address afterwards receives ``EADDRINUSE``. The socket is returned to the
    caller so it can be handed to the server, closing the check/bind race.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(1)
    except OSError as exc:
        sock.close()
        if exc.errno == errno.EADDRINUSE:
            raise PortInUse(port, host) from exc
        raise
    return sock


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def _module_ok(name: str) -> bool:
    try:
        importlib.import_module(name)
    except Exception:  # noqa: BLE001 - any import failure means "missing"
        return False
    return True


def _chromium_executable() -> str | None:
    """Return the executable path Playwright resolves for its Chromium build."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return playwright.chromium.executable_path
    except Exception:  # noqa: BLE001 - resolution or launch helpers can fail
        return None


def _chromium_status() -> dict:
    executable = _chromium_executable()
    if executable is None:
        return {
            "available": False,
            "executable": None,
            "reason": "Playwright could not resolve a matching Chromium executable",
        }
    available = Path(executable).is_file() and os.access(executable, os.X_OK)
    if available:
        return {"available": True, "executable": executable, "reason": None}
    return {
        "available": False,
        "executable": executable,
        "reason": (
            "matching Chromium executable is not installed"
            if not Path(executable).is_file()
            else "matching Chromium executable is present but not runnable"
        ),
    }


def _binary_available(name: str) -> bool:
    return shutil.which(name) is not None


def _interp_cmd(interpreter: str, *args: str) -> str:
    """Return ``<interpreter> <args>`` with the interpreter quoted for spaces."""
    return " ".join([shlex.quote(interpreter), *args])


def build_doctor_report() -> dict:
    """Collect the read-only doctor findings without touching application data."""
    modules = {name: _module_ok(name) for name in REQUIRED_MODULES}
    chromium = _chromium_status()
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "interpreter": sys.executable,
        "required_modules": modules,
        "missing_modules": [name for name, ok in modules.items() if not ok],
        "chromium": chromium,
        "ffmpeg": _binary_available("ffmpeg"),
        "ffprobe": _binary_available("ffprobe"),
    }


def doctor_report_is_ok(report: dict) -> bool:
    """A report is healthy when every required module is present and Chromium matches."""
    if report["missing_modules"]:
        return False
    return bool(report["chromium"].get("available"))


def format_doctor_report(report: dict) -> str:
    lines: list[str] = []
    lines.append("HoldMyBeer doctor")
    lines.append(f"  version:        {report['version']}")
    lines.append(f"  python:         {report['python']} ({report['interpreter']})")
    lines.append("  required modules:")
    for name in REQUIRED_MODULES:
        ok = report["required_modules"][name]
        lines.append(f"    [{'ok' if ok else 'MISSING'}] {name}")
    chromium = report["chromium"]
    if chromium["available"]:
        lines.append(f"  chromium:       OK ({chromium['executable']})")
    else:
        lines.append(f"  chromium:       MISSING — {chromium['reason']}")
        lines.append(
            f"    install with: {_interp_cmd(report['interpreter'], '-m', 'playwright', 'install', 'chromium')}"
        )
    lines.append("  frame tools (optional):")
    lines.append(f"    [{'ok' if report['ffmpeg'] else 'missing'}] ffmpeg")
    lines.append(f"    [{'ok' if report['ffprobe'] else 'missing'}] ffprobe")
    if report["missing_modules"]:
        lines.append(
            "  missing required module(s): " + ", ".join(report["missing_modules"])
        )
        lines.append("  repair each with:")
        for name in report["missing_modules"]:
            pkg = PIP_PACKAGES.get(name, name)
            lines.append(f"    {_interp_cmd(report['interpreter'], '-m', 'pip', 'install', pkg)}")
    return "\n".join(lines)


def cmd_doctor(_args: argparse.Namespace) -> int:
    report = build_doctor_report()
    print(format_doctor_report(report))
    return EXIT_OK if doctor_report_is_ok(report) else EXIT_ERROR


# --------------------------------------------------------------------------- #
# Hermes client configuration
# --------------------------------------------------------------------------- #
def _absolute_path(value: str | None, option: str) -> Path:
    if not value:
        raise ValueError(f"{option} is required; pass an absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{option} must be an absolute path: {value}")
    return path.resolve()


def _loopback_http_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("--url must be an HTTP loopback URL with a valid port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or (port is not None and not 1 <= port <= 65535)
        or parsed.netloc.endswith(":")
    ):
        raise ValueError("--url must be an HTTP loopback URL without credentials, path, query, or fragment")
    return value.rstrip("/")


def _installed_mcp_command() -> Path | None:
    sibling = Path(sys.executable).absolute().parent / "holdmybeer-mcp"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling.resolve()
    command_text = shutil.which("holdmybeer-mcp")
    if not command_text:
        return None
    command = Path(command_text).resolve()
    return command if command.is_file() and os.access(command, os.X_OK) else None


def _hermes_mcp_entry(data_dir: Path, command: Path, url: str = DEFAULT_HMB_URL) -> dict:
    return {
        "command": str(command),
        "args": [],
        "env": {DEFAULT_DATA_DIR_ENV: str(data_dir), "HMB_URL": url},
    }


def _write_hermes_config(home: Path, data_dir: Path, command: Path, url: str = DEFAULT_HMB_URL) -> tuple[bool, Path | None]:
    """Merge one MCP entry into JSON-compatible YAML without a YAML dependency.

    JSON is valid YAML. Refusing other YAML syntax lets this installer preserve
    unrelated Hermes settings exactly instead of rewriting them with a
    partial or lossy parser.
    """
    config_path = home / "config.yaml"
    expected = _hermes_mcp_entry(data_dir, command, url)
    if config_path.exists():
        original = config_path.read_bytes()
        try:
            config = json.loads(original)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            snippet = json.dumps({"mcp_servers": {"holdmybeer": expected}}, indent=2)
            raise ValueError(
                "Existing config.yaml is not JSON-compatible YAML; it was left unchanged. "
                "Merge this entry manually or use a dedicated empty --home:\n" + snippet
            ) from exc
        if not isinstance(config, dict):
            raise ValueError("Existing config.yaml must contain a JSON/YAML mapping; no changes made")
    else:
        original = None
        config = {}

    servers = config.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("Existing mcp_servers setting is not a mapping; no changes made")
    if "holdmybeer" in servers:
        if servers["holdmybeer"] == expected:
            return False, None
        raise ValueError("mcp_servers.holdmybeer already exists with different settings; no changes made")

    config["mcp_servers"] = {**servers, "holdmybeer": expected}
    payload = (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    backup_path = None
    if original is not None:
        backup_path = home / f"config.yaml.bak-{time.time_ns()}"
        shutil.copy2(config_path, backup_path)

    fd, temporary_name = tempfile.mkstemp(prefix=".config.yaml.", suffix=".tmp", dir=home)
    try:
        if original is None:
            os.fchmod(fd, 0o600)
        else:
            os.fchmod(fd, config_path.stat().st_mode & 0o777)
        with os.fdopen(fd, "wb") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, config_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return True, backup_path


def cmd_connect_hermes(args: argparse.Namespace) -> int:
    try:
        home = _absolute_path(args.home, "--home")
        data_dir = _absolute_path(args.data_dir, "--data-dir")
        url = _loopback_http_url(args.url)
        command = _installed_mcp_command()
        if command is None:
            raise ValueError("holdmybeer-mcp is not installed or not on PATH; install the project environment first")
        home.mkdir(parents=True, exist_ok=True)
        changed, backup = _write_hermes_config(home, data_dir, command, url)
    except (OSError, ValueError) as exc:
        print(f"holdmybeer: could not configure Hermes: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if changed:
        print(f"Configured Hermes MCP entry in {home / 'config.yaml'}")
        if backup:
            print(f"Backup: {backup}")
        print("Restart Hermes to load the MCP server. This command does not start Hermes or install skills.")
    else:
        print(f"Hermes MCP entry already matches in {home / 'config.yaml'}; no file changed.")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# launch
# --------------------------------------------------------------------------- #
def cmd_launch(args: argparse.Namespace) -> int:
    host = args.host
    port = args.port
    data_dir = _resolve_data_dir(args.data_dir)

    # Reserve the port before importing the app so a failed bind never creates
    # an application store or data directory.
    try:
        sock = _reserve_host_socket(host, port)
    except PortInUse as exc:
        print(f"holdmybeer: error: {exc}", file=sys.stderr)
        print(
            f"  {exc.port} is already bound on {exc.host}; "
            f"stop that process or pass a different --port (or --port 0 for an ephemeral port)",
            file=sys.stderr,
        )
        return EXIT_ERROR

    try:
        import uvicorn

        # Point HMB_DATA_DIR at the resolved directory before importing .app so
        # the module-global app/store (created at import time) is built under the
        # chosen directory instead of the user's default store.
        os.environ[DEFAULT_DATA_DIR_ENV] = str(data_dir)

        from .app import create_app

        # create_app builds the Store (data dir) only after the bind succeeded.
        app = create_app(data_dir)
        bound_port = sock.getsockname()[1]
        config = uvicorn.Config(
            app,
            host=host,
            port=bound_port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        scheme = "http"
        url_host = f"[{host}]" if ":" in host else host
        print(f"HoldMyBeer preview v{__version__} on {scheme}://{url_host}:{bound_port}", flush=True)
        print(f"  data directory: {data_dir}")
        print("  press Ctrl-C to stop")
        server.run(sockets=[sock])
        return EXIT_OK
    finally:
        sock.close()


def cmd_universal_agents(args: argparse.Namespace) -> int:
    from .hybrid import detect_universal_agents
    data_dir = _resolve_data_dir(args.data_dir)
    info = detect_universal_agents(data_dir=data_dir, url=args.url)
    lines = [
        "HoldMyBeer Universal Agent Interoperability",
        f"  OpenAI Tools Schema: {info['openai_tools_endpoint']}",
        f"  MCP Server Command:  {info['mcp_command']}",
        "  Agent Environments:",
    ]
    for agent in info["agents"]:
        state = "DETECTED" if agent["detected"] else "ready"
        lines.append(f"    [{state}] {agent['name']} ({agent['id']})")
        lines.append(f"      connect: {agent['connect_one_liner']}")
    print("\n".join(lines))
    return EXIT_OK


def cmd_export_skill(args: argparse.Namespace) -> int:
    if not getattr(args, "task_id", None) or not getattr(args, "output_dir", None):
        print("holdmybeer: export-skill requires --task-id and --output-dir", file=sys.stderr)
        return EXIT_ERROR
    from .app import Store
    from .hybrid import export_skill_bundle, resolve_task_or_session_recipe
    data_dir = _resolve_data_dir(args.data_dir)
    store = Store(data_dir)
    try:
        recipe = resolve_task_or_session_recipe(store, args.task_id)
        bundle = export_skill_bundle(recipe, args.output_dir)
    except Exception as exc:
        print(f"holdmybeer: could not export skill: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(bundle, indent=2))
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    from .app import Store
    from .hybrid import list_hybrid_recipes
    data_dir = _resolve_data_dir(args.data_dir)
    store = Store(data_dir)
    recipes = list_hybrid_recipes(store)

    if getattr(args, "json", False):
        print(json.dumps([r.model_dump() for r in recipes], indent=2))
        return EXIT_OK

    if not recipes:
        print(f"HoldMyBeer Workflows: No workflows found in {data_dir}")
        print("Teach a workflow first using the web UI (holdmybeer) or teach endpoint.")
        return EXIT_OK

    print(f"🍺 HoldMyBeer Workflows ({len(recipes)} available):")
    print("-" * 65)
    for idx, r in enumerate(recipes, 1):
        params_str = ", ".join(f"{p.name} ({p.type})" for p in r.parameters) or "none"
        trigger = r.trigger_phrases[0] if r.trigger_phrases else f"Run {r.title} in {r.app_name}"
        print(f"[{idx}] {r.title}")
        print(f"    Slug:       {r.slug()}")
        print(f"    App:        {r.app_name}")
        print(f"    Params:     {params_str}")
        print(f"    Voice:      “{trigger}”")
        print(f"    Task ID:    {r.task_id}")
        if idx < len(recipes):
            print("-" * 65)
    print("=" * 65)
    print("Run via CLI:  holdmybeer run <slug_or_number> [param=value]")
    print("Interactive:  holdmybeer tui")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    target = getattr(args, "target", None)
    if not target:
        print("holdmybeer run: missing target skill/workflow name, slug, or ID.", file=sys.stderr)
        print("Usage: holdmybeer run <slug_or_number_or_id> [param=val ...]", file=sys.stderr)
        return EXIT_ERROR

    from .app import Store
    from .hybrid import list_hybrid_recipes, resolve_task_or_session_recipe, run_hybrid_recipe
    data_dir = _resolve_data_dir(args.data_dir)
    store = Store(data_dir)
    recipes = list_hybrid_recipes(store)

    chosen_recipe = None
    # 1. Match by numeric index if user typed a number
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(recipes):
            chosen_recipe = recipes[idx - 1]

    # 2. Match by exact slug or task_id or recipe_id
    if chosen_recipe is None:
        target_lower = target.lower().strip()
        for r in recipes:
            if r.slug() == target_lower or r.task_id == target or r.recipe_id == target:
                chosen_recipe = r
                break

    # 3. Match by case-insensitive title or slug substring
    if chosen_recipe is None:
        target_lower = target.lower().strip()
        for r in recipes:
            if target_lower in r.title.lower() or target_lower in r.slug():
                chosen_recipe = r
                break

    # 4. Fallback to resolve_task_or_session_recipe
    if chosen_recipe is None:
        try:
            chosen_recipe = resolve_task_or_session_recipe(store, target)
        except Exception:
            chosen_recipe = None

    if chosen_recipe is None:
        print(f"holdmybeer run: could not find workflow matching '{target}'.", file=sys.stderr)
        print("Run 'holdmybeer list' to view available workflows.", file=sys.stderr)
        return EXIT_ERROR

    # Parse parameters
    raw_params = list(getattr(args, "params", []) or [])
    bound_params: dict[str, Any] = {}

    if len(raw_params) == 1 and "=" not in raw_params[0]:
        if chosen_recipe.parameters:
            bound_params[chosen_recipe.parameters[0].name] = raw_params[0]
        else:
            bound_params["input_text"] = raw_params[0]
    else:
        for p in raw_params:
            if "=" in p:
                k, v = p.split("=", 1)
                bound_params[k.strip()] = v.strip()
            else:
                bound_params[p.strip()] = ""

    dry_run = not getattr(args, "live", False)
    target_dir = getattr(args, "target_dir", None)

    try:
        res = run_hybrid_recipe(
            chosen_recipe,
            parameters=bound_params,
            target_dir=target_dir,
            dry_run=dry_run,
            user_approved_understanding=not dry_run,
        )
    except Exception as exc:
        print(f"holdmybeer run: error executing workflow: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
        return EXIT_OK if res.get("status") in {"verified", "success"} else EXIT_ERROR

    mode_label = "Safe Sandbox Simulation (Dry Run)" if dry_run else "LIVE REPLAY"
    print(f"🍺 HoldMyBeer Execution Receipt")
    print("=" * 65)
    print(f"  Workflow:   {chosen_recipe.title} (slug: {chosen_recipe.slug()})")
    print(f"  App:        {chosen_recipe.app_name}")
    print(f"  Mode:       {mode_label}")
    print(f"  Parameters: {res.get('bound_parameters', bound_params)}")
    print("-" * 65)
    print("  Execution Steps:")
    for step in res.get("steps", []):
        sid = step.get("id", "step")
        goal = step.get("goal", "")
        print(f"    ✓ [{sid}] {goal}")
    print("-" * 65)
    status = res.get("status", "unknown").upper()
    if status in {"VERIFIED", "SUCCESS"}:
        print(f"  Outcome:    STATUS: {status} ✨")
        diff = res.get("before_after_diff") or {}
        changes = diff.get("changes") or []
        if dry_run:
            print(f"  Sandbox:    Isolated ({len(changes)} simulated changes, 0 real files mutated)")
        else:
            print(f"  Real Files: {len(changes)} changes applied")
    else:
        print(f"  Outcome:    STATUS: {status}")
        snap = res.get("diagnostic_snapshot") or {}
        if snap:
            print(f"  Issue:      {snap.get('error_reason')}")
            print(f"  Suggested:  {snap.get('suggested_recovery_prompt')}")
    print("=" * 65)
    return EXIT_OK if res.get("status") in {"verified", "success"} else EXIT_ERROR


def cmd_tui(args: argparse.Namespace) -> int:
    from .app import Store
    from .hybrid import list_hybrid_recipes, run_hybrid_recipe
    data_dir = _resolve_data_dir(args.data_dir)
    store = Store(data_dir)

    print("\n" + "=" * 65)
    print("🍺 HoldMyBeer — Terminal Skill Runner (TUI)")
    print("=" * 65)

    recipes = list_hybrid_recipes(store)
    if not recipes:
        print(f"No workflows found in: {data_dir}")
        print("Teach your first workflow by starting the preview: holdmybeer\n")
        return EXIT_OK

    while True:
        print("\nAvailable Workflows:")
        for idx, r in enumerate(recipes, 1):
            trigger = r.trigger_phrases[0] if r.trigger_phrases else f"Run {r.title} in {r.app_name}"
            params_str = ", ".join(f"{p.name}" for p in r.parameters) or "none"
            print(f"  [{idx}] {r.title} (App: {r.app_name})")
            print(f"      Params: {params_str} | Voice: “{trigger}”")
        print("  [q] Quit")
        print("-" * 65)

        try:
            choice = input(f"Select a workflow to run [1-{len(recipes)}, q]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting HoldMyBeer TUI.")
            return EXIT_OK

        if choice.lower() in {"q", "quit", "exit"}:
            print("Goodbye! 🍺")
            return EXIT_OK

        chosen_recipe = None
        if choice.isdigit() and 1 <= int(choice) <= len(recipes):
            chosen_recipe = recipes[int(choice) - 1]
        else:
            for r in recipes:
                if choice.lower() == r.slug() or choice.lower() in r.title.lower():
                    chosen_recipe = r
                    break

        if chosen_recipe is None:
            print(f"Invalid selection: '{choice}'. Please pick a number from 1 to {len(recipes)}.")
            continue

        print(f"\nSelected: {chosen_recipe.title} (App: {chosen_recipe.app_name})")
        bound_params: dict[str, Any] = {}
        for p in chosen_recipe.parameters:
            default_val = p.default or ""
            prompt_str = f"  Parameter '{p.name}'"
            if default_val:
                prompt_str += f" [{default_val}]"
            prompt_str += ": "
            try:
                val = input(prompt_str).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCanceled.")
                return EXIT_OK
            bound_params[p.name] = val if val else default_val

        print("\nExecution Mode:")
        print("  [1] Safe Sandbox Simulation (Dry Run) [default]")
        print("  [2] Live Replay")
        try:
            mode_choice = input("Select mode [1/2, default 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCanceled.")
            return EXIT_OK

        is_live = mode_choice == "2"
        dry_run = not is_live

        print(f"\n> Running '{chosen_recipe.title}' in {'safe sandbox' if dry_run else 'LIVE mode'}...")
        try:
            res = run_hybrid_recipe(
                chosen_recipe,
                parameters=bound_params,
                dry_run=dry_run,
                user_approved_understanding=is_live,
            )
            print("-" * 65)
            for step in res.get("steps", []):
                print(f"  ✓ [{step.get('id', 'step')}] {step.get('goal', '')}")
            status = res.get("status", "unknown").upper()
            if status in {"VERIFIED", "SUCCESS"}:
                print(f"Outcome: {status} ✨ ({'Simulated in sandbox' if dry_run else 'Applied live'})\n")
            else:
                print(f"Outcome: {status}\n")
        except Exception as exc:
            print(f"Execution error: {exc}\n")

        try:
            cont = input("Run another workflow? [Y/n]: ").strip().lower()
            if cont in {"n", "no", "q"}:
                print("Goodbye! 🍺")
                return EXIT_OK
        except (EOFError, KeyboardInterrupt):
            print("\nExiting HoldMyBeer TUI.")
            return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="holdmybeer",
        description="Launch the local HoldMyBeer preview, check dependencies, configure an explicit Hermes home, list or run workflows, or launch the interactive TUI.",
        epilog=(
            "The preview binds loopback only by default. Use --host to change the "
            "interface, --port to change the port, and --data-dir to store data "
            "elsewhere (or set HMB_DATA_DIR)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"holdmybeer {__version__}",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["doctor", "connect", "agents", "universal-status", "export-skill", "list", "run", "tui"],
        help="Run doctor, configure a client, inspect universal agents, export a skill, list skills, run a skill, interactive TUI, or launch the preview when omitted.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Target skill name/slug/ID for 'run', or client name for 'connect' (e.g. hermes).",
    )
    parser.add_argument(
        "params",
        nargs="*",
        help="Optional parameter bindings for 'run' in key=value format (e.g. input_text=yahoo.com).",
    )
    # Launch options.
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Interface to bind (default: {DEFAULT_HOST}, loopback only).",
    )
    parser.add_argument(
        "--port",
        type=_port_type,
        default=DEFAULT_PORT,
        metavar="PORT",
        help=f"TCP port to bind (default: {DEFAULT_PORT}, 0-65535).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help="Store runtime data here instead of HMB_DATA_DIR or the default location.",
    )
    parser.add_argument(
        "--home",
        default=None,
        metavar="ABS_PATH",
        help="Explicit absolute Hermes home for 'connect hermes'; never defaults to ~/.hermes.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_HMB_URL,
        metavar="LOOPBACK_URL",
        help=f"Local HoldMyBeer app URL for issue briefs (default: {DEFAULT_HMB_URL}).",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        metavar="ID",
        help="Task or session ID for 'export-skill'.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Destination directory for 'export-skill'.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Run live against real target files/apps instead of safe sandbox simulation.",
    )
    parser.add_argument(
        "--target-dir",
        default=None,
        metavar="DIR",
        help="Optional target directory for 'run'.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output raw JSON results for 'list' or 'run'.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None) == "doctor":
        if getattr(args, "target", None) is not None or getattr(args, "home", None) is not None or getattr(args, "url", DEFAULT_HMB_URL) != DEFAULT_HMB_URL:
            print("holdmybeer: client names, --home and --url require 'connect hermes'", file=sys.stderr)
            return EXIT_ERROR
        return cmd_doctor(args)
    if getattr(args, "command", None) == "connect":
        if getattr(args, "target", None) != "hermes":
            print("holdmybeer: choose a client: connect hermes", file=sys.stderr)
            return EXIT_ERROR
        args.client = args.target
        return cmd_connect_hermes(args)
    if getattr(args, "command", None) in {"agents", "universal-status"}:
        return cmd_universal_agents(args)
    if getattr(args, "command", None) == "export-skill":
        return cmd_export_skill(args)
    if getattr(args, "command", None) == "list":
        return cmd_list(args)
    if getattr(args, "command", None) == "run":
        return cmd_run(args)
    if getattr(args, "command", None) == "tui":
        return cmd_tui(args)
    if getattr(args, "command", None) not in {"run", "connect"} and (getattr(args, "target", None) is not None or getattr(args, "home", None) is not None or getattr(args, "url", DEFAULT_HMB_URL) != DEFAULT_HMB_URL):
        print("holdmybeer: --home, --url and client names require 'connect hermes'", file=sys.stderr)
        return EXIT_ERROR
    try:
        return cmd_launch(args)
    except (OSError, ImportError) as exc:
        print(f"holdmybeer: could not launch: {exc}. Run holdmybeer doctor and check the host/data directory.", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
