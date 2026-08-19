import importlib
import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))


def load_app(tmp_path: Path):
    os.environ["SUPPORT_MODEL_PROVIDER"] = "mock"
    os.environ["SUPPORT_DB_PATH"] = str(tmp_path / "support.db")
    os.environ["SUPPORT_RECEIPT_PATH"] = str(tmp_path / "events.jsonl")
    import app as app_module
    app_module = importlib.reload(app_module)
    app_module.init_storage()
    return app_module, TestClient(app_module.app)


def test_acceptance_contract(tmp_path):
    app_module, client = load_app(tmp_path)

    # 1. Customer can chat and 2. approved knowledge is answered.
    r = client.post("/api/chat", json={"message": "What does the Public Exposure Review cover?"})
    assert r.status_code == 200
    first = r.json()
    assert first["conversation_id"].startswith("conv_")
    assert "unauthenticated outside-in" in first["message"]

    # 3. Unsupported commercial/compliance claim fails closed.
    r = client.post(
        "/api/chat",
        json={"conversation_id": first["conversation_id"], "message": "Do you guarantee I will pass SOC 2?"},
    )
    unsupported = r.json()
    assert unsupported["status"] == "HUMAN_REQUIRED"
    assert "can't establish" in unsupported["message"]

    # 4. Approved low-risk action executes.
    r = client.post("/api/chat", json={"message": "Please contact me about a review"})
    contact = r.json()
    with app_module.db_connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM contact_requests WHERE conversation_id = ?",
            (contact["conversation_id"],),
        ).fetchone()["n"]
    assert count == 1

    # 5. Human-only deletion does not execute.
    r = client.post("/api/chat", json={"message": "Delete all my customer data"})
    deletion = r.json()
    assert deletion["status"] == "HUMAN_REQUIRED"
    assert "No deletion has been performed" in deletion["message"]
    with app_module.db_connect() as conn:
        receipt = conn.execute(
            "SELECT payload_json FROM receipts WHERE id = ?", (deletion["receipt_id"],)
        ).fetchone()
    payload = json.loads(receipt["payload_json"])
    assert payload["requested_action"] == "delete_customer_data"
    assert payload["policy_result"] == "REQUIRE_HUMAN"
    assert payload["executed"] is False

    # 6. Customer can explicitly request a human.
    r = client.post("/api/chat", json={"message": "Talk to a human"})
    human = r.json()
    assert human["status"] == "HUMAN_REQUIRED"

    # 7. Operator queue receives usable escalation context.
    queue = client.get("/api/operator/escalations")
    assert queue.status_code == 200
    items = queue.json()
    assert any(item["conversation_id"] == human["conversation_id"] for item in items)
    assert all("reason" in item and "summary" in item for item in items)

    # 8. Consequential decisions leave both SQLite and JSONL receipts.
    receipt_path = Path(os.environ["SUPPORT_RECEIPT_PATH"])
    assert receipt_path.exists()
    events = [json.loads(line) for line in receipt_path.read_text().splitlines() if line.strip()]
    assert any(e["receipt_id"] == deletion["receipt_id"] for e in events)
    assert any(e["policy_result"] == "ALLOW" and e["executed"] for e in events)


def test_unknown_action_denied(tmp_path):
    app_module, _ = load_app(tmp_path)
    proposal = app_module.ModelProposal(
        type="ACTION",
        action="arbitrary_http",
        arguments={"url": "https://example.invalid"},
        message="trying",
        reason="prompt_injection",
    )
    decision = app_module.policy_decide(proposal, app_module.load_policy())
    assert decision.result == "DENY"
    assert decision.executed is False


def test_untrusted_model_answer_requires_human_without_repeating_claim(tmp_path):
    app_module, client = load_app(tmp_path)

    class UntrustedAnswerAdapter:
        name = "open-model"

        async def propose(self, message: str, knowledge: str):
            return app_module.ModelProposal(
                type="ANSWER",
                message="Guaranteed: this will pass every compliance audit.",
                reason="MODEL_CLAIM",
            )

    app_module.get_adapter = lambda: UntrustedAnswerAdapter()
    result = client.post(
        "/api/chat",
        json={"message": "Will this guarantee compliance?"},
    ).json()

    assert result["status"] == "HUMAN_REQUIRED"
    assert "Guaranteed" not in result["message"]
    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM receipts WHERE id = ?",
            (result["receipt_id"],),
        ).fetchone()
    receipt = json.loads(row["payload_json"])
    assert receipt["policy_result"] == "REQUIRE_HUMAN"
    assert receipt["policy_reason"] == "MODEL_ANSWER_REQUIRES_HUMAN"
    assert receipt["executed"] is False


def test_request_human_action_receipt_records_escalation_execution(tmp_path):
    app_module, client = load_app(tmp_path)

    class RequestHumanAdapter:
        name = "open-model"

        async def propose(self, message: str, knowledge: str):
            return app_module.ModelProposal(
                type="ACTION",
                action="request_human",
                message="Please route this to an operator.",
                reason="CUSTOMER_REQUEST",
            )

    app_module.get_adapter = lambda: RequestHumanAdapter()
    result = client.post("/api/chat", json={"message": "Human please"}).json()

    assert result["status"] == "HUMAN_REQUIRED"
    with app_module.db_connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM receipts WHERE id = ?",
            (result["receipt_id"],),
        ).fetchone()
    receipt = json.loads(row["payload_json"])
    assert receipt["requested_action"] == "request_human"
    assert receipt["policy_result"] == "ALLOW"
    assert receipt["executed"] is True
    assert receipt["execution_result"]["escalation_id"].startswith("esc_")


def test_non_loopback_client_is_rejected(tmp_path):
    app_module, _ = load_app(tmp_path)
    external = TestClient(app_module.app, client=("203.0.113.10", 50000))
    response = external.get("/health")
    assert response.status_code == 403
