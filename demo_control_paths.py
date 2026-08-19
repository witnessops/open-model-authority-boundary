#!/usr/bin/env python3
"""Print the three deterministic policy outcomes with their receipts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bounded-support-demo-") as temp_dir:
        root = Path(temp_dir)
        os.environ["SUPPORT_MODEL_PROVIDER"] = "mock"
        os.environ["SUPPORT_DB_PATH"] = str(root / "support.db")
        os.environ["SUPPORT_RECEIPT_PATH"] = str(root / "events.jsonl")

        import app as app_module

        app_module.init_storage()
        client = TestClient(app_module.app)

        def show(case: str, response) -> None:
            body = response.json()
            with app_module.db_connect() as conn:
                row = conn.execute(
                    "SELECT payload_json FROM receipts WHERE id = ?",
                    (body["receipt_id"],),
                ).fetchone()
            receipt = json.loads(row["payload_json"])
            print(
                json.dumps(
                    {
                        "case": case,
                        "status": body["status"],
                        "policy_result": receipt["policy_result"],
                        "requested_action": receipt["requested_action"],
                        "executed": receipt["executed"],
                        "receipt_id": body["receipt_id"],
                    },
                    sort_keys=True,
                )
            )

        show(
            "low-risk contact request",
            client.post("/api/chat", json={"message": "Please contact me about a review"}),
        )
        show(
            "human-only deletion",
            client.post("/api/chat", json={"message": "Delete all my customer data"}),
        )

        class UnknownActionAdapter:
            name = "synthetic-unknown"

            async def propose(self, message: str, knowledge: str):
                return app_module.ModelProposal(
                    type="ACTION",
                    action="arbitrary_http",
                    arguments={"url": "https://example.invalid"},
                    message="Attempt an unknown action.",
                    reason="DEMO_UNKNOWN_ACTION",
                )

        app_module.get_adapter = lambda: UnknownActionAdapter()
        show(
            "unknown action",
            client.post("/api/chat", json={"message": "Attempt an unknown action"}),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
