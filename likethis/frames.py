"""Bounded local video inspection helpers for HoldMyBeer MCP."""
from __future__ import annotations

import json
import math
import os
import selectors
import subprocess
import time
from pathlib import Path
from uuid import UUID

MAX_FRAMES = 6
MAX_WIDTH = 1280
MAX_HEIGHT = 720
MEDIA_TIMEOUT = 7
MAX_DURATION_SCAN_BYTES = 16 * 1024 * 1024
MAX_DURATION_SCAN_PACKETS = 1_000_000


class FrameError(ValueError):
    """A recording could not be safely inspected."""


def _demuxer_args(media: Path) -> list[str]:
    """Pin parsing to the only containers accepted by the upload route."""
    if media.suffix.lower() == ".webm":
        return ["-f", "matroska"]
    if media.suffix.lower() == ".mp4":
        # MOV external data references can otherwise name other local files.
        return ["-f", "mov", "-enable_drefs", "0", "-use_absolute_path", "0"]
    raise FrameError("unsupported recording format")


def _scan_packet_timing(media: Path) -> tuple[float, float]:
    """Find the final video packet's start/end without buffering ffprobe output."""
    command = [
        "ffprobe", "-protocol_whitelist", "file,pipe", *_demuxer_args(media), "-v", "error", "-select_streams", "v:0",
        "-show_packets", "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", str(media),
    ]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, shell=False, bufsize=0)
    except OSError as exc:
        raise FrameError("ffprobe unavailable") from exc
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + MEDIA_TIMEOUT
    pending = bytearray()
    consumed = 0
    packets = 0
    last_time: float | None = None
    last_pts: float | None = None

    def consume(line: bytes) -> None:
        nonlocal packets, last_time, last_pts
        if not line.strip():
            return
        if len(line) > 1024:
            raise FrameError("recording duration scan returned an oversized packet record")
        fields = line.decode("ascii", errors="ignore").strip().split(",")
        try:
            pts = float(fields[0])
        except (ValueError, IndexError, OverflowError):
            return
        if not math.isfinite(pts):
            return
        packet_duration = 0.0
        if len(fields) > 1:
            try:
                packet_duration = float(fields[1])
            except (ValueError, OverflowError):
                pass
        if not math.isfinite(packet_duration) or packet_duration < 0:
            packet_duration = 0.0
        last_time = max(last_time or 0.0, pts + packet_duration)
        last_pts = max(last_pts or 0.0, pts)
        packets += 1
        if packets > MAX_DURATION_SCAN_PACKETS:
            raise FrameError("recording duration scan exceeded packet limit")

    try:
        os.set_blocking(process.stdout.fileno(), False)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FrameError("ffprobe duration scan timed out")
            events = selector.select(min(remaining, 0.25))
            if not events:
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > MAX_DURATION_SCAN_BYTES:
                raise FrameError("recording duration scan exceeded output limit")
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, tail = pending.partition(b"\n")
                pending = bytearray(tail)
                consume(bytes(line))
            if len(pending) > 1024:
                raise FrameError("recording duration scan returned an oversized packet record")
        if pending:
            consume(bytes(pending))
        remaining = deadline - time.monotonic()
        return_code = process.wait(timeout=max(0.01, remaining))
    except subprocess.TimeoutExpired as exc:
        raise FrameError("ffprobe duration scan timed out") from exc
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
    if return_code or last_time is None or last_pts is None:
        raise FrameError("recording duration is unavailable")
    return last_time, last_pts


def _scan_packet_duration(media: Path) -> float:
    return _scan_packet_timing(media)[0]


def _session_uuid(session_id: str) -> str:
    try:
        return str(UUID(session_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise FrameError("invalid session id") from exc


def _recording(root: Path, session_id: str) -> Path:
    ident = _session_uuid(session_id)
    db_path = root / "holdmybeer.sqlite3"
    if not db_path.is_file():
        raise FrameError("session not found")
    import sqlite3

    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        row = db.execute("SELECT 1 FROM sessions WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise FrameError("session not found")
    artifacts = (root / "artifacts").resolve()
    for suffix in (".webm", ".mp4"):
        candidate = (artifacts / f"{ident}{suffix}").resolve()
        if candidate.parent == artifacts and candidate.is_file():
            return candidate
    raise FrameError("recording not found")


def extract_frames(root: Path, session_id: str, timestamps: list[float]) -> list[tuple[float, bytes]]:
    """Return PNG bytes at requested seconds; work and output are tightly bounded."""
    if not isinstance(timestamps, list) or not 1 <= len(timestamps) <= MAX_FRAMES:
        raise FrameError(f"request between 1 and {MAX_FRAMES} timestamps")
    clean: list[float] = []
    for value in timestamps:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FrameError("timestamps must be numbers")
        try:
            value = float(value)
        except OverflowError as exc:
            raise FrameError("timestamps must be finite numbers") from exc
        if not math.isfinite(value) or value < 0:
            raise FrameError("timestamps must be between 0 and recording duration")
        clean.append(value)

    media = _recording(root.resolve(), session_id)
    try:
        probe = subprocess.run(
            ["ffprobe", "-protocol_whitelist", "file,pipe", *_demuxer_args(media), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(media)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=MEDIA_TIMEOUT, check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrameError("ffprobe unavailable or timed out") from exc
    if probe.returncode:
        raise FrameError("recording could not be read")
    last_seek_time: float | None = None
    try:
        raw_duration = json.loads(probe.stdout).get("format", {}).get("duration")
        duration = float(raw_duration)
    except (ValueError, TypeError, json.JSONDecodeError, OverflowError):
        duration, last_seek_time = _scan_packet_timing(media)
    if not math.isfinite(duration):
        duration, last_seek_time = _scan_packet_timing(media)
    if not (math.isfinite(duration) and duration >= 0 and all(t <= duration for t in clean)):
        raise FrameError(f"timestamps must be between 0 and recording duration ({duration:.3f}s)")

    frames: list[tuple[float, bytes]] = []
    for timestamp in clean:
        seek_timestamp = min(timestamp, last_seek_time) if last_seek_time is not None else timestamp
        try:
            result = subprocess.run(
                ["ffmpeg", "-protocol_whitelist", "file,pipe", *_demuxer_args(media), "-v", "error", "-ss", f"{seek_timestamp:.6f}", "-i", str(media),
                 "-frames:v", "1", "-vf", f"scale=w='min({MAX_WIDTH},iw)':h='min({MAX_HEIGHT},ih)':force_original_aspect_ratio=decrease",
                 "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=MEDIA_TIMEOUT, check=False, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FrameError("ffmpeg unavailable or timed out") from exc
        if result.returncode or not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FrameError(f"could not extract frame at {timestamp:.3f}s")
        frames.append((seek_timestamp, result.stdout))
    return frames
