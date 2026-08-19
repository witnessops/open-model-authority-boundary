"""A sandboxed executor operating over an in-memory ``World``.

The executor is the *only* component that produces side effects, and it will
refuse to run an action that has not been authorized by the policy engine.
Effects are simulated (in-memory files, an outbox, fetch log) so the demo is
safe and fully reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .actions import Action, ActionKind, Decision


class ExecutionError(RuntimeError):
    """Raised when execution is attempted without authorization."""


@dataclass
class World:
    """A simulated environment the executor mutates."""

    files: Dict[str, str] = field(
        default_factory=lambda: {
            "workspace/report.txt": "Q3 revenue up 12%.",
            "workspace/tmp/cache": "cached bytes",
            "workspace/secrets/api_key": "sk-do-not-touch",
        }
    )
    outbox: List[Dict[str, Any]] = field(default_factory=list)
    fetches: List[str] = field(default_factory=list)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "files": sorted(self.files.keys()),
            "outbox": list(self.outbox),
            "fetches": list(self.fetches),
        }


class Executor:
    """Runs authorized actions against a :class:`World`."""

    def __init__(self, world: World | None = None) -> None:
        self.world = world or World()

    def execute(self, action: Action, decision: Decision) -> Dict[str, Any]:
        """Execute ``action`` iff ``decision`` permits it.

        This double-checks authorization at the execution site so a bug or
        bypass upstream cannot smuggle an action past the boundary.
        """

        if not decision.allowed:
            raise ExecutionError(
                f"refusing to execute {action.kind.value}: "
                f"decision was '{decision.verdict.value}'"
            )

        handler = getattr(self, f"_do_{action.kind.value}", None)
        if handler is None:
            raise ExecutionError(f"no executor for kind '{action.kind.value}'")
        return handler(action)

    def _do_read_file(self, action: Action) -> Dict[str, Any]:
        path = action.params["path"]
        content = self.world.files.get(path)
        if content is None:
            return {"ok": False, "error": f"file not found: {path}"}
        return {"ok": True, "path": path, "content": content}

    def _do_write_file(self, action: Action) -> Dict[str, Any]:
        path = action.params["path"]
        self.world.files[path] = action.params.get("content", "")
        return {"ok": True, "path": path, "bytes": len(self.world.files[path])}

    def _do_delete_file(self, action: Action) -> Dict[str, Any]:
        path = action.params["path"]
        existed = self.world.files.pop(path, None) is not None
        return {"ok": True, "path": path, "existed": existed}

    def _do_send_email(self, action: Action) -> Dict[str, Any]:
        message = {
            "to": action.params.get("to"),
            "subject": action.params.get("subject", ""),
            "body": action.params.get("body", ""),
        }
        self.world.outbox.append(message)
        return {"ok": True, "delivered_to": message["to"]}

    def _do_http_get(self, action: Action) -> Dict[str, Any]:
        url = action.params["url"]
        self.world.fetches.append(url)
        return {"ok": True, "url": url, "status": 200, "body": f"<simulated {url}>"}
