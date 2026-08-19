from fastapi.testclient import TestClient

from oma.api import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_index_serves_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Authority Boundary" in resp.text


def test_policy_endpoint():
    resp = client.get("/api/policy")
    assert resp.status_code == 200
    body = resp.json()
    assert "run_shell" in body["forbidden_kinds"]
    assert "corp.com" in body["email_domain_allowlist"]


def test_plan_endpoint_denies_forbidden_and_allows_reads():
    resp = client.post(
        "/api/plan",
        json={"goal": "read workspace/report.txt and run a shell script"},
    )
    assert resp.status_code == 200
    data = resp.json()
    kinds = {p["action"]["kind"]: p for p in data["planned"]}
    assert kinds["read_file"]["executed"] is True
    assert kinds["run_shell"]["decision"]["verdict"] == "deny"
    assert kinds["run_shell"]["executed"] is False


def test_plan_endpoint_honors_approvals():
    first = client.post(
        "/api/plan", json={"goal": "email the report to alice@corp.com"}
    ).json()
    email = next(p for p in first["planned"] if p["action"]["kind"] == "send_email")
    assert email["executed"] is False

    approved = client.post(
        "/api/plan",
        json={
            "goal": "email the report to alice@corp.com",
            "approvals": [email["action"]["id"]],
        },
    ).json()
    email2 = next(
        p for p in approved["planned"] if p["action"]["kind"] == "send_email"
    )
    assert email2["executed"] is True
