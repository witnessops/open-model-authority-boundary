import pytest

from oma.actions import Action, ActionKind, Decision, Verdict
from oma.boundary import AuthorityBoundary
from oma.executor import ExecutionError, Executor
from oma.planner import HeuristicPlanner


def test_denied_actions_never_execute():
    boundary = AuthorityBoundary()
    result = boundary.run("run a shell script and transfer funds to the vendor")
    denied = [p for p in result.planned if p.decision.verdict is Verdict.DENY]
    assert denied, "expected at least one denied action"
    assert all(not p.executed for p in denied)


def test_allow_actions_execute_automatically():
    boundary = AuthorityBoundary()
    result = boundary.run("read workspace/report.txt")
    read = [p for p in result.planned if p.action.kind is ActionKind.READ_FILE]
    assert read and read[0].executed
    assert read[0].result["ok"] is True


def test_require_approval_gated_on_human_approval():
    boundary = AuthorityBoundary()
    # Without approval: proposed but not executed.
    result = boundary.run("email the report to alice@corp.com")
    email = next(p for p in result.planned if p.action.kind is ActionKind.SEND_EMAIL)
    assert email.decision.verdict is Verdict.REQUIRE_APPROVAL
    assert not email.executed

    # With approval of that action id: executed.
    approved = boundary.run(
        "email the report to alice@corp.com", approvals=[email.action.id]
    )
    email2 = next(p for p in approved.planned if p.action.kind is ActionKind.SEND_EMAIL)
    assert email2.executed
    assert email2.result["delivered_to"] == "alice@corp.com"


def test_executor_refuses_unauthorized_action():
    executor = Executor()
    action = Action(ActionKind.DELETE_FILE, {"path": "workspace/tmp/cache"})
    with pytest.raises(ExecutionError):
        executor.execute(action, Decision(Verdict.DENY, ["nope"]))


def test_summary_counts_are_consistent():
    boundary = AuthorityBoundary()
    result = boundary.run(
        "read workspace/report.txt, email alice@corp.com, run a script"
    )
    s = result.summary
    total = s["allow"] + s["deny"] + s["require_approval"]
    assert total == len(result.planned)
    assert s["executed"] <= s["allow"] + s["require_approval"]


def test_heuristic_planner_always_proposes_something():
    planner = HeuristicPlanner()
    assert planner.propose("") 
    assert planner.propose("do something vague")
