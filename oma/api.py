"""FastAPI service exposing the authority boundary plus a small web UI."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .boundary import AuthorityBoundary
from .planner import load_planner
from .policy import Policy

app = FastAPI(title="Open Model Authority Boundary", version="0.1.0")

_WEB_DIR = Path(__file__).parent / "web"


class PlanRequest(BaseModel):
    goal: str
    planner: str = "heuristic"
    approvals: List[str] = []


def _boundary(planner_name: str) -> AuthorityBoundary:
    return AuthorityBoundary(planner=load_planner(planner_name))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_WEB_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/policy")
def get_policy() -> dict:
    p = Policy.default()
    return {
        "allowed_kinds": sorted(k.value for k in p.allowed_kinds),
        "approval_kinds": sorted(k.value for k in p.approval_kinds),
        "forbidden_kinds": sorted(k.value for k in p.forbidden_kinds),
        "path_allowlist": p.path_allowlist,
        "path_denylist": p.path_denylist,
        "email_domain_allowlist": p.email_domain_allowlist,
        "http_host_allowlist": p.http_host_allowlist,
    }


@app.post("/api/plan")
def plan(req: PlanRequest) -> dict:
    """Plan a goal and execute whatever the policy authorizes."""

    result = _boundary(req.planner).run(req.goal, approvals=req.approvals)
    return result.to_dict()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
