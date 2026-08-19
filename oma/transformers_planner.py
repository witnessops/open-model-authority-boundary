"""Optional planner backed by a real open model via ``transformers``.

This adapter is imported lazily by :func:`oma.planner.load_planner` so the base
install never requires heavy ML dependencies. It asks a text-generation model
to emit a JSON array of proposed actions, then parses that into
:class:`~oma.actions.Action` objects. The model still has no execution
authority: its output is only a *proposal* that the policy engine must clear.
"""

from __future__ import annotations

import json
import re
from typing import List

from .actions import Action, ActionKind

_PROMPT = """You are a planning assistant. Given a goal, output ONLY a JSON
array of proposed actions. Each item is an object with keys "kind", "params",
and "rationale". Valid kinds: {kinds}.

Goal: {goal}
JSON:"""


class TransformersPlanner:
    """Drive proposals with a Hugging Face text-generation pipeline."""

    def __init__(
        self,
        model: str = "Qwen/Qwen2.5-0.5B-Instruct",
        max_new_tokens: int = 256,
    ) -> None:
        from transformers import pipeline  # imported lazily

        self._pipe = pipeline("text-generation", model=model)
        self._max_new_tokens = max_new_tokens

    def propose(self, goal: str) -> List[Action]:
        kinds = ", ".join(k.value for k in ActionKind)
        prompt = _PROMPT.format(kinds=kinds, goal=goal)
        out = self._pipe(prompt, max_new_tokens=self._max_new_tokens)[0]
        text = out["generated_text"][len(prompt) :]
        return self._parse(text)

    @staticmethod
    def _parse(text: str) -> List[Action]:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

        actions: List[Action] = []
        for item in items:
            try:
                kind = ActionKind(item["kind"])
            except (KeyError, ValueError):
                continue
            actions.append(
                Action(
                    kind=kind,
                    params=item.get("params", {}) or {},
                    rationale=item.get("rationale", ""),
                )
            )
        return actions
