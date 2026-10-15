from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

VERSION = "0.2.0a1"
MAX_MEDIA_BYTES = 100 * 1024 * 1024
DATA_DIR = Path(os.environ.get("HMB_DATA_DIR", "~/.local/share/holdmybeer")).expanduser().resolve()
_ASSET_DIR = Path(__file__).resolve().parent / "web"
if not _ASSET_DIR.is_dir():
    _ASSET_DIR = Path(__file__).resolve().parent.parent / "web"
FIXTURE_HTML = (_ASSET_DIR / "fixture.html").read_text()


from .models import StrictModel, CreateSession, Procedure
from .revisions import read_revisions


class UpdateSession(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=20_000)
    answers: dict[str, str] | None = Field(default=None, max_length=50)
    procedure: Procedure | None = None

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, answers):
        if answers is not None and any(not key.strip() or len(key) > 100 or len(value) > (4000 if key in {"agent_observations", "agent_questions"} else 2000) for key, value in answers.items()):
            raise ValueError("answer keys must be 1-100 characters and values at most 2000 characters (4000 for agent observation/question bundles)")
        return answers


class RunInput(StrictModel):
    caption: str | None = Field(default=None, min_length=1, max_length=2000)
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    variant: str = Field(default="normal", pattern="^(normal|changed)$")
    repair: bool = False
    mode: Literal["practice", "procedure"] = "practice"
    media_mode: Literal["new", "reuse"] = "new"
    existing_draft_id: uuid.UUID | None = None
    items: list["RunItem"] | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_run_shape(self):
        if self.items is None:
            if self.caption is None:
                raise ValueError("caption is required")
            if self.media_mode == "new" and self.filename is None:
                raise ValueError("filename is required for new media")
            if self.media_mode == "reuse" and self.existing_draft_id is None:
                raise ValueError("existing_draft_id is required for reused media")
            if self.media_mode == "reuse" and self.filename is not None:
                raise ValueError("filename is derived from the retained draft when media is reused")
            if self.media_mode == "new" and self.existing_draft_id is not None:
                raise ValueError("existing_draft_id is only valid for reused media")
        elif self.caption is not None or self.filename is not None or self.existing_draft_id is not None or self.media_mode != "new":
            raise ValueError("batch items carry their own caption and media selection")
        return self


class RunItem(StrictModel):
    caption: str = Field(min_length=1, max_length=2000)
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    media_mode: Literal["new", "reuse"] = "new"
    existing_draft_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_media_selection(self):
        if self.media_mode == "new" and (self.filename is None or self.existing_draft_id is not None):
            raise ValueError("new media requires filename and cannot include existing_draft_id")
        if self.media_mode == "reuse" and self.existing_draft_id is None:
            raise ValueError("reused media requires existing_draft_id")
        if self.media_mode == "reuse" and self.filename is not None:
            raise ValueError("filename is derived from the retained draft when media is reused")
        return self



