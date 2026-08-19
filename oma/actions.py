"""Core data models: proposed actions and policy decisions.

These types are deliberately plain and serializable so that proposals,
decisions, and execution results can be logged and audited.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


class ActionKind(str, enum.Enum):
    """The kinds of side effects a plan may propose."""

    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    DELETE_FILE = "delete_file"
    SEND_EMAIL = "send_email"
    HTTP_GET = "http_get"
    RUN_SHELL = "run_shell"
    TRANSFER_FUNDS = "transfer_funds"


@dataclass
class Action:
    """A single concrete action proposed by a planner.

    The planner fills in ``kind``, ``params`` and a human-readable
    ``rationale``. It has no ability to execute the action itself.

    ``id`` is derived deterministically from the action's kind and parameters
    so the same proposal keeps the same id across runs. This is what lets a
    human approve an action by id and have that approval survive a re-plan of
    the same goal.
    """

    kind: ActionKind
    params: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self._stable_id()

    def _stable_id(self) -> str:
        payload = json.dumps(
            {"kind": self.kind.value, "params": self.params},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
        return f"act-{digest}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "params": self.params,
            "rationale": self.rationale,
        }


class Verdict(str, enum.Enum):
    """The deterministic policy's ruling on a proposed action."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class Decision:
    """The result of evaluating an action against the policy."""

    verdict: Verdict
    reasons: List[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    def to_dict(self) -> Dict[str, Any]:
        return {"verdict": self.verdict.value, "reasons": list(self.reasons)}
