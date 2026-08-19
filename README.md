# Open Model Authority Boundary

A small open-model experiment showing how an AI can **propose** actions while a
deterministic **policy** retains **execution authority**.

The central idea is an *authority boundary*: a (potentially untrusted) model may
reason about a goal and propose a plan of concrete actions, but it can never
execute anything itself. Every proposed action is passed through a deterministic
policy engine that decides whether it is allowed, denied, or requires human
approval. Only actions the policy authorizes are ever handed to the executor.

```
   goal ──▶ Planner (AI / heuristic)  ──proposes──▶  Actions
                                                       │
                                                       ▼
                                          Deterministic Policy Engine
                                          (ALLOW / DENY / REQUIRE_APPROVAL)
                                                       │
                                             authorized actions only
                                                       ▼
                                                   Executor
```

The planner is intentionally pluggable. The default `HeuristicPlanner` is fully
offline and deterministic so the whole system runs anywhere with no GPU or
network. An optional `TransformersPlanner` (guarded import) can drive proposals
with a real open model when the `transformers` extra is installed.

## Project layout

| Path | Purpose |
| --- | --- |
| `oma/actions.py` | Action + decision data models |
| `oma/policy.py` | Deterministic policy engine (the authority boundary) |
| `oma/planner.py` | Planner protocol, `HeuristicPlanner`, optional transformers planner |
| `oma/executor.py` | Sandboxed executor over an in-memory `World` |
| `oma/boundary.py` | Orchestrator wiring planner → policy → executor |
| `oma/api.py` | FastAPI service + web UI |
| `oma/cli.py` | Command-line demo |
| `oma/web/index.html` | Single-page UI |
| `tests/` | pytest suite |

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

# Run the test suite
pytest -q

# Try the CLI
oma "email the quarterly report to alice@corp.com then delete the temp cache"

# Run the web service (UI at http://localhost:8000)
uvicorn oma.api:app --host 0.0.0.0 --port 8000
```

## Why this matters

Letting a language model directly call tools couples *reasoning* with
*authority*. This project deliberately separates the two: reasoning can be as
creative (or as compromised) as it likes, but a small, auditable, deterministic
policy is the only thing that can grant execution. Every run produces a full
transcript of proposals, decisions, and reasons, so the boundary is inspectable.
