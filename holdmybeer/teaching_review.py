"""Review-only consent for one recording and its current task description.

These receipts never install a procedure or authorize an executor.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import StrictBool

from .models import StrictModel
from .proposals import latest_proposal, teaching_source


class UnderstandingApproval(StrictModel):
    proposal_id: UUID
    consent: StrictBool


def teaching_router(store):
    router = APIRouter()

    def review(session_id):
        store.get_session(session_id)
        proposal = latest_proposal(store.root, session_id)
        result = {"status": "waiting", "proposal": proposal, "can_execute": False,
                  "execution_reason": "Repeating recorded tasks is not available in this preview."}
        if proposal is None:
            return result
        source = teaching_source(store.root, session_id)
        if not source["source_media_sha256"] or any(proposal.get(key) != value for key, value in source.items()):
            result["status"] = "stale"
        elif proposal["questions"]:
            result["status"] = "questions"
        else:
            result["status"] = "ready"
            path = store.artifacts / f"{session_id}.{proposal['id']}.understanding.json"
            try:
                if not path.is_symlink() and path.stat().st_size <= 4000:
                    receipt = json.loads(path.read_text())
                    if (receipt.get("proposal_id") == proposal["id"] and receipt.get("consent") is True
                            and all(receipt.get(key) == value for key, value in source.items())):
                        result["status"] = "approved"
            except (OSError, ValueError, AttributeError):
                pass
        return result

    @router.get("/api/sessions/{session_id}/teaching-review")
    def get_review(session_id: UUID):
        return review(str(session_id))

    @router.post("/api/sessions/{session_id}/teaching-review/approve")
    def approve(session_id: UUID, body: UnderstandingApproval):
        sid = str(session_id)
        if body.consent is not True:
            raise HTTPException(422, "Explicit agreement is required.")
        with store.lock:
            from .training import is_mutable_training_session
            if not is_mutable_training_session(store, sid):
                raise HTTPException(409, "This training version is retained. Use Edit task to create a new draft.")
            answers = store.get_session(sid).get("answers", {})
            if (not answers.get("teaching_goal", "").strip() or not answers.get("teaching_done", "").strip()
                    or answers.get("teaching_recording_confirmed") != "yes"):
                raise HTTPException(409, "Describe the task and confirm your complete recording first.")
            current = review(sid)
            proposal = current["proposal"]
            if current["status"] not in {"ready", "approved"} or proposal["id"] != str(body.proposal_id):
                raise HTTPException(409, "Review the current recording and resolve questions before agreeing.")
            receipt = {"proposal_id": proposal["id"], "consent": True,
                       "approved_at": datetime.now(timezone.utc).isoformat(),
                       **teaching_source(store.root, sid)}
            target = store.artifacts / f"{sid}.{proposal['id']}.understanding.json"
            fd, name = tempfile.mkstemp(prefix=".understanding-", dir=store.artifacts)
            try:
                with os.fdopen(fd, "w") as output:
                    json.dump(receipt, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, target)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        return review(sid)

    return router
