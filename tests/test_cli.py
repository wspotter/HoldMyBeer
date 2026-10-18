"""Tests for the packaged ``holdmybeer`` CLI: launch defaults, port handling and the read-only doctor."""
import argparse
import json
import socket
import sys

import pytest

import holdmybeer.cli as cli
import holdmybeer.app as backend
from holdmybeer import __version__


# --------------------------------------------------------------------------- #
# argument parsing and validation
# --------------------------------------------------------------------------- #
def test_help_lists_launch_and_doctor_options(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Launch the local HoldMyBeer preview" in out
    assert "doctor" in out
    assert "--port" in out
    assert "--data-dir" in out
    assert "loopback" in out


def test_version_flag_reports_single_literal(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("value", ["not-a-number", "70000", "-1", "12.5", "65536"])
def test_malformed_or_out_of_range_ports_rejected(value):
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--port", value])
    assert exc.value.code == cli.EXIT_ERROR


@pytest.mark.parametrize("value", [0, 1, 18940, 65535])
def test_valid_ports_accepted(value):
    parser = cli.build_parser()
    assert parser.parse_args(["--port", str(value)]).port == value


def test_default_port_is_loopback_and_stable():
    parser = cli.build_parser()
    args = parser.parse_args([])
    assert args.port == cli.DEFAULT_PORT
    assert args.host == cli.DEFAULT_HOST


def _fake_mcp_command(tmp_path, monkeypatch):
    command = tmp_path / "bin" / "holdmybeer-mcp"
    command.parent.mkdir()
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o755)
    active_bin = tmp_path / "active" / "bin"
    active_bin.mkdir(parents=True)
    monkeypatch.setattr(cli.sys, "executable", str(active_bin / "python"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(command) if name == "holdmybeer-mcp" else None)
    return command.resolve()


def test_connect_hermes_requires_explicit_home_and_does_not_touch_default_profile(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HMB_DATA_DIR", raising=False)
    data_dir = tmp_path / "hmb-data"
    code = cli.main(["connect", "hermes", "--data-dir", str(data_dir)])
    assert code == cli.EXIT_ERROR
    assert "--home is required" in capsys.readouterr().err
    assert not (tmp_path / ".hermes" / "config.yaml").exists()


def test_connect_hermes_creates_private_isolated_config(tmp_path, monkeypatch, capsys):
    command = _fake_mcp_command(tmp_path, monkeypatch)
    home = tmp_path / "hermes-home"
    data_dir = tmp_path / "hmb-data"
    code = cli.main(["connect", "hermes", "--home", str(home), "--data-dir", str(data_dir)])
    assert code == cli.EXIT_OK
    config_path = home / "config.yaml"
    config = json.loads(config_path.read_text())
    assert config == {
        "mcp_servers": {
            "holdmybeer": {
                "command": str(command),
                "args": [],
                "env": {"HMB_DATA_DIR": str(data_dir), "HMB_URL": cli.DEFAULT_HMB_URL},
            }
        }
    }
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert list(home.glob("config.yaml.bak-*")) == []
    assert "does not start Hermes" in capsys.readouterr().out


def test_connect_hermes_preserves_other_json_settings_and_backs_up_first(tmp_path, monkeypatch, capsys):
    command = _fake_mcp_command(tmp_path, monkeypatch)
    home = tmp_path / "hermes-home"
    home.mkdir()
    config_path = home / "config.yaml"
    original = '{"model": {"name": "local"}, "mcp_servers": {"calendar": {"url": "http://localhost"}}}\n'
    config_path.write_text(original)
    code = cli.main(["connect", "hermes", "--home", str(home), "--data-dir", str(tmp_path / "data")])
    assert code == cli.EXIT_OK
    backups = list(home.glob("config.yaml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    result = json.loads(config_path.read_text())
    assert result["model"] == {"name": "local"}
    assert result["mcp_servers"]["calendar"] == {"url": "http://localhost"}
    assert result["mcp_servers"]["holdmybeer"]["command"] == str(command)
    assert "Backup:" in capsys.readouterr().out


def test_connect_hermes_exact_entry_is_idempotent_without_backup(tmp_path, monkeypatch, capsys):
    command = _fake_mcp_command(tmp_path, monkeypatch)
    home = tmp_path / "hermes-home"
    data_dir = tmp_path / "data"
    entry = cli._hermes_mcp_entry(data_dir, command)
    home.mkdir()
    (home / "config.yaml").write_text(json.dumps({"mcp_servers": {"holdmybeer": entry}}))
    original = (home / "config.yaml").read_bytes()
    code = cli.main(["connect", "hermes", "--home", str(home), "--data-dir", str(data_dir)])
    assert code == cli.EXIT_OK
    assert (home / "config.yaml").read_bytes() == original
    assert list(home.glob("config.yaml.bak-*")) == []
    assert "already matches" in capsys.readouterr().out


def test_connect_hermes_uses_explicit_url_and_active_environment_executable(tmp_path, monkeypatch):
    active_bin = tmp_path / "active" / "bin"
    active_bin.mkdir(parents=True)
    sibling = active_bin / "holdmybeer-mcp"
    sibling.write_text("#!/bin/sh\nexit 0\n")
    sibling.chmod(0o755)
    other = tmp_path / "other" / "bin" / "holdmybeer-mcp"
    other.parent.mkdir(parents=True)
    other.write_text("#!/bin/sh\nexit 0\n")
    other.chmod(0o755)
    monkeypatch.setattr(cli.sys, "executable", str(active_bin / "python"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(other))
    home = tmp_path / "hermes-home"
    data_dir = tmp_path / "data"
    code = cli.main([
        "connect", "hermes", "--home", str(home), "--data-dir", str(data_dir),
        "--url", "http://localhost:18941/",
    ])
    assert code == cli.EXIT_OK
    entry = json.loads((home / "config.yaml").read_text())["mcp_servers"]["holdmybeer"]
    assert entry["command"] == str(sibling.resolve())
    assert entry["env"] == {"HMB_DATA_DIR": str(data_dir), "HMB_URL": "http://localhost:18941"}


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:18940",
    "http://example.com:18940",
    "http://127.0.0.1:0",
    "http://127.0.0.1:65536",
    "http://127.0.0.1:nope",
    "http://127.0.0.1:",
    "http://user@127.0.0.1:18940",
    "http://127.0.0.1:18940/private",
    "http://127.0.0.1:18940?x=1",
    "http://127.0.0.1:18940#fragment",
    "http://127.0.0.1:18940?",
    "http://127.0.0.1:18940#",
])
def test_connect_hermes_rejects_non_loopback_or_malformed_urls(url):
    with pytest.raises(ValueError):
        cli._loopback_http_url(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:18940",
    "http://localhost:1/",
    "http://[::1]:65535",
])
def test_connect_hermes_accepts_loopback_http_urls(url):
    assert cli._loopback_http_url(url).rstrip("/") == url.rstrip("/")


def test_connect_hermes_refuses_conflicting_or_non_json_yaml_without_changes(tmp_path, monkeypatch, capsys):
    _fake_mcp_command(tmp_path, monkeypatch)
    home = tmp_path / "hermes-home"
    home.mkdir()
    config_path = home / "config.yaml"
    for original, expected_error in [
        ('{"mcp_servers":{"holdmybeer":{"command":"/other/server"}}}\n', "already exists with different settings"),
        ("model:\n  name: local\n", "not JSON-compatible YAML"),
    ]:
        config_path.write_text(original)
        code = cli.main(["connect", "hermes", "--home", str(home), "--data-dir", str(tmp_path / "data")])
        assert code == cli.EXIT_ERROR
        assert config_path.read_text() == original
        assert list(home.glob("config.yaml.bak-*")) == []
        assert expected_error in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# data directory resolution
# --------------------------------------------------------------------------- #
def test_data_dir_honours_explicit_argument(tmp_path):
    chosen = tmp_path / "custom-data"
    args = cli.build_parser().parse_args(["--data-dir", str(chosen)])
    assert cli._resolve_data_dir(args.data_dir) == chosen.resolve()


def test_data_dir_falls_back_to_hmb_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("HMB_DATA_DIR", raising=False)
    monkeypatch.setenv("HMB_DATA_DIR", str(tmp_path / "from-env"))
    args = cli.build_parser().parse_args([])
    assert cli._resolve_data_dir(args.data_dir) == (tmp_path / "from-env").resolve()


# --------------------------------------------------------------------------- #
# port reservation with a real bound socket
# --------------------------------------------------------------------------- #
def _listen_on(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    sock.bind((host, port))
    sock.listen(1)
    return sock


def test_reserve_free_port_returns_socket():
    with _listen_on("127.0.0.1", 0) as guard:
        port = guard.getsockname()[1]
    # Port is free again; reservation should succeed and return a usable socket.
    reserved = cli._reserve_host_socket("127.0.0.1", port)
    try:
        assert reserved.getsockname()[1] == port
    finally:
        reserved.close()


def test_reserve_occupied_port_raises_with_real_socket():
    guard = _listen_on("127.0.0.1", 0)
    port = guard.getsockname()[1]
    try:
        with pytest.raises(cli.PortInUse) as exc:
            cli._reserve_host_socket("127.0.0.1", port)
        assert exc.value.port == port
        assert exc.value.host == "127.0.0.1"
    finally:
        guard.close()


# --------------------------------------------------------------------------- #
# launch command
# --------------------------------------------------------------------------- #
def test_launch_occupied_port_errors_without_starting_server(tmp_path, monkeypatch, capsys):
    guard = _listen_on("127.0.0.1", 0)
    port = guard.getsockname()[1]
    data_dir = tmp_path / "should-not-be-created"
    try:
        code = cli.main(["--port", str(port), "--data-dir", str(data_dir)])
    finally:
        guard.close()
    assert code == cli.EXIT_ERROR
    assert "already in use" in capsys.readouterr().err
    # Bind failed before create_app, so no application store was created.
    assert not data_dir.exists()


def test_launch_free_port_starts_server(tmp_path):
    import json
    import os
    from pathlib import Path
    import re
    import subprocess
    import time
    import httpx

    chosen = tmp_path / "chosen"
    env = dict(os.environ, HOME=str(tmp_path), PYTHONUNBUFFERED="1")
    env.pop("HMB_DATA_DIR", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    log = tmp_path / "launch.log"
    with log.open("w") as output:
        process = subprocess.Popen([sys.executable, "-m", "holdmybeer", "--port", "0", "--data-dir", str(chosen)], env=env, cwd=tmp_path, stdout=output, stderr=subprocess.STDOUT)
        try:
            for _ in range(150):
                match = re.search(r"http://127\.0\.0\.1:(\d+)", log.read_text())
                if match:
                    try:
                        response = httpx.get(match.group(0) + "/api/status", timeout=.2)
                        if response.is_success:
                            break
                    except httpx.HTTPError:
                        pass
                assert process.poll() is None, log.read_text()
                time.sleep(.05)
            else:
                pytest.fail(log.read_text())
            assert int(match.group(1)) > 0
            assert chosen.is_dir()
            assert not (tmp_path / ".local/share/holdmybeer").exists()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_doctor_subprocess_does_not_create_default_store(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    env = dict(os.environ, HOME=str(tmp_path))
    env.pop("HMB_DATA_DIR", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, "-m", "holdmybeer", "doctor"], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode in (0, 2)
    assert "HoldMyBeer doctor" in result.stdout
    assert not (tmp_path / ".local/share/holdmybeer").exists()


def test_doctor_repair_commands_use_python_modules_and_quote_interpreter():
    import shlex
    report = {"version": __version__, "python": "3", "interpreter": "/some path/python", "required_modules": {name: False for name in cli.REQUIRED_MODULES}, "missing_modules": list(cli.REQUIRED_MODULES), "chromium": {"available": False, "reason": "missing"}, "ffmpeg": False, "ffprobe": False}
    text = cli.format_doctor_report(report)
    commands = [line.strip().removeprefix("install with: ") for line in text.splitlines() if " -m " in line]
    tokens = [shlex.split(command) for command in commands]
    assert [report["interpreter"], "-m", "playwright", "install", "chromium"] in tokens
    assert [report["interpreter"], "-m", "pip", "install", "playwright"] in tokens


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def test_doctor_reports_present_modules_and_chromium_path():
    report = cli.build_doctor_report()
    assert report["version"] == __version__
    assert set(report["required_modules"]) == set(cli.REQUIRED_MODULES)
    # All four required modules are installed in the test environment.
    assert all(report["required_modules"].values())
    assert report["missing_modules"] == []
    # Chromium resolves to a concrete executable path (may or may not be installed).
    assert isinstance(report["chromium"]["executable"], str)
    assert report["chromium"]["available"] in (True, False)


def test_doctor_flags_missing_chromium_and_gives_install_command(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_executable", lambda: "/nope/ms-playwright/chromium-9999/chrome-linux/chrome")
    report = cli.build_doctor_report()
    assert report["chromium"]["available"] is False
    assert "install" in report["chromium"]["reason"]
    text = cli.format_doctor_report(report)
    assert "playwright install chromium" in text
    assert report["interpreter"] in text
    assert cli.doctor_report_is_ok(report) is False


def test_doctor_flags_missing_required_module(monkeypatch):
    monkeypatch.setattr(cli, "_module_ok", lambda name: name != "playwright")
    report = cli.build_doctor_report()
    assert report["missing_modules"] == ["playwright"]
    assert cli.doctor_report_is_ok(report) is False


def test_doctor_exit_code_reflects_required_health(tmp_path, monkeypatch, capsys):
    # In this environment the matching Chromium build is not installed, so the
    # doctor must exit non-zero while still reporting the optional frame tools.
    monkeypatch.setattr(cli, "_chromium_executable", lambda: "/nope/chrome")
    code = cli.cmd_doctor(argparse.Namespace())
    assert code == cli.EXIT_ERROR
    out = capsys.readouterr().out
    assert "chromium:       MISSING" in out
    assert "playwright install chromium" in out
    assert "ffmpeg" in out and "ffprobe" in out


def test_doctor_stays_read_only(monkeypatch):
    # Doctor must not import create_app or touch the data directory. If it did,
    # the spy (which raises) would surface as an error.
    def _spy_create_app(data_dir):
        raise AssertionError("doctor created application data")

    monkeypatch.setattr(backend, "create_app", _spy_create_app)
    report = cli.build_doctor_report()
    assert report["version"] == __version__


def test_cli_list_empty(tmp_path, capsys):
    data_dir = tmp_path / "data"
    code = cli.main(["list", "--data-dir", str(data_dir)])
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "No workflows found" in out


def test_cli_list_and_run_with_recipes(tmp_path, capsys):
    from holdmybeer.app import Store
    from holdmybeer.hybrid import HybridRecipe, HybridParameter, HybridStep, save_hybrid_recipe
    data_dir = tmp_path / "data"
    store = Store(data_dir)
    recipe = HybridRecipe(
        task_id="task-cli-test-1",
        title="Lookup Domain In Terminal",
        app_name="terminal",
        parameters=[
            HybridParameter(name="target_host", type="string", description="Domain name", default="yahoo.com", required=True),
        ],
        steps=[
            HybridStep(
                id="s1",
                action="browser_or_fixture_action",
                goal="nslookup target domain",
                check="nslookup command finished",
                params={"command": "nslookup {target_host}"},
            )
        ],
        trigger_phrases=["Hey Ollie, run nslookup in terminal"],
    )
    save_hybrid_recipe(store, recipe.task_id, recipe)

    # Test list command
    code_list = cli.main(["list", "--data-dir", str(data_dir)])
    assert code_list == cli.EXIT_OK
    out_list = capsys.readouterr().out
    assert "Lookup Domain In Terminal" in out_list
    assert "lookup_domain_in_terminal" in out_list
    assert "target_host" in out_list
    assert "Hey Ollie, run nslookup in terminal" in out_list

    # Test run command in safe sandbox dry-run
    code_run = cli.main(["run", "lookup_domain_in_terminal", "target_host=yahoo.com", "--data-dir", str(data_dir)])
    assert code_run == cli.EXIT_OK
    out_run = capsys.readouterr().out
    assert "HoldMyBeer Execution Receipt" in out_run
    assert "Safe Sandbox Simulation" in out_run
    assert "yahoo.com" in out_run
    assert "STATUS: VERIFIED" in out_run

    # Test run with --json
    code_json = cli.main(["run", "lookup_domain_in_terminal", "target_host=yahoo.com", "--data-dir", str(data_dir), "--json"])
    assert code_json == cli.EXIT_OK
    out_json = capsys.readouterr().out
    parsed = json.loads(out_json)
    assert parsed["status"] == "verified"
    assert parsed["bound_parameters"]["target_host"] == "yahoo.com"


def test_cli_run_missing_target_fails(capsys):
    code = cli.main(["run"])
    assert code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "missing target" in err


def test_cli_tui_exits_cleanly_on_empty(tmp_path, capsys):
    data_dir = tmp_path / "data"
    code = cli.main(["tui", "--data-dir", str(data_dir)])
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Terminal Skill Runner" in out
    assert "No workflows found" in out


def test_cli_tui_interactive_flow(tmp_path, monkeypatch, capsys):
    from holdmybeer.app import Store
    from holdmybeer.hybrid import HybridRecipe, HybridParameter, HybridStep, save_hybrid_recipe
    import io

    data_dir = tmp_path / "data"
    store = Store(data_dir)
    recipe = HybridRecipe(
        task_id="task-cli-test-2",
        title="Ping Host In Terminal",
        app_name="terminal",
        parameters=[
            HybridParameter(name="host", type="string", description="Host to ping", default="127.0.0.1", required=True),
        ],
        steps=[
            HybridStep(
                id="s1",
                action="browser_or_fixture_action",
                goal="ping host",
                check="ping completed",
                params={"command": "ping -c 1 {host}"},
            )
        ],
        trigger_phrases=["Hey Ollie, ping host in terminal"],
    )
    save_hybrid_recipe(store, recipe.task_id, recipe)

    # Simulate user entering:
    # 1. "1" (select workflow 1)
    # 2. "" (accept default parameter "127.0.0.1")
    # 3. "1" (select sandbox mode)
    # 4. "q" (quit)
    inputs = io.StringIO("1\n\n1\nq\n")
    monkeypatch.setattr("sys.stdin", inputs)

    code = cli.main(["tui", "--data-dir", str(data_dir)])
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Terminal Skill Runner" in out
    assert "Ping Host In Terminal" in out
    assert "Outcome: VERIFIED" in out
    assert "Goodbye!" in out


