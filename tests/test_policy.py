from oma.actions import Action, ActionKind, Verdict
from oma.policy import Policy, PolicyEngine


def make_engine():
    return PolicyEngine(Policy.default())


def test_forbidden_kinds_are_denied():
    engine = make_engine()
    for kind in (ActionKind.RUN_SHELL, ActionKind.TRANSFER_FUNDS):
        decision = engine.evaluate(Action(kind, {}))
        assert decision.verdict is Verdict.DENY
        assert decision.reasons


def test_read_file_within_allowlist_is_allowed():
    engine = make_engine()
    decision = engine.evaluate(
        Action(ActionKind.READ_FILE, {"path": "workspace/report.txt"})
    )
    assert decision.verdict is Verdict.ALLOW


def test_read_file_outside_allowlist_is_denied():
    engine = make_engine()
    decision = engine.evaluate(Action(ActionKind.READ_FILE, {"path": "/etc/passwd"}))
    assert decision.verdict is Verdict.DENY


def test_secrets_path_is_denied_even_within_workspace():
    engine = make_engine()
    decision = engine.evaluate(
        Action(ActionKind.READ_FILE, {"path": "workspace/secrets/api_key"})
    )
    assert decision.verdict is Verdict.DENY


def test_write_and_delete_require_approval():
    engine = make_engine()
    for kind in (ActionKind.WRITE_FILE, ActionKind.DELETE_FILE):
        decision = engine.evaluate(Action(kind, {"path": "workspace/out.txt"}))
        assert decision.verdict is Verdict.REQUIRE_APPROVAL


def test_email_domain_allowlist():
    engine = make_engine()
    ok = engine.evaluate(Action(ActionKind.SEND_EMAIL, {"to": "alice@corp.com"}))
    assert ok.verdict is Verdict.REQUIRE_APPROVAL
    bad = engine.evaluate(Action(ActionKind.SEND_EMAIL, {"to": "eve@evil.com"}))
    assert bad.verdict is Verdict.DENY


def test_http_host_allowlist():
    engine = make_engine()
    ok = engine.evaluate(Action(ActionKind.HTTP_GET, {"url": "https://api.corp.com/x"}))
    assert ok.verdict is Verdict.ALLOW
    bad = engine.evaluate(Action(ActionKind.HTTP_GET, {"url": "https://evil.com/x"}))
    assert bad.verdict is Verdict.DENY


def test_missing_path_is_denied():
    engine = make_engine()
    decision = engine.evaluate(Action(ActionKind.READ_FILE, {}))
    assert decision.verdict is Verdict.DENY
