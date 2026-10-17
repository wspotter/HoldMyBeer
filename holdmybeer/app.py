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

from . import __version__ as VERSION
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


class HybridRunInput(StrictModel):
    dry_run: bool = True
    user_approved_understanding: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    target_dir: str | None = Field(default=None, max_length=1000)
    recipe: dict[str, Any] | None = None


class QuickRecordInput(StrictModel):
    window_title: str | None = Field(default=None, max_length=300)
    file_path: str | None = Field(default=None, max_length=500)
    hint: str | None = Field(default=None, max_length=500)
    app_name: str | None = Field(default=None, max_length=100)
    task_name: str | None = Field(default=None, max_length=200)


class QuickRenameInput(StrictModel):
    task_name: str = Field(min_length=1, max_length=200)
    app_name: str | None = Field(default=None, max_length=100)


class ExportSkillInput(StrictModel):
    output_dir: str | None = Field(default=None, max_length=1000)

class AutoReviewInput(StrictModel):
    window_title: str | None = Field(default=None, max_length=300)
    duration_seconds: float | None = Field(default=None, ge=0.0, le=86400.0)


class AnswerChoicesInput(StrictModel):
    selected_name: str | None = Field(default=None, max_length=200)
    choices: dict[str, str] = Field(default_factory=dict)
    run_sandbox: bool = True






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
                try:
                    procedure = json.loads(row['data'])['procedure']
                    revision = procedure['revision']
                except (KeyError, json.JSONDecodeError):
                    # A legacy session with missing/corrupt procedure data is still
                    # preserved in `sessions` (and stays accessible in the UI); it
                    # simply has no procedure_revisions row to review. Never let one
                    # bad row abort the whole migration.
                    continue
                db.execute('INSERT INTO procedure_revisions VALUES(?,?,?,?,?)',
                           (row['id'], revision, json.dumps(procedure), _now(), 'legacy_current'))

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
        from .training import is_mutable_training_session
        with self.lock, self.connect() as db:
            if not is_mutable_training_session(self, ident):
                raise HTTPException(409, 'This training version is retained. Use Edit task to create a new draft.')
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
            if 'answers' in patch and isinstance(data.get('answers'), dict) and isinstance(patch['answers'], dict):
                data['answers'].update(patch['answers'])
                patch = {k: v for k, v in patch.items() if k != 'answers'}
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
    from .brief_jobs import BriefJobs, brief_router
    app.state.brief_jobs = BriefJobs(app.state.store, app.state.runner_lock)
    app.include_router(brief_router(app.state.brief_jobs))
    from .teaching_review import teaching_router
    app.include_router(teaching_router(app.state.store))
    from .training import training_router
    app.include_router(training_router(app.state.store))

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
        if request.url.path in {"/", "/index.html", "/app.js", "/simple.js", "/training.js", "/directed.js", "/briefs.js", "/style.css"}:
            request.scope["headers"] = [
                (k, v) for (k, v) in request.scope.get("headers", [])
                if k.lower() not in {b"if-none-match", b"if-modified-since"}
            ]
        response = await call_next(request)
        if request.url.path in {"/", "/index.html", "/app.js", "/simple.js", "/training.js", "/directed.js", "/briefs.js", "/style.css"}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/api/status")
    def status(): return {"version": VERSION, "analysis": "manual", "runner": "bundled-browser", "procedure_runner": "reviewed-fixture-actions", "supported_workflows": ["fixture", "github-issue-brief"], "hermes": "mcp-client"}

    @app.get("/api/sessions")
    def list_sessions():
        from .training import training_task_metadata
        with app.state.store.connect() as db:
            sessions = []
            for row in db.execute("SELECT id FROM sessions ORDER BY rowid DESC"):
                data = app.state.store.get_session(row[0])
                data['training_task'] = training_task_metadata(db, row[0])
                sessions.append(data)
            return {"sessions": sessions}

    @app.post("/api/sessions")
    def create_session(body: CreateSession):
        data = {"id": str(uuid.uuid4()), "title": body.title.strip(), "created_at": _now(), "notes": "", "answers": {},
                "procedure": {"revision": 1, "steps": []}, "media_url": None, "runs": []}
        if not data["title"]: raise HTTPException(422, "title cannot be blank")
        app.state.store.save_session(data)
        return data

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        from .training import training_task_metadata
        data = app.state.store.get_session(session_id)
        with app.state.store.connect() as db:
            data['training_task'] = training_task_metadata(db, session_id)
        return data

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
            with app.state.store.lock:
                from .training import is_mutable_training_session
                if not is_mutable_training_session(app.state.store, session_id):
                    raise HTTPException(409, 'This training version is retained. Use Edit task to create a new draft.')
                fresh = app.state.store.get_session(session_id)
                patch = {'media_url': f'/api/sessions/{session_id}/media', 'media_revision': str(uuid.uuid4())}
                if 'teaching_recording_confirmed' in fresh.get('answers', {}):
                    patch['answers'] = {**fresh['answers'], 'teaching_recording_confirmed': 'no'}
                os.replace(temp, target)
                if alternate.parent == app.state.store.artifacts: alternate.unlink(missing_ok=True)
                app.state.store.update_session(session_id, patch)
        finally:
            temp.unlink(missing_ok=True)
        data["media_url"] = f"/api/sessions/{session_id}/media"
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

    @app.put("/api/tasks/{task_id}/hybrid-recipe")
    def put_hybrid_recipe(task_id: str, body: dict[str, Any]):
        from .hybrid import save_hybrid_recipe
        try:
            recipe = save_hybrid_recipe(app.state.store, task_id, body)
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
        return recipe.model_dump()

    @app.get("/api/tasks/{task_id}/hybrid-recipe")
    def get_task_hybrid_recipe(task_id: str):
        from .hybrid import resolve_task_or_session_recipe
        try:
            recipe = resolve_task_or_session_recipe(app.state.store, task_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return recipe.model_dump()

    @app.post("/api/tasks/{task_id}/hybrid-run")
    def run_task_hybrid(task_id: str, body: HybridRunInput | None = None):
        from .hybrid import HybridRecipe, resolve_task_or_session_recipe
        from .runner import execute_hybrid
        payload = body or HybridRunInput()
        if not payload.dry_run and not payload.user_approved_understanding:
            raise HTTPException(
                409,
                "Real execution requires dry_run=false and explicit user_approved_understanding=true.",
            )
        try:
            if payload.recipe is not None:
                recipe = HybridRecipe.model_validate({**payload.recipe, "task_id": str(task_id)})
            else:
                recipe = resolve_task_or_session_recipe(app.state.store, task_id)
            return execute_hybrid(
                recipe=recipe,
                parameters=payload.parameters,
                target_dir=payload.target_dir,
                dry_run=payload.dry_run,
                user_approved_understanding=payload.user_approved_understanding,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/quick-record")
    def quick_record(body: QuickRecordInput | None = None):
        from .hybrid import infer_quick_record_metadata, resolve_task_or_session_recipe
        payload = body or QuickRecordInput()
        with app.state.store.lock:
            now = _now()
            with app.state.store.connect() as db:
                row_count = db.execute("SELECT COUNT(*) FROM training_tasks").fetchone()[0]
                inferred = infer_quick_record_metadata(
                    window_title=payload.window_title,
                    file_path=payload.file_path,
                    hint=payload.hint,
                    app_name=payload.app_name,
                    task_name=payload.task_name,
                    existing_count=row_count,
                )
                app_name = inferred["app_name"]
                base_task_name = inferred["task_name"]

                app_row = db.execute("SELECT id, name FROM training_apps WHERE name=?", (app_name,)).fetchone()
                if app_row is not None:
                    aid = app_row["id"]
                else:
                    aid = str(uuid.uuid4())
                    db.execute("INSERT INTO training_apps VALUES(?,?,?)", (aid, app_name, now))

                final_task_name = base_task_name
                suffix_num = 2
                while db.execute(
                    "SELECT 1 FROM training_tasks WHERE app_id=? AND name=?",
                    (aid, final_task_name),
                ).fetchone():
                    final_task_name = f"{base_task_name} #{suffix_num}"
                    suffix_num += 1

                tid = str(uuid.uuid4())
                sid = str(uuid.uuid4())
                session_data = {
                    "id": sid,
                    "title": f"Training · {final_task_name}",
                    "created_at": now,
                    "notes": "",
                    "answers": {
                        "teaching_task_name": final_task_name,
                        "teaching_goal": "",
                        "teaching_done": "",
                        "teaching_recording_confirmed": "no",
                    },
                    "procedure": {"revision": 1, "steps": []},
                    "media_url": None,
                    "runs": [],
                }
                db.execute("INSERT INTO sessions(id,data) VALUES(?,?)", (sid, json.dumps(session_data)))
                db.execute(
                    "INSERT INTO procedure_revisions VALUES(?,?,?,?,?)",
                    (sid, 1, json.dumps(session_data["procedure"]), now, "saved"),
                )
                db.execute(
                    "INSERT INTO training_tasks VALUES(?,?,?,?,?,?)",
                    (tid, aid, final_task_name, 1, None, now),
                )
                db.execute(
                    "INSERT INTO training_versions VALUES(?,?,?,?,?)",
                    (tid, 1, sid, now, None),
                )

            recipe = resolve_task_or_session_recipe(app.state.store, tid)
            card = recipe.to_recipe_card()
            session_with_ctx = {**session_data, "training": {"version": 1}}
            task_detail = {
                "id": tid,
                "app_id": aid,
                "app_name": app_name,
                "name": final_task_name,
                "description": "",
                "latest_version": 1,
                "working_version": None,
                "versions": [
                    {
                        "version": 1,
                        "session_id": sid,
                        "created_at": now,
                        "parent_version": None,
                        "status": "draft",
                    }
                ],
                "session": session_with_ctx,
            }
            return {
                "task_id": tid,
                "app_id": aid,
                "app_name": app_name,
                "task_name": final_task_name,
                "session_id": sid,
                "session": session_with_ctx,
                "task": task_detail,
                "inferred": {**inferred, "task_name": final_task_name},
                "recipe_card": card,
            }

    @app.put("/api/tasks/{task_id}/quick-rename")
    def quick_rename_task(task_id: str, body: QuickRenameInput):
        from .hybrid import get_hybrid_recipe, resolve_task_or_session_recipe, save_hybrid_recipe
        new_name = body.task_name.strip()
        if not new_name:
            raise HTTPException(422, "task_name cannot be blank")
        with app.state.store.lock:
            with app.state.store.connect() as db:
                task_row = db.execute("SELECT * FROM training_tasks WHERE id=?", (str(task_id),)).fetchone()
                if task_row is not None:
                    db.execute("UPDATE training_tasks SET name=? WHERE id=?", (new_name, str(task_id)))
                    vrow = db.execute(
                        "SELECT session_id FROM training_versions WHERE task_id=? AND version=?",
                        (str(task_id), task_row["latest_version"]),
                    ).fetchone()
                    sid = vrow["session_id"] if vrow else None
                else:
                    sid = str(task_id)
                if sid:
                    srow = db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
                    if srow:
                        sdata = json.loads(srow["data"])
                        sdata["title"] = f"Training · {new_name}"
                        sdata.setdefault("answers", {})["teaching_task_name"] = new_name
                        db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(sdata), sid))
            existing_recipe = get_hybrid_recipe(app.state.store, task_id)
            if existing_recipe is not None:
                save_hybrid_recipe(app.state.store, task_id, existing_recipe.model_copy(update={"title": new_name}))
            recipe = resolve_task_or_session_recipe(app.state.store, task_id)
            return {
                "task_id": str(task_id),
                "task_name": new_name,
                "recipe_card": recipe.to_recipe_card(),
            }

    @app.get("/api/tasks/{task_id}/recipe-card")
    def get_task_recipe_card(task_id: str):
        from .hybrid import resolve_task_or_session_recipe
        try:
            recipe = resolve_task_or_session_recipe(app.state.store, task_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return recipe.to_recipe_card()

    @app.post("/api/tasks/{task_id}/export-skill")
    def post_export_skill(task_id: str, body: ExportSkillInput | None = None):
        from .hybrid import export_skill_bundle, resolve_task_or_session_recipe
        payload = body or ExportSkillInput()
        try:
            recipe = resolve_task_or_session_recipe(app.state.store, task_id)
            out_dir = Path(payload.output_dir) if payload.output_dir else (app.state.store.artifacts / "skills")
            return export_skill_bundle(recipe, out_dir)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/tools/openai")
    def get_openai_tools():
        from .hybrid import list_hybrid_recipes, resolve_task_or_session_recipe
        recipes = list(list_hybrid_recipes(app.state.store))
        seen_tasks = {r.task_id for r in recipes}
        with app.state.store.connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "training_tasks" in tables:
                for row in db.execute("SELECT id FROM training_tasks ORDER BY created_at DESC, id"):
                    tid = row["id"]
                    if tid not in seen_tasks:
                        try:
                            recipes.append(resolve_task_or_session_recipe(app.state.store, tid))
                            seen_tasks.add(tid)
                        except LookupError:
                            pass
        tools = []
        seen_names = set()
        for r in recipes:
            tool = r.to_openai_tool()
            fname = tool["function"]["name"]
            if fname not in seen_names:
                seen_names.add(fname)
                tools.append(tool)
        return {"tools": tools, "count": len(tools)}


    @app.post("/api/sessions/{session_id}/auto-review")
    def post_session_auto_review(session_id: uuid.UUID, body: AutoReviewInput | None = None):
        from .hybrid import generate_auto_review
        payload = body or AutoReviewInput()
        try:
            return generate_auto_review(
                app.state.store,
                str(session_id),
                window_title=payload.window_title,
                duration_seconds=payload.duration_seconds,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/sessions/{session_id}/answer-choices")
    def post_session_answer_choices(session_id: uuid.UUID, body: AnswerChoicesInput | None = None):
        from .hybrid import apply_multiple_choice_answers
        payload = body or AnswerChoicesInput()
        try:
            return apply_multiple_choice_answers(
                app.state.store,
                str(session_id),
                selected_name=payload.selected_name,
                choices=payload.choices,
                run_sandbox=payload.run_sandbox,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc


    @app.post("/api/native-record/start")
    def post_native_record_start():
        from .hybrid import start_native_recording
        return start_native_recording(app.state.store)

    @app.post("/api/native-record/{session_id}/stop")
    def post_native_record_stop(session_id: uuid.UUID):
        from .hybrid import stop_native_recording
        try:
            return stop_native_recording(app.state.store, str(session_id))
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/universal-agents")
    @app.get("/api/agents/detect")
    def get_universal_agents():
        from .hybrid import detect_universal_agents
        return detect_universal_agents(data_dir=app.state.store.root)

    web_dir = _ASSET_DIR
    if web_dir.is_dir() and any(web_dir.iterdir()): app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