class DraftInput(StrictModel):
    caption: str = Field(min_length=1, max_length=2000)
    filename: str = Field(min_length=1, max_length=255)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(value: str) -> str:
    if value in {".", ".."} or Path(value).name != value or "\x00" in value:
        raise HTTPException(422, "filename must be a plain filename")
    return value


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.artifacts = (root / "artifacts").resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = root / "holdmybeer.sqlite3"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS procedure_revisions(
                session_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
                saved_at TEXT NOT NULL, source TEXT NOT NULL,
                PRIMARY KEY(session_id, revision));
            """)
            db.execute('BEGIN IMMEDIATE')
            # Preserve only the current known legacy revision; earlier overwrites
            # cannot be reconstructed safely from revision numbers alone.
            for row in db.execute('''SELECT id,data FROM sessions s WHERE NOT EXISTS
                (SELECT 1 FROM procedure_revisions p WHERE p.session_id=s.id)''').fetchall():
                procedure = json.loads(row['data'])['procedure']
                db.execute('INSERT INTO procedure_revisions VALUES(?,?,?,?,?)',
                           (row['id'], procedure['revision'], json.dumps(procedure), _now(), 'legacy_current'))

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def get_session(self, ident: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM sessions WHERE id=?", (ident,)).fetchone()
        if not row: raise HTTPException(404, "session not found")
        data = json.loads(row[0])
        with self.connect() as db:
            data["runs"] = [json.loads(r[0]) for r in db.execute("SELECT data FROM runs WHERE session_id=? ORDER BY rowid", (ident,))]
        return data

    def save_session(self, data: dict):
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id,data) VALUES(?,?)", (data["id"], json.dumps(data)))
            procedure = data['procedure']
            db.execute('INSERT INTO procedure_revisions VALUES(?,?,?,?,?)',
                       (data['id'], procedure['revision'], json.dumps(procedure), _now(), 'saved'))

    def update_session(self, ident: str, patch: dict):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM sessions WHERE id=?', (ident,)).fetchone()
            if row is None:
                raise HTTPException(404, 'session not found')
            data = json.loads(row[0])
            if 'procedure' in patch:
                current = Procedure.model_validate(data['procedure']).model_dump(exclude_none=True)
                proposed = Procedure.model_validate(patch['procedure']).model_dump(exclude_none=True)
                number = proposed['revision']
                if number == current['revision'] and proposed == current:
                    pass  # Retrying an identical save must not duplicate history.
                elif number == current['revision'] + 1:
                    db.execute('INSERT INTO procedure_revisions VALUES(?,?,?,?,?)',
                               (ident, number, json.dumps(proposed), _now(), 'saved'))
                else:
                    raise HTTPException(409, f"Procedure changed or revision is invalid. Current revision is {current['revision']}; reload before editing and save changes as revision {current['revision'] + 1}.")
                patch = {**patch, 'procedure': proposed}
            data.update(patch)
            db.execute('UPDATE sessions SET data=? WHERE id=?', (json.dumps(data), ident))

    def save_run(self, sid: str, data: dict):
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,session_id,data) VALUES(?,?,?)", (data["id"], sid, json.dumps(data)))

    def save_draft(self, data: dict):
        with self.connect() as db:
            db.execute("INSERT INTO drafts(id,data) VALUES(?,?)", (data["id"], json.dumps(data)))

    def drafts(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM drafts ORDER BY rowid")]

    def get_draft(self, ident: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM drafts WHERE id=?", (ident,)).fetchone()
        return json.loads(row[0]) if row else None


def create_app(data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="HoldMyBeer", docs_url=None, redoc_url=None)
    app.state.store = Store((data_dir or DATA_DIR).resolve())
    app.state.runner_lock = threading.Lock()

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host_header = request.headers.get("host", "")
        host = (urlsplit("//" + host_header).hostname or "").lower()
        if host not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            return Response("local Host required", status_code=400)
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            request_url = request.url
            try:
                origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                request_port = request_url.port or (443 if request_url.scheme == "https" else 80)
            except ValueError:
                return Response("invalid Origin or Host", status_code=403)
            if (parsed.scheme != request_url.scheme or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or parsed.hostname != (request_url.hostname or "").lower() or origin_port != request_port
                    or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                return Response("foreign Origin rejected", status_code=403)
        peer = request.client.host if request.client else "127.0.0.1"
        if peer not in {"127.0.0.1", "::1", "testclient"}:
            return Response("loopback clients only", status_code=403)
        return await call_next(request)

    @app.get("/api/status")
    def status(): return {"version": VERSION, "analysis": "manual", "runner": "bundled-browser", "procedure_runner": "reviewed-fixture-actions", "hermes": "scaffold"}

    @app.get("/api/sessions")
    def list_sessions():
        with app.state.store.connect() as db:
            return {"sessions": [app.state.store.get_session(r[0]) for r in db.execute("SELECT id FROM sessions ORDER BY rowid DESC")]}

    @app.post("/api/sessions")
    def create_session(body: CreateSession):
        data = {"id": str(uuid.uuid4()), "title": body.title.strip(), "created_at": _now(), "notes": "", "answers": {},
                "procedure": {"revision": 1, "steps": []}, "media_url": None, "runs": []}
        if not data["title"]: raise HTTPException(422, "title cannot be blank")
        app.state.store.save_session(data)
        return data

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str): return app.state.store.get_session(session_id)

    def procedure_history(session_id, revision=None, before_revision=None):
        with app.state.store.connect() as db:
            try:
                return read_revisions(db, session_id, revision, before_revision)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc

    @app.get('/api/sessions/{session_id}/procedure-revisions')
    def list_procedure_revisions(session_id: str, before_revision: int | None = Query(default=None, ge=1)):
        return procedure_history(session_id, before_revision=before_revision)

    @app.get('/api/sessions/{session_id}/procedure-revisions/{revision}')
    def get_procedure_revision(session_id: str, revision: int):
        return procedure_history(session_id, revision=revision) if revision > 0 else Response(status_code=404)

    @app.get("/api/sessions/{session_id}/proposal")
    def get_proposal(session_id: str):
        app.state.store.get_session(session_id)
        from .proposals import latest_proposal
        return {"proposal": latest_proposal(app.state.store.root, session_id)}

    @app.put("/api/sessions/{session_id}")
    def update_session(session_id: str, body: UpdateSession):
        patch = body.model_dump(exclude_unset=True, exclude_none=True)
        app.state.store.update_session(session_id, patch)
        return app.state.store.get_session(session_id)

    @app.post("/api/sessions/{session_id}/media")
    async def upload_media(session_id: str, request: Request):
        data = app.state.store.get_session(session_id)
        ctype = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if ctype not in {"video/webm", "video/mp4"}: raise HTTPException(415, "video/webm or video/mp4 required")
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_MEDIA_BYTES): raise HTTPException(413, "media too large")
        suffix = ".mp4" if ctype == "video/mp4" else ".webm"
        target = (app.state.store.artifacts / (session_id + suffix)).resolve()
        if target.parent != app.state.store.artifacts: raise HTTPException(400, "unsafe media path")
        alternate = (app.state.store.artifacts / (session_id + (".webm" if suffix == ".mp4" else ".mp4"))).resolve()
        fd, temp_name = tempfile.mkstemp(prefix=f".{session_id}.", suffix=".upload", dir=app.state.store.artifacts)
        temp = Path(temp_name)
        total = 0
        try:
            with os.fdopen(fd, "wb") as out:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_MEDIA_BYTES: raise HTTPException(413, "media too large")
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if total == 0: raise HTTPException(422, "empty media")
            os.replace(temp, target)
            if alternate.parent == app.state.store.artifacts: alternate.unlink(missing_ok=True)
        finally:
            temp.unlink(missing_ok=True)
        data["media_url"] = f"/api/sessions/{session_id}/media"
        app.state.store.update_session(session_id, {'media_url': data['media_url']})
        return {"url": data["media_url"]}

    @app.get("/api/sessions/{session_id}/media")
    def get_media(session_id: str):
        app.state.store.get_session(session_id)
        candidates = [(app.state.store.artifacts / (session_id + ext)).resolve() for ext in (".webm", ".mp4")]
        target = next((p for p in candidates if p.parent == app.state.store.artifacts and p.is_file()), None)
        if target is None: raise HTTPException(404, "media not found")
        return FileResponse(target, media_type="video/mp4" if target.suffix == ".mp4" else "video/webm")

    @app.get("/fixture", response_class=HTMLResponse)
    def fixture(): return FIXTURE_HTML

    @app.post("/api/fixture/drafts")
    def create_draft(body: DraftInput):
        filename = _safe_filename(body.filename)
        data = {"id": str(uuid.uuid4()), "caption": body.caption, "filename": filename}
        app.state.store.save_draft(data)
        return data

    @app.get("/api/fixture/drafts")
    def list_drafts(): return {"drafts": app.state.store.drafts()}

    @app.get("/api/artifacts/{run_id}.png")
    def screenshot(run_id: str):
        if not re.fullmatch(r"[0-9a-f-]{36}", run_id): raise HTTPException(404, "artifact not found")
        path = (app.state.store.artifacts / f"{run_id}.png").resolve()
        if path.parent != app.state.store.artifacts or not path.is_file(): raise HTTPException(404, "artifact not found")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/sessions/{session_id}/run")
    def run_session(session_id: str, body: RunInput, request: Request):
        session = app.state.store.get_session(session_id)
        procedure = session.get("procedure", {})
        if body.mode == "procedure":
            steps = procedure.get("steps", [])
            actions = [step.get("action") for step in steps]
            allowed = (["upload", "fill", "click", "verify_draft"], ["select_media", "fill", "click", "verify_draft"])
            if len(steps) != 4 or actions not in allowed:
                raise HTTPException(422, "procedure mode requires select_media or upload, fill, click, verify_draft actions in order")
        items = body.items or [RunItem(caption=body.caption, filename=body.filename, media_mode=body.media_mode, existing_draft_id=body.existing_draft_id)]
        resolved = []
        for item in items:
            if item.media_mode == "reuse":
                retained = app.state.store.get_draft(str(item.existing_draft_id))
                if retained is None:
                    raise HTTPException(404, "existing draft not found")
                filename = _safe_filename(retained["filename"])
            else:
                filename = _safe_filename(item.filename)
            resolved.append((item, filename))
        if body.mode == "procedure" and any(item.media_mode == "reuse" for item, _ in resolved) and procedure.get("steps", [{}])[0].get("action") == "upload":
            raise HTTPException(422, "reused media requires select_media as the first procedure action")
        if not app.state.runner_lock.acquire(blocking=False):
            raise HTTPException(429, "a browser run is already active")
        try:
            runs = []
            for item, filename in resolved:
                run = _execute_run(app, request, session, procedure, body, item.caption, filename,
                                   item.media_mode, item.existing_draft_id)
                app.state.store.save_run(session_id, run)
                runs.append(run)
                if run["status"] != "verified":
                    break
        finally:
            app.state.runner_lock.release()
        if body.items:
            return {"status": "verified" if len(runs) == len(resolved) and all(r["status"] == "verified" for r in runs) else "failed",
                    "runs": runs, "completed": len(runs), "attempted": len(runs),
                    "verified_count": sum(r["status"] == "verified" for r in runs), "requested": len(resolved),
                    "stopped_on_failure": len(runs) < len(resolved) or any(r["status"] != "verified" for r in runs)}
        return runs[0]

    def _execute_run(app, request, session, procedure, body, caption, filename, media_mode, existing_draft_id):
        run_id = str(uuid.uuid4())
        run = {"id": run_id, "status": "failed", "revision": session["procedure"]["revision"], "caption": caption,
               "filename": filename, "media_mode": media_mode,
               "existing_draft_id": str(existing_draft_id) if existing_draft_id else None,
               "mode": body.mode, "procedure": json.loads(json.dumps(procedure)) if body.mode == "procedure" else None,
               "steps": [], "failure": None, "screenshot_url": None, "draft_id": None,
               "inputs": {"caption": caption, "filename": filename, "media_mode": media_mode,
                          "existing_draft_id": str(existing_draft_id) if existing_draft_id else None,
                          "variant": body.variant, "repair": body.repair, "mode": body.mode}}
        try:
            from .runner import execute
            result = execute(f"http://127.0.0.1:{request.scope['server'][1]}", app.state.store.artifacts, run_id,
                             caption, filename, body.variant, body.repair, body.mode,
                             procedure if body.mode == "procedure" else None, media_mode)
            run.update(result)
        except Exception as exc:
            run["failure"] = (str(exc) or type(exc).__name__)[:500]
        return run

    @app.get("/api/sessions/{session_id}/runs/{run_id}")
    def get_run(session_id: str, run_id: str):
        session = app.state.store.get_session(session_id)
        for run in session["runs"]:
            if run["id"] == run_id: return run
        raise HTTPException(404, "run not found")

    web_dir = _ASSET_DIR
    if web_dir.is_dir() and any(web_dir.iterdir()): app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
