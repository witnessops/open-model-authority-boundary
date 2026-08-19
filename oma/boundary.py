"""The orchestrator that wires planner → policy → executor.

This is where the authority boundary is enforced end to end: the planner only
proposes, the policy decides, and the executor runs authorized actions only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from .actions import Action, Decision, Verdict
from .executor import Executor, World
from .planner import HeuristicPlanner, Planner
from .policy import Policy, PolicyEngine


@dataclass
class PlannedAction:
    """A proposed action together with its decision and execution result."""

    action: Action
    decision: Decision
    executed: bool = False
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "decision": self.decision.to_dict(),
            "executed": self.executed,
            "result": self.result,
        }


@dataclass
class RunResult:
    """A full, auditable transcript of one boundary run."""

    goal: str
    planned: List[PlannedAction] = field(default_factory=list)
    world: Optional[Dict[str, Any]] = None

    @property
    def summary(self) -> Dict[str, int]:
        counts = {v.value: 0 for v in Verdict}
        executed = 0
        for pa in self.planned:
            counts[pa.decision.verdict.value] += 1
            executed += int(pa.executed)
        counts["executed"] = executed
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "summary": self.summary,
            "planned": [pa.to_dict() for pa in self.planned],
            "world": self.world,
        }


class AuthorityBoundary:
    """Runs a goal through the propose → decide → execute pipeline."""

    def __init__(
        self,
        planner: Planner | None = None,
        policy: Policy | None = None,
        world: World | None = None,
    ) -> None:
        self.planner = planner or HeuristicPlanner()
        self.engine = PolicyEngine(policy)
        self.executor = Executor(world)

    def run(self, goal: str, approvals: Optional[Iterable[str]] = None) -> RunResult:
        """Plan and (where authorized) execute.

        ``approvals`` is the set of action ids a human has explicitly approved.
        An action whose verdict is ``REQUIRE_APPROVAL`` only executes if its id
        is in ``approvals``. Actions that are ``ALLOW`` execute automatically;
        ``DENY`` actions never execute.
        """

        approved: Set[str] = set(approvals or ())
        result = RunResult(goal=goal)

        for action in self.planner.propose(goal):
            decision = self.engine.evaluate(action)
            planned = PlannedAction(action=action, decision=decision)

            should_execute = decision.verdict is Verdict.ALLOW or (
                decision.verdict is Verdict.REQUIRE_APPROVAL
                and action.id in approved
            )
            if should_execute:
                effective = (
                    decision
                    if decision.verdict is Verdict.ALLOW
                    else Decision(Verdict.ALLOW, decision.reasons + ["human approved"])
                )
                planned.result = self.executor.execute(action, effective)
                planned.executed = True

            result.planned.append(planned)

        result.world = self.executor.world.snapshot()
        return result
