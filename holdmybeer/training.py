"""App/task organization and isolated, versioned training sessions."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator

from .models import Procedure, StrictModel
from .proposals import latest_proposal, teaching_source


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attach_recording_as_next_version(store, session_id: str, target_task_id: str) -> int:
    """Attach a fresh, single-version recording to an existing task atomically."""
    sid, target_id = str(session_id), str(target_task_id)
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        source = db.execute(
            "SELECT task_id, version FROM training_versions WHERE session_id=?", (sid,)
        ).fetchone()
        target = db.execute("SELECT * FROM training_tasks WHERE id=?", (target_id,)).fetchone()
        if source is None or target is None:
            raise ValueError("recording or target task no longer exists")
        if target["archived_at"] is not None:
            raise HTTPException(409, "target task is archived; restore it before adding a recording")
        source_id = source["task_id"]
        if source_id == target_id:
            return int(target["latest_version"])

        source_task = db.execute("SELECT * FROM training_tasks WHERE id=?", (source_id,)).fetchone()
        if source_task is not None and source_task["archived_at"] is not None:
            raise HTTPException(409, "source task is archived; restore it before renaming or merging")
        source_versions = db.execute(
            "SELECT version FROM training_versions WHERE task_id=? ORDER BY version", (source_id,)
        ).fetchall()
        if (source_task is None or source_task["working_version"] is not None or len(source_versions) != 1
                or source["version"] != source_task["latest_version"]):
            raise ValueError("only a fresh, unbranched, non-working recording can be added to another task")
        current_head = db.execute(
            "SELECT 1 FROM training_versions WHERE task_id=? AND version=?",
            (target_id, target["latest_version"]),
        ).fetchone()
        if current_head is None:
            raise ValueError("target task history has no current head")

        next_version = int(target["latest_version"]) + 1
        db.execute(
            "UPDATE training_versions SET task_id=?, version=?, parent_version=? "
            "WHERE task_id=? AND version=? AND session_id=?",
            (target_id, next_version, target["latest_version"], source_id, source["version"], sid),
        )
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hybrid_recipes'"
        ).fetchone():
            db.execute("DELETE FROM hybrid_recipes WHERE task_id=?", (source_id,))
        db.execute("DELETE FROM training_tasks WHERE id=?", (source_id,))
        db.execute("UPDATE training_tasks SET latest_version=? WHERE id=?", (next_version, target_id))
        return next_version


class AppInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


class TaskInput(StrictModel):
    # The task name is an organizational label only; intent is inferred later from
    # a real recording, so description/done are optional here and become legacy
    # notes for previously recorded tasks rather than pre-recorded intent.
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    done: str = Field(default="", max_length=1000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("task name cannot be blank")
        return value.strip()

    @field_validator("description", "done")
    @classmethod
    def clean_optional(cls, value):
        # Empty is allowed; a name-only task starts in the pending-intent state.
        return "" if value is None else value.strip()


class VersionInput(StrictModel):
    base_version: int = Field(ge=1)


class RestoreInput(VersionInput):
    source_version: int = Field(ge=1)


class TaskSettingsInput(StrictModel):
    base_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    done: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=20_000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("task name cannot be blank")
        return value.strip()

    @field_validator("description", "done", "notes")
    @classmethod
    def clean_text(cls, value):
        return value.strip()


class ActivateInput(StrictModel):
    version: int = Field(ge=1)
    run_id: uuid.UUID


def training_router(store):
    router = APIRouter(prefix="/api/training")
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS training_apps(
            id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS training_tasks(
            id TEXT PRIMARY KEY, app_id TEXT NOT NULL REFERENCES training_apps(id), name TEXT NOT NULL,
            latest_version INTEGER NOT NULL, working_version INTEGER, created_at TEXT NOT NULL,
            archived_at TEXT, UNIQUE(app_id, name));
        CREATE TABLE IF NOT EXISTS training_versions(
            task_id TEXT NOT NULL REFERENCES training_tasks(id), version INTEGER NOT NULL,
            session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id), created_at TEXT NOT NULL,
            parent_version INTEGER, PRIMARY KEY(task_id, version));
        CREATE INDEX IF NOT EXISTS training_tasks_app ON training_tasks(app_id);
        """)
        task_columns = {row[1] for row in db.execute("PRAGMA table_info(training_tasks)")}
        if "archived_at" not in task_columns:
            db.execute("ALTER TABLE training_tasks ADD COLUMN archived_at TEXT")

    def get_task(db, task_id):
        row = db.execute("SELECT * FROM training_tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "task not found")
        return row

    def versions(db, task_id):
        return [dict(row) for row in db.execute(
            "SELECT version,session_id,created_at,parent_version FROM training_versions WHERE task_id=? ORDER BY version",
            (task_id,))]

    def detail(task_id):
        with store.connect() as db:
            task = get_task(db, task_id)
            history = versions(db, task_id)
            latest = next(v for v in history if v["version"] == task["latest_version"])
            data = store.get_session(latest["session_id"])
            name = data.get("answers", {}).get("teaching_task_name") or data.get("title") or task["name"]
            return {"id": task_id, "app_id": task["app_id"], "name": name,
                    "latest_version": task["latest_version"], "working_version": task["working_version"],
                    "archived_at": task["archived_at"], "archived": task["archived_at"] is not None,
                    "versions": [{k: v[k] for k in ("version", "session_id", "created_at", "parent_version")} for v in history],
                    "session": _session_context(data, task["latest_version"])}

    def make_session(task_name, description, done, source=None):
        data = {"id": str(uuid.uuid4()), "title": task_name, "created_at": _now(), "notes": "",
                "answers": {"teaching_task_name": task_name, "teaching_goal": description, "teaching_done": done,
                            "teaching_recording_confirmed": "no"},
                "procedure": {"revision": 1, "steps": []}, "media_url": None, "runs": []}
        if source:
            data["notes"] = source.get("notes", "")
            data["answers"] = {k: v for k, v in source.get("answers", {}).items()
                               if k not in {"teaching_recording_confirmed", "teaching_approval"}}
            data["answers"].update({"teaching_goal": description, "teaching_done": done,
                                    "teaching_task_name": source.get("answers", {}).get("teaching_task_name") or source.get("title", task_name),
                                    "teaching_recording_confirmed": "no"})
            data["procedure"] = json.loads(json.dumps(source["procedure"]))
            if source.get("media_url"):
                data["media_url"] = f"/api/sessions/{data['id']}/media"
        return data

    def store_version_session(data, source_id=None):
        """Copy a source recording before DB insert; roll back bytes on DB failure."""
        copied = None
        try:
            if source_id:
                source_path = next((p for ext in (".webm", ".mp4")
                                    if (p := store.artifacts / f"{source_id}{ext}").is_file()
                                    and not p.is_symlink() and p.resolve().parent == store.artifacts.resolve()), None)
                if source_path:
                    copied = store.artifacts / f"{data['id']}{source_path.suffix}"
                    with source_path.open("rb") as src, copied.open("xb") as dst:
                        shutil.copyfileobj(src, dst)
                        dst.flush()
                        os.fsync(dst.fileno())
            store.save_session(data)
        except Exception:
            if copied:
                copied.unlink(missing_ok=True)
            raise

    def _session_context(data, version):
        data["training"] = {"version": version}
        return data

    @router.get("/apps")
    def list_apps(include_archived: bool = False):
        with store.connect() as db:
            apps = []
            for app in db.execute("SELECT id,name FROM training_apps ORDER BY created_at,id"):
                tasks = []
                query = "SELECT * FROM training_tasks WHERE app_id=?"
                if not include_archived:
                    query += " AND archived_at IS NULL"
                query += " ORDER BY created_at,id"
                for task in db.execute(query, (app["id"],)):
                    latest = db.execute("SELECT session_id FROM training_versions WHERE task_id=? AND version=?",
                                        (task["id"], task["latest_version"])).fetchone()
                    session = store.get_session(latest["session_id"])
                    tasks.append({"id": task["id"], "name": session.get("answers", {}).get("teaching_task_name") or session.get("title") or task["name"],
                                  "description": session["answers"].get("teaching_goal", ""),
                                  "latest_version": task["latest_version"], "working_version": task["working_version"],
                                  "archived_at": task["archived_at"], "archived": task["archived_at"] is not None,
                                  "session_id": latest["session_id"]})
                apps.append({"id": app["id"], "name": app["name"], "tasks": tasks})
            return {"apps": apps}

    @router.post("/apps")
    def create_app(body: AppInput):
        ident = str(uuid.uuid4())
        try:
            with store.connect() as db:
                db.execute("INSERT INTO training_apps VALUES(?,?,?)", (ident, body.name, _now()))
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(409, "an app with that name already exists") from exc
            raise
        return {"id": ident, "name": body.name, "tasks": []}

    @router.post("/apps/{app_id}/tasks")
    def create_task(app_id: uuid.UUID, body: TaskInput):
        aid, tid = str(app_id), str(uuid.uuid4())
        with store.connect() as db:
            if not db.execute("SELECT 1 FROM training_apps WHERE id=?", (aid,)).fetchone():
                raise HTTPException(404, "app not found")
            # The name is an organizational label, not intent; reject a duplicate
            # name in this app before creating a session so we never orphan bytes.
            if db.execute("SELECT 1 FROM training_tasks WHERE app_id=? AND name=? COLLATE NOCASE",
                          (aid, body.name)).fetchone():
                raise HTTPException(409, "a task with that name already exists in this app")
        data = make_session(body.name, body.description, body.done)
        store_version_session(data)
        try:
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO training_tasks(id,app_id,name,latest_version,working_version,created_at) VALUES(?,?,?,?,?,?)",
                    (tid, aid, body.name, 1, None, _now()),
                )
                db.execute("INSERT INTO training_versions VALUES(?,?,?,?,?)", (tid, 1, data["id"], _now(), None))
        except Exception as exc:
            # A session that could not be attached must not become an orphaned training session.
            # The UNIQUE(app_id,name) backstop catches a race past the pre-check above.
            if "UNIQUE" in str(exc).upper():
                with store.connect() as db:
                    db.execute("DELETE FROM procedure_revisions WHERE session_id=?", (data["id"],))
                    db.execute("DELETE FROM sessions WHERE id=?", (data["id"],))
                raise HTTPException(409, "a task with that name already exists in this app") from exc
            with store.connect() as db:
                db.execute("DELETE FROM procedure_revisions WHERE session_id=?", (data["id"],))
                db.execute("DELETE FROM sessions WHERE id=?", (data["id"],))
            raise
        return detail(tid)

    @router.get("/tasks/{task_id}")
    def get_task_detail(task_id: uuid.UUID):
        return detail(str(task_id))

    @router.post("/tasks/{task_id}/archive")
    def archive_task(task_id: uuid.UUID):
        tid = str(task_id)
        with store.lock, store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = get_task(db, tid)
            if task["archived_at"] is None:
                db.execute("UPDATE training_tasks SET archived_at=? WHERE id=?", (_now(), tid))
        return detail(tid)

    @router.post("/tasks/{task_id}/unarchive")
    def unarchive_task(task_id: uuid.UUID):
        tid = str(task_id)
        with store.lock, store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            get_task(db, tid)
            db.execute("UPDATE training_tasks SET archived_at=NULL WHERE id=?", (tid,))
        return detail(tid)

    def fork_version(task_id, base_version, source_version=None, settings=None):
        tid = str(task_id)
        with store.connect() as db:
            task = get_task(db, tid)
            if task["archived_at"] is not None:
                raise HTTPException(409, "task is archived; restore it before creating or restoring a version")
            if task["latest_version"] != base_version:
                raise HTTPException(409, "task changed; reload before creating a version")
            chosen = source_version if source_version is not None else base_version
            row = db.execute("SELECT session_id FROM training_versions WHERE task_id=? AND version=?", (tid, chosen)).fetchone()
            if row is None:
                raise HTTPException(404, "source version not found")
            src = store.get_session(row["session_id"])
            current = store.get_session(db.execute("SELECT session_id FROM training_versions WHERE task_id=? AND version=?",
                                                  (tid, base_version)).fetchone()[0])
            content = src if source_version is not None else current
            description = content.get("answers", {}).get("teaching_goal", "")
            done = content.get("answers", {}).get("teaching_done", "")
            task_name = content.get("answers", {}).get("teaching_task_name") or content.get("title") or task["name"]
            new_number = task["latest_version"] + 1
            if settings is not None:
                other = db.execute(
                    "SELECT 1 FROM training_tasks WHERE app_id=? AND name=? COLLATE NOCASE AND id<>?",
                    (task["app_id"], settings["name"], tid),
                ).fetchone()
                if other is not None:
                    raise HTTPException(409, "a task with that name already exists in this app")
                current_answers = current.get("answers", {})
                if (settings["name"].casefold() == task["name"].casefold()
                        and settings["description"] == current_answers.get("teaching_goal", "")
                        and settings["done"] == current_answers.get("teaching_done", "")
                        and settings["notes"] == current.get("notes", "")):
                    return detail(tid)
        data = make_session(task_name, description, done, src)
        if settings is not None:
            data["title"] = settings["name"]
            data["answers"].update({
                "teaching_task_name": settings["name"],
                "teaching_goal": settings["description"],
                "teaching_done": settings["done"],
            })
            data["notes"] = settings["notes"]
        store_version_session(data, src["id"])
        try:
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                task = get_task(db, tid)
                if task["archived_at"] is not None:
                    raise HTTPException(409, "task is archived; restore it before creating a version")
                if task["latest_version"] != base_version:
                    raise HTTPException(409, "task changed; reload before creating a version")
                if settings is not None:
                    other = db.execute(
                        "SELECT 1 FROM training_tasks WHERE app_id=? AND name=? COLLATE NOCASE AND id<>?",
                        (task["app_id"], settings["name"], tid),
                    ).fetchone()
                    if other is not None:
                        raise HTTPException(409, "a task with that name already exists in this app")
                db.execute("INSERT INTO training_versions VALUES(?,?,?,?,?)", (tid, new_number, data["id"], _now(), chosen))
                if settings is None:
                    db.execute("UPDATE training_tasks SET latest_version=? WHERE id=?", (new_number, tid))
                else:
                    db.execute(
                        "UPDATE training_tasks SET name=?, latest_version=? WHERE id=?",
                        (settings["name"], new_number, tid),
                    )
        except Exception:
            with store.connect() as db:
                db.execute("DELETE FROM procedure_revisions WHERE session_id=?", (data["id"],))
                db.execute("DELETE FROM sessions WHERE id=?", (data["id"],))
            (store.artifacts / f"{data['id']}.webm").unlink(missing_ok=True)
            (store.artifacts / f"{data['id']}.mp4").unlink(missing_ok=True)
            raise
        return detail(tid)

    @router.post("/tasks/{task_id}/edit")
    def edit_task(task_id: uuid.UUID, body: VersionInput):
        with store.lock:
            return fork_version(task_id, body.base_version)

    @router.put("/tasks/{task_id}/settings")
    def save_task_settings(task_id: uuid.UUID, body: TaskSettingsInput):
        tid = str(task_id)
        settings = body.model_dump(exclude={"base_version"})
        with store.lock:
            return fork_version(tid, body.base_version, settings=settings)

    @router.post("/tasks/{task_id}/restore")
    def restore_task(task_id: uuid.UUID, body: RestoreInput):
        with store.lock:
            return fork_version(task_id, body.base_version, body.source_version)

    def activate_locked(task_id: uuid.UUID, body: ActivateInput):
        tid = str(task_id)
        # The same write reservation used by proposal creation prevents a new
        # proposal or task version from slipping between validation and promotion.
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = get_task(db, tid)
            if task["archived_at"] is not None:
                raise HTTPException(409, "task is archived; restore it before activating a version")
            if body.version != task["latest_version"] or task["working_version"] == body.version:
                raise HTTPException(409, "only the latest unpromoted version can become working")
            row = db.execute("SELECT session_id FROM training_versions WHERE task_id=? AND version=?",
                             (tid, body.version)).fetchone()
            sid = row["session_id"]
            session = store.get_session(sid)
            proposal = latest_proposal(store.root, sid)
            if proposal is None or proposal.get("questions"):
                raise HTTPException(409, "current understanding proposal is not ready")
            current_source = teaching_source(store.root, sid)
            if any(proposal.get(k) != v for k, v in current_source.items()):
                raise HTTPException(409, "understanding proposal is stale")
            reviewed_procedure = Procedure.model_validate(proposal.get("procedure")).model_dump(exclude_none=True)
            saved_procedure = Procedure.model_validate(session.get("procedure")).model_dump(exclude_none=True)
            if reviewed_procedure != saved_procedure:
                raise HTTPException(409, "saved procedure does not match the reviewed proposal")
            receipt_path = store.artifacts / f"{sid}.{proposal['id']}.understanding.json"
            try:
                receipt = json.loads(receipt_path.read_text()) if not receipt_path.is_symlink() else {}
            except (OSError, ValueError):
                receipt = {}
            if receipt.get("proposal_id") != proposal["id"] or receipt.get("consent") is not True or any(
                    receipt.get(k) != v for k, v in current_source.items()):
                raise HTTPException(409, "current understanding has not been explicitly approved")
            run = next((r for r in session.get("runs", []) if r.get("id") == str(body.run_id)), None)
            if (not run or run.get("status") != "verified" or run.get("mode") != "procedure"
                    or run.get("revision") != reviewed_procedure.get("revision")
                    or not run.get("procedure")
                    or Procedure.model_validate(run["procedure"]).model_dump(exclude_none=True) != reviewed_procedure):
                raise HTTPException(409, "matching verified procedure trial is required")
            db.execute("UPDATE training_tasks SET working_version=? WHERE id=? AND latest_version=?",
                       (body.version, tid, body.version))
            if db.total_changes == 0:
                raise HTTPException(409, "task changed while activation was being checked")
        result = detail(tid)
        result["activation"] = {"status": "working", "capability": "supported_fixture_only",
                                "message": "This version is working for the reviewed fixture trial only."}
        return result

    @router.post("/tasks/{task_id}/activate")
    def activate_task(task_id: uuid.UUID, body: ActivateInput):
        with store.lock:
            return activate_locked(task_id, body)

    return router


