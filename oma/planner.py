"""Planners turn a natural-language goal into a list of proposed actions.

A planner has *no* execution authority. It only proposes. The default
:class:`HeuristicPlanner` is deterministic and offline so the system runs with
no model weights, GPU, or network access. :class:`TransformersPlanner` is an
optional adapter that drives proposals with a real open model.
"""

from __future__ import annotations

import re
from typing import List, Protocol

from .actions import Action, ActionKind


class Planner(Protocol):
    """Anything that can propose a plan for a goal."""

    def propose(self, goal: str) -> List[Action]:  # pragma: no cover - protocol
        ...


class HeuristicPlanner:
    """A tiny deterministic planner driven by keyword intents.

    It is not meant to be clever. It exists to produce realistic, varied
    proposals (including ones the policy must reject) without any model.
    """

    _EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    _PATH_RE = re.compile(r"(?:file|path|cache|log|report)\s+([\w./-]+)")
    _URL_RE = re.compile(r"https?://[\w./:-]+")

    def propose(self, goal: str) -> List[Action]:
        text = goal.strip()
        lowered = text.lower()
        actions: List[Action] = []

        for url in self._URL_RE.findall(text):
            actions.append(
                Action(
                    ActionKind.HTTP_GET,
                    {"url": url},
                    rationale=f"fetch data referenced by the goal ({url})",
                )
            )

        if any(w in lowered for w in ("read", "open", "review", "load")):
            path = self._guess_path(text, default="workspace/report.txt")
            actions.append(
                Action(
                    ActionKind.READ_FILE,
                    {"path": path},
                    rationale="read the referenced file to gather context",
                )
            )

        for addr in self._EMAIL_RE.findall(text):
            actions.append(
                Action(
                    ActionKind.SEND_EMAIL,
                    {
                        "to": addr,
                        "subject": self._subject(lowered),
                        "body": f"Automated message for goal: {text}",
                    },
                    rationale=f"the goal asks to email {addr}",
                )
            )

        if "write" in lowered or "save" in lowered or "create" in lowered:
            path = self._guess_path(text, default="workspace/output.txt")
            actions.append(
                Action(
                    ActionKind.WRITE_FILE,
                    {"path": path, "content": f"Result for: {text}"},
                    rationale="persist the produced result to disk",
                )
            )

        if any(w in lowered for w in ("delete", "remove", "clean", "purge")):
            path = self._guess_path(text, default="workspace/tmp/cache")
            actions.append(
                Action(
                    ActionKind.DELETE_FILE,
                    {"path": path},
                    rationale="clean up temporary files requested by the goal",
                )
            )

        # Models sometimes propose shortcuts. Surface a shell action when the
        # goal hints at it so the policy boundary is exercised.
        if any(w in lowered for w in ("run", "execute", "shell", "command", "script")):
            actions.append(
                Action(
                    ActionKind.RUN_SHELL,
                    {"command": "bash ./do_the_thing.sh"},
                    rationale="run a helper script to accomplish the goal quickly",
                )
            )

        if any(w in lowered for w in ("pay", "transfer", "wire", "refund")):
            actions.append(
                Action(
                    ActionKind.TRANSFER_FUNDS,
                    {"amount": 500, "to_account": "external-1234"},
                    rationale="the goal mentions moving money",
                )
            )

        if not actions:
            path = self._guess_path(text, default="workspace/report.txt")
            actions.append(
                Action(
                    ActionKind.READ_FILE,
                    {"path": path},
                    rationale="no explicit intent detected; inspect a default file",
                )
            )

        return actions

    def _guess_path(self, text: str, default: str) -> str:
        m = self._PATH_RE.search(text)
        if m:
            candidate = m.group(1)
            if "/" not in candidate:
                candidate = f"workspace/{candidate}"
            return candidate
        return default

    @staticmethod
    def _subject(lowered: str) -> str:
        if "report" in lowered:
            return "Report"
        if "invoice" in lowered:
            return "Invoice"
        return "Automated message"


def load_planner(name: str = "heuristic", **kwargs) -> Planner:
    """Factory that returns a planner by name.

    ``heuristic`` (default) is always available. ``transformers`` requires the
    optional dependency and is imported lazily so the base install stays light.
    """

    if name == "heuristic":
        return HeuristicPlanner()
    if name == "transformers":
        from .transformers_planner import TransformersPlanner

        return TransformersPlanner(**kwargs)
    raise ValueError(f"unknown planner '{name}'")
