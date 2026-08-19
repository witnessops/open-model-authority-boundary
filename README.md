# Open Model Authority Boundary

A small open-model application showing one practical rule: the model may propose an action, but deterministic policy retains execution authority.

This is a clean public snapshot of the WitnessOps `AI-LAB-EXP-001` Bounded Support Agent experiment. It is experimental, local-only, and not production infrastructure.

## The boundary

```text
customer message
      |
      v
bounded context -> model proposal -> schema validation
                                      |
                                      v
                           deterministic policy gate
                           ALLOW | REQUIRE_HUMAN | DENY
                                      |
                                      v
                        deterministic handler -> receipt
```

The proposal source is replaceable. The same controller accepts proposals from a Hugging Face or Ollama-compatible open-model endpoint, while the default `mock` adapter makes the authority boundary reproducible without credentials, network access, or a GPU. Text answers from a non-mock model require human review; only the deterministic acceptance adapter may answer directly.

## 30-second demo

Python 3.11+ is required; CI runs Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python demo_control_paths.py
```

The demo exercises three control outcomes through the real application controller:

| Case | Policy result | Executed |
| --- | --- | --- |
| Low-risk contact request | `ALLOW` | `true` |
| Customer-data deletion | `REQUIRE_HUMAN` | `false` |
| Unknown `arbitrary_http` action | `DENY` | `false` |

Example output is committed at [`receipts/sample-control-paths.jsonl`](receipts/sample-control-paths.jsonl). Receipt identifiers and timestamps are intentionally run-specific.

## Run the application

```bash
cp .env.example .env
uvicorn app:app --reload
```

- Customer UI: <http://127.0.0.1:8000/>
- Operator queue: <http://127.0.0.1:8000/operator>

The prototype rejects non-loopback clients. It is not a network or multi-user service.

The default provider is deterministic and offline:

```bash
SUPPORT_MODEL_PROVIDER=mock uvicorn app:app --reload
```

To use an Ollama-compatible local model:

```bash
SUPPORT_MODEL_PROVIDER=ollama \
SUPPORT_MODEL=llama3.2 \
uvicorn app:app --reload
```

To use a Hugging Face OpenAI-compatible endpoint:

```bash
SUPPORT_MODEL_PROVIDER=huggingface \
HF_TOKEN=... \
SUPPORT_MODEL=your-open-model-id \
uvicorn app:app --reload
```

Changing the proposal source does not change the schema, policy, handler, or receipt path. The deterministic demo verifies that controller contract; it does not establish that any model is safe or useful.

## Verification

```bash
pytest -q
```

The acceptance suite checks that:

1. supported knowledge can be answered;
2. the deterministic acceptance adapter routes a known unsupported claim to a human;
3. an allowlisted low-risk action executes;
4. a human-only deletion does not execute;
5. an unknown action is denied;
6. a customer can demand a human;
7. the operator queue receives usable context; and
8. consequential decisions leave SQLite and JSONL receipts.

Additional hostile-adapter checks verify that an untrusted model-labelled answer is withheld for human review, an allowed human-escalation action is recorded as executed, and non-loopback clients are rejected.

GitHub Actions runs both `pytest -q` and the deterministic demo on every pull request and push to `main`.

## Project files

| Path | Purpose |
| --- | --- |
| `app.py` | Proposal adapters, schema validation, policy controller, deterministic handlers, HTTP API, and minimal UIs |
| `policy.yaml` | Default-deny action policy |
| `knowledge/approved.md` | Bounded support context |
| `demo_control_paths.py` | Deterministic `ALLOW` / `REQUIRE_HUMAN` / `DENY` demonstration |
| `tests/test_acceptance.py` | Acceptance contract |
| `receipts/sample-control-paths.jsonl` | Reconstructable sample output |

## Limits

This prototype is not production-ready and does not prove that an open model is safe. The policy gate controls side-effect execution; it does not independently verify the truth of a model's text answers. It grants no autonomous production authority and is not a general AI governance framework. It does not prove safety against a compromised host, runtime, policy file, or handler. Receipts support reconstruction of application decisions; they do not independently prove every property of the model, provider, operating system, or surrounding infrastructure.

Licensed under Apache-2.0.