def is_mutable_training_session(store, session_id: str) -> bool:
    """Return false for historical and working training sessions."""
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_versions'").fetchone():
            return True
        row = db.execute("""SELECT 1 FROM training_versions v JOIN training_tasks t ON t.id=v.task_id
                          WHERE v.session_id=? AND (v.version<t.latest_version OR v.version=t.working_version
                                                     OR t.archived_at IS NOT NULL)""",
                         (session_id,)).fetchone()
    return row is None


def is_archived_training_session(store, session_id: str) -> bool:
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_tasks'").fetchone():
            return False
        row = db.execute("""SELECT t.archived_at FROM training_versions v
                           JOIN training_tasks t ON t.id=v.task_id WHERE v.session_id=?""",
                         (session_id,)).fetchone()
    return row is not None and row["archived_at"] is not None


def training_task_metadata(db, session_id: str) -> dict | None:
    """Return explicit app/task/version ownership, or None for legacy sessions."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"training_apps", "training_tasks", "training_versions"}.issubset(tables):
        return None
    try:
        row = db.execute("""SELECT a.id AS app_id, a.name AS app_name, t.id AS task_id,
                                  t.name AS stored_task_name, t.latest_version, t.working_version,
                                  v.version, latest.data AS latest_data
                           FROM training_versions v
                           JOIN training_tasks t ON t.id=v.task_id
                           JOIN training_apps a ON a.id=t.app_id
                           LEFT JOIN training_versions lv ON lv.task_id=t.id AND lv.version=t.latest_version
                           LEFT JOIN sessions latest ON latest.id=lv.session_id
                           WHERE v.session_id=?""", (session_id,)).fetchone()
    except sqlite3.OperationalError:
        # Partial/older installations may have a training table without the full schema.
        return None
    if row is None:
        return None
    name = row["stored_task_name"]
    if row["latest_data"]:
        try:
            current = json.loads(row["latest_data"])
            name = current.get("answers", {}).get("teaching_task_name") or current.get("title") or name
        except (TypeError, ValueError, AttributeError):
            pass
    return {"app_id": row["app_id"], "app_name": row["app_name"], "task_id": row["task_id"],
            "task_name": name, "version": row["version"], "latest_version": row["latest_version"],
            "working_version": row["working_version"]}
