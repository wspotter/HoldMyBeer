"""Validated, review-only teaching proposal persistence."""
from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator

from .models import Procedure, StrictModel

MAX_OBSERVATIONS = 6
MAX_QUESTIONS = 6
MAX_TIMESTAMP = 86_400
SAFE_QUESTION_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Observation(StrictModel):
    timestamp: float = Field(ge=0, le=MAX_TIMESTAMP, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("observation text cannot be blank")
        return value


class TeachingQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1, max_length=300)

    @field_validator("id")
    @classmethod
    def safe_slug(cls, value: str) -> str:
        if not SAFE_QUESTION_ID.fullmatch(value):
            raise ValueError("question id must be a lowercase slug")
        return value

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question cannot be blank")
        return value


class TeachingProposal(StrictModel):
    id: str
    session_id: str
    observations: list[Observation] = Field(min_length=1, max_length=MAX_OBSERVATIONS)
    questions: list[TeachingQuestion] = Field(max_length=MAX_QUESTIONS)
    procedure: Procedure
    created_at: str
    source_media_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_context_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("created_at")
    @classmethod
    def timezone_aware_created_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("created_at must be an ISO timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def unique_question_ids(self):
        ids = [item.id for item in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return self


def _session_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid session id") from exc


def _proposal_from_input(session_id: str, observations: list[dict], questions: list[dict], procedure: dict) -> TeachingProposal:
    sid = _session_id(session_id)
    try:
        proposal = TeachingProposal.model_validate({
            "id": str(uuid.uuid4()),
            "session_id": sid,
            "observations": observations,
            "questions": questions,
            "procedure": procedure,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except ValidationError:
        raise ValueError("invalid teaching proposal payload") from None
    actions = [step.action for step in proposal.procedure.steps]
    if actions not in (["upload", "fill", "click", "verify_draft"], ["select_media", "fill", "click", "verify_draft"]):
        raise ValueError("proposal procedure must contain select_media or upload, fill, click, verify_draft actions in order")
    return proposal


def _session_exists(root: Path, session_id: str) -> bool:
    db_path = root.resolve() / "holdmybeer.sqlite3"
    if not db_path.is_file():
        return False
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        return db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is not None


def teaching_source(root: Path, session_id: str) -> dict[str, str | None]:
    """Fingerprint current inputs, not a claim that an assistant inspected them."""
    sid = _session_id(session_id)
    with sqlite3.connect((root.resolve() / "holdmybeer.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        row = db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
    if row is None:
        raise ValueError("session not found")
    data = json.loads(row[0])
    context = {key: data.get(key, "") for key in ("title", "notes", "media_revision")}
    context["answers"] = {key: value for key, value in data.get("answers", {}).items()
                          if key not in {"teaching_approval", "teaching_recording_confirmed"}}
    digest = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    artifacts = (root.resolve() / "artifacts").resolve()
    media_digest = None
    for suffix in (".webm", ".mp4"):
        path = artifacts / (sid + suffix)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 100 * 1024 * 1024:
            continue
        if path.resolve().parent != artifacts:
            continue
        with path.open("rb") as source:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
        media_digest = hasher.hexdigest()
        break
    return {"source_media_sha256": media_digest, "source_context_sha256": digest}


def _validated_file(path: Path, session_id: str) -> dict[str, Any] | None:
    try:
        resolved = path.resolve(strict=True)
        if resolved.parent != path.parent.resolve() or not resolved.is_file() or resolved.stat().st_size > 64_000:
            return None
        proposal = TeachingProposal.model_validate_json(resolved.read_text(encoding="utf-8"))
        if proposal.session_id != session_id or proposal.id != path.name.split(".")[1]:
            return None
        if [step.action for step in proposal.procedure.steps] not in (["upload", "fill", "click", "verify_draft"], ["select_media", "fill", "click", "verify_draft"]):
            return None
        return proposal.model_dump(mode="json")
    except (OSError, ValueError):
        return None


def latest_proposal(root: Path, session_id: str) -> dict[str, Any] | None:
    """Return the newest valid proposal for this session, ignoring unsafe/corrupt files."""
    sid = _session_id(session_id)
    artifacts = (root.resolve() / "artifacts").resolve()
    if not artifacts.is_dir():
        return None
    candidates: list[dict[str, Any]] = []
    for path in artifacts.glob(f"{sid}.*.proposal.json"):
        try:
            proposal_id = str(UUID(path.name.split(".")[1]))
        except (ValueError, IndexError):
            continue
        if path.name != f"{sid}.{proposal_id}.proposal.json":
            continue
        data = _validated_file(path, sid)
        if data is not None:
            candidates.append(data)
    return max(candidates, key=lambda item: item["created_at"], default=None)


def create_proposal(root: Path, session_id: str, observations: list[dict], questions: list[dict], procedure: dict) -> dict[str, Any]:
    """Atomically write one review-only proposal beside the session's local artifacts."""
    proposal = _proposal_from_input(session_id, observations, questions, procedure)
    db_path = root.resolve() / "holdmybeer.sqlite3"
    if not db_path.is_file():
        raise ValueError("session not found")
    # Proposal creation and activation serialize through the same SQLite write
    # reservation, including the ownership/freeze check and source snapshot.
    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM sessions WHERE id=?", (proposal.session_id,)).fetchone() is None:
            raise ValueError("session not found")
        # Import here to avoid the training -> proposals import cycle.
        from .training import training_task_metadata
        metadata = training_task_metadata(db, proposal.session_id)
        if metadata is not None and not _is_mutable_training_session_db(db, proposal.session_id):
            raise ValueError("This task version is frozen. Use Edit task to continue teaching it.")
        proposal = proposal.model_copy(update=teaching_source(root, proposal.session_id))
        artifacts = (root.resolve() / "artifacts").resolve()
        artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = artifacts / f"{proposal.session_id}.{proposal.id}.proposal.json"
        payload = (proposal.model_dump_json() + "\n").encode("utf-8")
        fd, temp_name = tempfile.mkstemp(prefix=".proposal-", suffix=".tmp", dir=artifacts)
        temp = Path(temp_name)
        created = False
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        # Hard-link creation is atomic and fails if the destination already exists.
        os.link(temp, target, follow_symlinks=False)
        created = True
        directory_fd = os.open(artifacts, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        db.commit()
    except Exception:
        db.rollback()
        if "created" in locals() and created:
            target.unlink(missing_ok=True)
        raise
    finally:
        if "temp" in locals():
            temp.unlink(missing_ok=True)
        db.close()
    return proposal.model_dump(mode="json")


def _is_mutable_training_session_db(db: sqlite3.Connection, session_id: str) -> bool:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"training_versions", "training_tasks"}.issubset(tables):
        return True
    row = db.execute("""SELECT 1 FROM training_versions v JOIN training_tasks t ON t.id=v.task_id
                      WHERE v.session_id=? AND (v.version<t.latest_version OR v.version=t.working_version)""",
                     (session_id,)).fetchone()
    return row is None
