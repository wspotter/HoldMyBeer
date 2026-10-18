"""Run with an installed wheel's interpreter, outside the source import path."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def main():
    with tempfile.TemporaryDirectory(prefix="hmb-wheel-") as work:
        os.environ["HMB_DATA_DIR"] = str(Path(work) / "data")
        import likethis
        package_file = Path(likethis.__file__).resolve()
        source_root = Path(__file__).resolve().parents[1]
        if source_root == package_file.parent or source_root in package_file.parents:
            raise RuntimeError(f"wheel smoke imported LikeThis from source tree: {package_file}")
        from likethis.app import create_app
        app = create_app(Path(os.environ["HMB_DATA_DIR"]))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    if httpx.get(base + "/api/status", timeout=.2).is_success:
                        break
                except httpx.HTTPError:
                    time.sleep(.03)
            else:
                raise RuntimeError("wheel server did not start")
            for path in ("/", "/app.js", "/simple.js", "/briefs.js", "/directed.js", "/training.js", "/style.css", "/fixture"):
                assert httpx.get(base + path).status_code == 200, path

            trained_app = httpx.post(base + "/api/training/apps", json={"name": "Installed wheel app"})
            assert trained_app.status_code == 200, trained_app.text
            app_id = trained_app.json()["id"]
            task_a = httpx.post(base + f"/api/training/apps/{app_id}/tasks", json={
                "name": "First task", "description": "Save the requested file", "done": "Receipt matches inputs"})
            task_b = httpx.post(base + f"/api/training/apps/{app_id}/tasks", json={
                "name": "Second task", "description": "Prepare another file", "done": "The second receipt is retained"})
            assert task_a.status_code == task_b.status_code == 200, (task_a.text, task_b.text)
            first = task_a.json()
            second = task_b.json()
            assert first["session"]["id"] != second["session"]["id"]
            assert len(httpx.get(base + "/api/training/apps").json()["apps"][0]["tasks"]) == 2
            old_session = first["session"]
            old_sid = old_session["id"]
            retained_media = b"installed wheel training media bytes"
            upload = httpx.post(base + f"/api/sessions/{old_sid}/media", content=retained_media,
                                headers={"content-type": "video/webm"})
            assert upload.status_code == 200, upload.text
            edited = httpx.post(base + f"/api/training/tasks/{first['id']}/edit", json={"base_version": 1})
            assert edited.status_code == 200, edited.text
            version_two = edited.json()
            new_sid = version_two["session"]["id"]
            assert new_sid != old_sid and version_two["latest_version"] == 2
            assert version_two["versions"][0]["session_id"] == old_sid
            assert version_two["versions"][1]["session_id"] == new_sid
            copied = httpx.get(base + f"/api/sessions/{new_sid}/media")
            original = httpx.get(base + f"/api/sessions/{old_sid}/media")
            assert copied.content == original.content == retained_media
            assert httpx.put(base + f"/api/sessions/{old_sid}", json={"notes": "old version is frozen"}).status_code == 409
            assert httpx.put(base + f"/api/sessions/{new_sid}", json={"notes": "new draft is editable"}).status_code == 200
            task_url = base + f"/api/training/tasks/{first['id']}"
            settings = httpx.put(task_url + "/settings", json={"base_version": 2, "name": "Renamed first task",
                "description": "Save a file", "done": "Receipt visible", "notes": "Installed settings check"})
            assert settings.status_code == 200, settings.text
            version_three = settings.json()
            assert version_three["latest_version"] == 3
            assert httpx.get(base + f"/api/sessions/{version_three['session']['id']}/media").content == retained_media
            assert httpx.post(task_url + "/archive").json()["archived"] is True
            active_tasks = httpx.get(base + "/api/training/apps").json()["apps"][0]["tasks"]
            assert len(active_tasks) == 1 and active_tasks[0]["id"] == second["id"]
            assert httpx.put(task_url + "/settings", json={"base_version": 3, "name": "Blocked"}).status_code == 409
            restored = httpx.post(task_url + "/unarchive").json()
            assert restored["archived"] is False and len(restored["versions"]) == 3
            session = httpx.post(base + "/api/sessions", json={"title": "Installed wheel check"}).json()
            steps = [
                {"goal": "Upload", "check": "Fresh filename", "action": "upload", "target": "Media", "input": "filename"},
                {"goal": "Caption", "check": "Fresh caption", "action": "fill", "target": "Caption", "input": "caption"},
                {"goal": "Save", "check": "Receipt", "action": "click", "target": "Save draft"},
                {"goal": "Verify", "check": "Retained", "action": "verify_draft"},
            ]
            url = base + f"/api/sessions/{session['id']}"
            assert httpx.put(url, json={"procedure": {"revision": 2, "steps": steps}}).is_success
            run = httpx.post(url + "/run", json={"caption": "Installed wheel fresh input", "filename": "wheel.txt", "variant": "normal", "repair": False, "mode": "procedure"}, timeout=30).json()
            assert run["status"] == "verified", run
            assert httpx.get(base + run["screenshot_url"]).headers["content-type"] == "image/png"

            async def protocol():
                params = StdioServerParameters(command=sys.executable, args=["-m", "likethis.mcp_server"], env=dict(os.environ))
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        tools = await client.list_tools()
                        assert len(tools.tools) == 8
                        history = await client.call_tool('hmb_procedure_history', {'session_id': session['id'], 'revision': 2})
                        assert not history.isError
                        assert json.loads(history.content[0].text)['procedure']['steps'] == steps
                        result = await client.call_tool("hmb_list_sessions", {})
                        assert not result.isError
                        assert session["id"] in json.dumps(result.model_dump())
            asyncio.run(protocol())
            print("Installed wheel: packaged assets, two independent app tasks, versioned settings with retained media, archive/restore, reviewed Chromium trial, screenshot, and eight-tool MCP history passed")
        finally:
            server.should_exit = True
            worker.join(timeout=5)
            sock.close()


if __name__ == "__main__":
    main()
