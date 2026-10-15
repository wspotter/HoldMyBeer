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
import os
import shlex
import shutil
import socket
import sys
from pathlib import Path
from typing import Sequence

from . import __version__

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18940
DEFAULT_DATA_DIR_ENV = "HMB_DATA_DIR"
DEFAULT_DATA_DIR = "~/.local/share/holdmybeer"

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="holdmybeer",
        description="Launch the local HoldMyBeer preview or run a read-only doctor check.",
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
        choices=["doctor"],
        help="Run a read-only dependency check instead of launching the preview.",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None) == "doctor":
        return cmd_doctor(args)
    try:
        return cmd_launch(args)
    except (OSError, ImportError) as exc:
        print(f"holdmybeer: could not launch: {exc}. Run holdmybeer doctor and check the host/data directory.", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
