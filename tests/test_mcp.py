import json
import os
import sqlite3
import subprocess
import sys
import uuid

import pytest

from holdmybeer.frames import MEDIA_TIMEOUT, FrameError, _scan_packet_duration, extract_frames
from holdmybeer.mcp_server import hmb_get_session, hmb_list_sessions, hmb_recording_frames


@pytest.fixture
def recording_store(tmp_path, monkeypatch):
    root = tmp_path / "data"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    sid = str(uuid.uuid4())
    db = sqlite3.connect(root / "holdmybeer.sqlite3")
    db.executescript("CREATE TABLE sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL); CREATE TABLE runs(id TEXT PRIMARY KEY,session_id TEXT,data TEXT NOT NULL);")
    db.execute("INSERT INTO sessions VALUES (?,?)", (sid, json.dumps({"id": sid, "title": "local test", "created_at": "today", "notes": "untrusted", "media_url": "/media", "procedure": {"revision": 1, "steps": []}})))
    db.commit()
    db.close()
    from holdmybeer.app import Store
    Store(root)
    video = artifacts / f"{sid}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=1600x900:d=1", "-an", "-c:v", "mpeg4", "-y", str(video)], check=True, timeout=15, shell=False)
    monkeypatch.setenv("HMB_DATA_DIR", str(root))
    return root, sid, video


def test_session_tools_read_from_local_store(recording_store):
    _, sid, _ = recording_store
    listing = hmb_list_sessions()
    assert listing["sessions"][0]["id"] == sid
    assert listing["sessions"][0]["training_task"] is None
    session = hmb_get_session(sid)
    assert session["notes"] == "untrusted"
    assert session["training_task"] is None
    with pytest.raises(ValueError, match="session not found"):
        hmb_get_session(str(uuid.uuid4()))


def test_session_tools_identify_same_named_tasks_by_app_and_version(recording_store):
    root, legacy_sid, _ = recording_store
    from fastapi.testclient import TestClient
    from holdmybeer.app import create_app

    client = TestClient(create_app(root))
    app_a = client.post("/api/training/apps", json={"name": "Alpha"}).json()
    app_b = client.post("/api/training/apps", json={"name": "Beta"}).json()
    body = {"name": "Same task", "description": "Save the requested item", "done": "Receipt matches"}
    task_a = client.post(f"/api/training/apps/{app_a['id']}/tasks", json=body).json()
    task_b = client.post(f"/api/training/apps/{app_b['id']}/tasks", json=body).json()
    v1_a = task_a["session"]["id"]
    v1_b = task_b["session"]["id"]
    edited = client.post(f"/api/training/tasks/{task_a['id']}/edit", json={"base_version": 1}).json()
    v2_a = edited["session"]["id"]
    latest_answers = {**edited["session"]["answers"], "teaching_task_name": "Renamed task"}
    assert client.put(f"/api/sessions/{v2_a}", json={"title": "Renamed task", "answers": latest_answers}).status_code == 200

    listing = {item["id"]: item for item in hmb_list_sessions()["sessions"]}
    first_version = listing[v1_a]["training_task"]
    second_task = listing[v1_b]["training_task"]
    latest_version = hmb_get_session(v2_a)["training_task"]
    assert first_version == {"app_id": app_a["id"], "app_name": "Alpha", "task_id": task_a["id"],
                             "task_name": "Renamed task", "version": 1, "latest_version": 2,
                             "working_version": None}
    assert second_task["app_id"] == app_b["id"]
    assert second_task["app_name"] == "Beta"
    assert second_task["task_id"] == task_b["id"]
    assert second_task["task_name"] == "Same task"
    assert second_task["version"] == second_task["latest_version"] == 1
    assert latest_version == {"app_id": app_a["id"], "app_name": "Alpha", "task_id": task_a["id"],
                              "task_name": "Renamed task", "version": 2, "latest_version": 2,
                              "working_version": None}
    assert hmb_get_session(legacy_sid)["training_task"] is None


def test_frame_tool_extracts_png_at_bounded_dimensions(recording_store):
    root, sid, _ = recording_store
    frames = extract_frames(root, sid, [0.25, 0.75])
    assert len(frames) == 2
    assert all(data.startswith(b"\x89PNG\r\n\x1a\n") for _, data in frames)
    # PNG IHDR width and height are the first two 32-bit integers after the signature.
    import struct
    width, height = struct.unpack(">II", frames[0][1][16:24])
    assert width <= 1280
    assert 0 < height <= 720
    content = hmb_recording_frames(sid, [0.5])
    assert content[0].startswith("Frame at 0.500 seconds")
    assert content[1]._mime_type == "image/png"
    assert content[1].data.startswith(b"\x89PNG\r\n\x1a\n")


