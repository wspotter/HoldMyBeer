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
        from holdmybeer.app import create_app
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
            for path in ("/", "/app.js", "/style.css", "/fixture"):
                assert httpx.get(base + path).status_code == 200, path
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
                params = StdioServerParameters(command=sys.executable, args=["-m", "holdmybeer.mcp_server"], env=dict(os.environ))
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
            print("Installed wheel: web assets, reviewed Chromium trial, retained screenshot and eight-tool MCP handshake with procedure history passed")
        finally:
            server.should_exit = True
            worker.join(timeout=5)
            sock.close()


if __name__ == "__main__":
    main()
