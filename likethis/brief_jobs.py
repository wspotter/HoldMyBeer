"""Durable, explicitly approved jobs for the supported read-only issue workflow.

The HTTP UI approves an immutable plan; MCP may prepare and start only that plan.
This is a trusted-local-user boundary, not isolation from other local processes.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, StrictBool

from .models import StrictModel


class BriefRequest(StrictModel):
    session_id: uuid.UUID
    repository: str = Field(default="wspotter/HoldMyBeer", min_length=3, max_length=140)
    keyword: str = Field(default="", max_length=80)
    limit: int = Field(default=10, ge=1, le=10, strict=True)


class BriefApproval(StrictModel):
    plan_hash: str = Field(min_length=64, max_length=64)
    consent: StrictBool


class BriefJobs:
    def __init__(self, store, runner_lock):
        self.store = store
        self.root = store.db_path.parent / "issue-briefs"
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.runner_lock = runner_lock
        self.events = {}
        self.approvers = {}
        # An old process cannot finish a persisted running job. Never silently replay it.
        for path in self.root.glob("*.json"):
            job = json.loads(path.read_text())
            if job.get("status") == "running":
                job.update(status="interrupted", failure="Workspace restarted; inspect retained artifacts before preparing another run.")
                self.save(job)

    def save(self, job):
        path = self.root / (job["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, indent=2) + "\n")
        temporary.replace(path)

    def get(self, ident):
        try:
            ident = str(uuid.UUID(ident))
        except ValueError:
            raise HTTPException(404, "issue brief not found")
        with self.lock:
            path = self.root / (ident + ".json")
            if not path.is_file():
                raise HTTPException(404, "issue brief not found")
            return json.loads(path.read_text())

    def prepare(self, body):
        from .issue_brief import validate_inputs
        try:
            validate_inputs(body.repository, body.keyword, body.limit)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        session = self.store.get_session(str(body.session_id))
        plan = {"workflow": "github-issue-brief", "workflow_revision": 1,
                "session_id": session["id"], "session_revision": session["procedure"]["revision"],
                "repository": body.repository, "keyword": body.keyword, "limit": body.limit,
                "actions": ["Open the public repository issue list", "Search open issues using the supplied words",
                            "Read up to the requested number of visible issue links", "Save a local report and screenshot"],
                "read_only": True, "login": False, "publication": False}
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        job = {"id": str(uuid.uuid4()), "plan": plan, "plan_hash": digest,
               "created_at": time.time(), "status": "awaiting_approval", "result": None, "failure": None}
        with self.lock:
            self.save(job)
        return job

    def approve(self, ident, body):
        with self.lock:
            job = self.get(ident)
            if job["status"] != "awaiting_approval":
                raise HTTPException(409, "This plan cannot be approved again; inspect its current status.")
            if not body.consent or not secrets.compare_digest(body.plan_hash, job["plan_hash"]):
                raise HTTPException(409, "Explicit consent for this exact plan is required.")
            self.check_revision(job)
            job.update(status="approved", approved_at=time.time(), expires_at=time.time() + 600)
            self.save(job)
            return job

    def check_revision(self, job):
        session = self.store.get_session(job["plan"]["session_id"])
        if session["procedure"]["revision"] != job["plan"]["session_revision"]:
            raise HTTPException(409, "Session procedure changed; prepare and review a fresh plan.")

    def start(self, ident):
        with self.lock:
            job = self.get(ident)
            # Retrying the same start reads its receipt; it never launches a second browser.
            if job["status"] not in {"awaiting_approval", "approved"}:
                return job
            if job["status"] != "approved":
                raise HTTPException(409, "Review and approve this plan in the local workspace first.")
            if time.time() > job["expires_at"]:
                raise HTTPException(409, "Approval expired; prepare and review a fresh plan.")
            self.check_revision(job)
            if not self.runner_lock.acquire(blocking=False):
                raise HTTPException(429, "A browser run is already active.")
            event = threading.Event()
            self.events[job["id"]] = event
            job.update(status="running", started_at=time.time())
            try:
                # Persisting the running receipt is part of dispatch. Keep it in
                # the cleanup block too: disk errors here must not strand the
                # shared runner lock and permanently block later work.
                self.save(job)
                threading.Thread(target=self._run, args=(job, event), daemon=True).start()
            except Exception:
                self.events.pop(job["id"], None)
                self.runner_lock.release()
                job.update(status="failed", failure="Browser worker could not start or its running receipt could not be saved.")
                try:
                    self.save(job)
                except Exception:
                    # Preserve the original failure. The previous durable
                    # receipt remains available for inspection/recovery.
                    pass
                raise
            return job

    def _run(self, job, event):
        try:
            from .issue_brief import execute_issue_brief
            plan = job["plan"]
            result = execute_issue_brief(plan["repository"], plan["keyword"], plan["limit"],
                                         self.store.artifacts, job["id"], event)
            with self.lock:
                job.update(status=result["status"], result=result, finished_at=time.time())
                self.save(job)
        except Exception as exc:
            with self.lock:
                job.update(status="failed", failure=str(exc)[:500], finished_at=time.time())
                self.save(job)
        finally:
            with self.lock:
                self.events.pop(job["id"], None)
            self.runner_lock.release()

    def cancel(self, ident):
        with self.lock:
            job = self.get(ident)
            if job["status"] == "running":
                self.events[job["id"]].set()
                job["cancel_requested"] = True
            elif job["status"] in {"awaiting_approval", "approved"}:
                job["status"] = "cancelled"
            self.save(job)
            return job


def brief_router(jobs):
    router = APIRouter(prefix="/api/issue-briefs")

    @router.get("/approval-session")
    def approval_session(request: Request, response: Response):
        # The MCP tools do not expose this browser approval exchange.
        cookie = request.cookies.get("hmb_brief_approver")
        with jobs.lock:
            now = time.time()
            jobs.approvers = {k: v for k, v in jobs.approvers.items() if v[1] > now}
            if cookie not in jobs.approvers:
                cookie = secrets.token_urlsafe(32)
                jobs.approvers[cookie] = (secrets.token_urlsafe(32), now + 3600)
            csrf = jobs.approvers[cookie][0]
        response.set_cookie("hmb_brief_approver", cookie, httponly=True, samesite="strict",
                            path="/api/issue-briefs", max_age=3600)
        response.headers["Cache-Control"] = "no-store"
        return {"csrf": csrf}

    @router.post("")
    def prepare(body: BriefRequest):
        return jobs.prepare(body)

    @router.get("")
    def list_jobs(session_id: uuid.UUID):
        with jobs.lock:
            rows = [json.loads(p.read_text()) for p in jobs.root.glob("*.json")]
        return {"jobs": sorted((j for j in rows if j["plan"]["session_id"] == str(session_id)),
                               key=lambda j: j["created_at"], reverse=True)[:50]}

    @router.get("/{ident}")
    def get(ident: str):
        return jobs.get(ident)

    @router.post("/{ident}/approve")
    def approve(ident: str, body: BriefApproval, request: Request):
        cookie = request.cookies.get("hmb_brief_approver")
        with jobs.lock:
            entry = jobs.approvers.get(cookie)
            if (not entry or entry[1] < time.time() or
                    not secrets.compare_digest(request.headers.get("X-HMB-Approval", ""), entry[0])):
                raise HTTPException(403, "Open the local workspace and approve the exact plan there.")
        return jobs.approve(ident, body)

    @router.post("/{ident}/start")
    def start(ident: str):
        return jobs.start(ident)

    @router.post("/{ident}/cancel")
    def cancel(ident: str):
        return jobs.cancel(ident)

    @router.get("/{ident}/report")
    def report(ident: str):
        from fastapi.responses import FileResponse
        job = jobs.get(ident)
        path = jobs.store.artifacts / f"{job['id']}-issues.json"
        if job["status"] != "verified" or not path.is_file():
            raise HTTPException(404, "No verified report is retained for this job.")
        return FileResponse(path, media_type="application/json", filename=f"{job['id']}-issues.json")

    return router
