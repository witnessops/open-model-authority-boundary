"""Command-line entry point for the authority boundary demo."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .actions import Verdict
from .boundary import AuthorityBoundary
from .planner import load_planner


_SYMBOL = {
    Verdict.ALLOW: "[ALLOW]",
    Verdict.DENY: "[DENY] ",
    Verdict.REQUIRE_APPROVAL: "[APPRV]",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oma",
        description="Propose actions with an AI; a deterministic policy decides.",
    )
    parser.add_argument("goal", help="natural-language goal to plan for")
    parser.add_argument(
        "--planner",
        default="heuristic",
        help="planner to use (heuristic|transformers)",
    )
    parser.add_argument(
        "--approve",
        action="append",
        default=[],
        metavar="ACTION_ID",
        help="approve an action that requires approval (repeatable)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the full transcript as JSON"
    )
    return parser


def run(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    planner = load_planner(args.planner)
    boundary = AuthorityBoundary(planner=planner)
    result = boundary.run(args.goal, approvals=args.approve)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(f"Goal: {result.goal}\n")
    for pa in result.planned:
        symbol = _SYMBOL[pa.decision.verdict]
        status = "executed" if pa.executed else "not executed"
        print(f"{symbol} {pa.action.id} {pa.action.kind.value} ({status})")
        print(f"        proposed: {pa.action.params}")
        print(f"        rationale: {pa.action.rationale}")
        for reason in pa.decision.reasons:
            print(f"        policy: {reason}")
        if pa.result is not None:
            print(f"        result: {pa.result}")
        print()

    print(f"Summary: {result.summary}")
    return 0


def main() -> None:  # pragma: no cover - thin wrapper
    sys.exit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