def test_frame_requests_are_limited_to_existing_local_media(recording_store):
    root, sid, video = recording_store
    with pytest.raises(FrameError, match="between 1 and 6"):
        extract_frames(root, sid, [0] * 7)
    with pytest.raises(FrameError, match="duration"):
        extract_frames(root, sid, [5])
    for invalid in (float("nan"), float("inf"), float("-inf"), -0.1, 1e308, 10 ** 1000):
        with pytest.raises(FrameError, match="timestamps"):
            extract_frames(root, sid, [invalid])
    with pytest.raises(FrameError, match="invalid session"):
        extract_frames(root, "../../etc/passwd", [0])
    video.unlink()
    with pytest.raises(FrameError, match="recording not found"):
        extract_frames(root, sid, [0])


def test_frame_tool_rejects_outside_symlink_and_invalid_video(recording_store, tmp_path):
    assert MEDIA_TIMEOUT <= 7
    root, sid, video = recording_store
    external = tmp_path / "outside.mp4"
    external.write_bytes(video.read_bytes())
    video.unlink()
    video.symlink_to(external)
    with pytest.raises(FrameError, match="recording not found"):
        extract_frames(root, sid, [0])
    video.unlink()
    video.write_bytes(b"not a recording")
    with pytest.raises(FrameError, match="recording could not be read"):
        extract_frames(root, sid, [0])


def test_disguised_concat_playlist_cannot_read_other_local_video(recording_store, tmp_path):
    root, sid, video = recording_store
    external = tmp_path / "private.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=320x180:d=1",
         "-an", "-c:v", "mpeg4", "-y", str(external)],
        check=True, timeout=15, shell=False,
    )
    video.write_text(f"ffconcat version 1.0\nfile '{external}'\n", encoding="utf-8")
    with pytest.raises(FrameError):
        extract_frames(root, sid, [0])


def test_live_mediasource_webm_without_format_duration_extracts_frames(recording_store):
    root, sid, _ = recording_store
    video = root / "artifacts" / f"{sid}.webm"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=10",
         "-t", "1.2", "-an", "-c:v", "libvpx", "-f", "webm", "-live", "1", "-y", str(video)],
        check=True, timeout=15, shell=False,
    )
    assert _scan_packet_duration(video) == pytest.approx(1.2, abs=0.001)
    # The live WebM muxer leaves format.duration unset, as MediaRecorder does.
    frames = extract_frames(root, sid, [0.5, 1.15])
    assert [timestamp for timestamp, _ in frames] == [0.5, 1.1]
    assert all(data.startswith(b"\x89PNG\r\n\x1a\n") for _, data in frames)


def test_stdio_mcp_lists_tools_and_returns_image_content(recording_store):
    import anyio
    from mcp import ClientSession, types
    from mcp.client.stdio import StdioServerParameters, stdio_client

    root, sid, _ = recording_store

    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "holdmybeer.mcp_server"],
            env={**os.environ, "HMB_DATA_DIR": str(root)},
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "hmb_list_sessions", "hmb_get_session", "hmb_recording_frames", "hmb_propose_teaching", "hmb_procedure_history",
                    "hmb_propose_issue_brief", "hmb_execute_approved_brief", "hmb_get_issue_brief"
                }
                annotations = {tool.name: tool.annotations for tool in tools.tools}
                assert annotations["hmb_recording_frames"].readOnlyHint is True
                assert annotations["hmb_procedure_history"].readOnlyHint is True
                assert annotations["hmb_propose_teaching"].readOnlyHint is False
                assert all(item.destructiveHint is False for item in annotations.values())
                assert annotations["hmb_execute_approved_brief"].openWorldHint is True
                assert annotations["hmb_execute_approved_brief"].idempotentHint is True
                assert all(item.openWorldHint is False for name, item in annotations.items() if name != "hmb_execute_approved_brief")
                history = await client.call_tool('hmb_procedure_history', {'session_id': sid, 'revision': 1})
                assert not history.isError
                assert json.loads(history.content[0].text)['procedure'] == {'revision': 1, 'steps': []}
                result = await client.call_tool("hmb_recording_frames", {"session_id": sid, "timestamps": [0.5]})
                assert any(isinstance(block, types.ImageContent) and block.mimeType == "image/png" for block in result.content)
                proposal = await client.call_tool("hmb_propose_teaching", {
                    "session_id": sid,
                    "observations": [{"timestamp": 0.5, "text": "Save button appears below the form."}],
                    "questions": [],
                    "procedure": {"revision": 1, "steps": [
                        {"goal": "Upload media", "check": "Filename appears", "action": "upload", "target": "media-input", "input": "filename"},
                        {"goal": "Enter caption", "check": "Caption appears", "action": "fill", "target": "caption-input", "input": "caption"},
                        {"goal": "Save draft", "check": "Draft is saved", "action": "click", "target": "save-draft"},
                        {"goal": "Verify saved draft", "check": "Draft id appears", "action": "verify_draft"},
                    ]},
                })
                assert not proposal.isError
                assert json.loads(proposal.content[0].text)["review_required"] is True

    anyio.run(exercise)
