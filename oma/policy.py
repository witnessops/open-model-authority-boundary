"""The deterministic policy engine.

This module is the authority boundary. Whatever a planner proposes, the
policy engine alone decides whether an action may execute. The logic here is
intentionally simple, ordered, and free of any model inference so that its
behavior is fully predictable and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

from .actions import Action, ActionKind, Decision, Verdict


@dataclass
class Policy:
    """Declarative configuration for :class:`PolicyEngine`.

    Rules are deliberately explicit. Anything not affirmatively permitted is
    denied by default.
    """

    # Kinds that may be auto-approved when their per-kind checks pass.
    allowed_kinds: Set[ActionKind] = field(
        default_factory=lambda: {ActionKind.READ_FILE, ActionKind.HTTP_GET}
    )
    # Kinds that are permitted but always require explicit human approval.
    approval_kinds: Set[ActionKind] = field(
        default_factory=lambda: {
            ActionKind.WRITE_FILE,
            ActionKind.DELETE_FILE,
            ActionKind.SEND_EMAIL,
        }
    )
    # Kinds that are never permitted under any circumstances.
    forbidden_kinds: Set[ActionKind] = field(
        default_factory=lambda: {ActionKind.RUN_SHELL, ActionKind.TRANSFER_FUNDS}
    )

    # Filesystem guardrails: only paths under an allowed prefix are eligible,
    # and denied prefixes are rejected outright.
    path_allowlist: List[str] = field(default_factory=lambda: ["workspace/"])
    path_denylist: List[str] = field(
        default_factory=lambda: ["workspace/secrets/", "/etc/", ".ssh"]
    )

    # Email guardrail: recipients must be on an allowed domain.
    email_domain_allowlist: List[str] = field(default_factory=lambda: ["corp.com"])

    # HTTP guardrail: hosts must be on an allowed list.
    http_host_allowlist: List[str] = field(
        default_factory=lambda: ["api.corp.com", "docs.corp.com"]
    )

    @classmethod
    def default(cls) -> "Policy":
        return cls()


class PolicyEngine:
    """Evaluates proposed actions against a :class:`Policy`.

    The engine never mutates state and never executes anything; it only
    returns a :class:`Decision`.
    """

    def __init__(self, policy: Policy | None = None) -> None:
        self.policy = policy or Policy.default()

    def evaluate(self, action: Action) -> Decision:
        p = self.policy
        kind = action.kind

        if kind in p.forbidden_kinds:
            return Decision(
                Verdict.DENY,
                [f"action kind '{kind.value}' is forbidden by policy"],
            )

        checker = _KIND_CHECKS.get(kind, self._check_generic)
        return checker(self, action)

    # -- per-kind checks -------------------------------------------------

    def _base_verdict(self, kind: ActionKind) -> Verdict:
        if kind in self.policy.approval_kinds:
            return Verdict.REQUIRE_APPROVAL
        if kind in self.policy.allowed_kinds:
            return Verdict.ALLOW
        return Verdict.DENY

    def _check_generic(self, action: Action) -> Decision:
        verdict = self._base_verdict(action.kind)
        if verdict is Verdict.DENY:
            return Decision(
                verdict, [f"action kind '{action.kind.value}' is not permitted"]
            )
        return Decision(verdict, ["kind permitted by policy"])

    def _check_path(self, action: Action) -> Decision:
        path = str(action.params.get("path", ""))
        reasons: List[str] = []
        if not path:
            return Decision(Verdict.DENY, ["missing required 'path' parameter"])

        for denied in self.policy.path_denylist:
            if denied in path:
                return Decision(
                    Verdict.DENY,
                    [f"path '{path}' matches denied prefix '{denied}'"],
                )

        if not any(path.startswith(pre) for pre in self.policy.path_allowlist):
            return Decision(
                Verdict.DENY,
                [
                    f"path '{path}' is outside the allowed roots "
                    f"{self.policy.path_allowlist}"
                ],
            )

        verdict = self._base_verdict(action.kind)
        reasons.append(f"path '{path}' is within an allowed root")
        if verdict is Verdict.REQUIRE_APPROVAL:
            reasons.append("mutating file action requires human approval")
        return Decision(verdict, reasons)

    def _check_email(self, action: Action) -> Decision:
        to = str(action.params.get("to", ""))
        if "@" not in to:
            return Decision(Verdict.DENY, [f"invalid recipient '{to}'"])
        domain = to.rsplit("@", 1)[-1].lower()
        if domain not in {d.lower() for d in self.policy.email_domain_allowlist}:
            return Decision(
                Verdict.DENY,
                [
                    f"recipient domain '{domain}' is not on the allowlist "
                    f"{self.policy.email_domain_allowlist}"
                ],
            )
        return Decision(
            Verdict.REQUIRE_APPROVAL,
            [
                f"recipient domain '{domain}' is allowed",
                "outbound email requires human approval",
            ],
        )

    def _check_http(self, action: Action) -> Decision:
        url = str(action.params.get("url", ""))
        host = _host_from_url(url)
        if not host:
            return Decision(Verdict.DENY, [f"could not parse host from url '{url}'"])
        if host not in self.policy.http_host_allowlist:
            return Decision(
                Verdict.DENY,
                [
                    f"host '{host}' is not on the http allowlist "
                    f"{self.policy.http_host_allowlist}"
                ],
            )
        return Decision(Verdict.ALLOW, [f"host '{host}' is allowed for GET requests"])


def _host_from_url(url: str) -> str:
    without_scheme = url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].split(":", 1)[0].lower()


_KIND_CHECKS = {
    ActionKind.READ_FILE: PolicyEngine._check_path,
    ActionKind.WRITE_FILE: PolicyEngine._check_path,
    ActionKind.DELETE_FILE: PolicyEngine._check_path,
    ActionKind.SEND_EMAIL: PolicyEngine._check_email,
    ActionKind.HTTP_GET: PolicyEngine._check_http,
}
