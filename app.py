from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SUPPORT_DB_PATH", BASE_DIR / "support.db"))
RECEIPT_PATH = Path(os.getenv("SUPPORT_RECEIPT_PATH", BASE_DIR / "receipts" / "events.jsonl"))
POLICY_PATH = BASE_DIR / "policy.yaml"
KNOWLEDGE_PATH = BASE_DIR / "knowledge" / "approved.md"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class ModelProposal(BaseModel):
    type: Literal["ANSWER", "ACTION", "ESCALATE"]
    message: str
    action: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    status: str
    receipt_id: str


@dataclass
class PolicyDecision:
    action: str | None
    result: Literal["ALLOW", "REQUIRE_HUMAN", "DENY", "ANSWER"]
    executed: bool
    reason: str


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def load_policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def load_knowledge() -> str:
    return KNOWLEDGE_PATH.read_text(encoding="utf-8")


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_storage() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              created_ms INTEGER NOT NULL,
              updated_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              conversation_id TEXT NOT NULL,
              actor TEXT NOT NULL,
              body TEXT NOT NULL,
              created_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contact_requests (
              id TEXT PRIMARY KEY,
              conversation_id TEXT NOT NULL,
              name TEXT,
              email TEXT,
              created_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS escalations (
              id TEXT PRIMARY KEY,
              conversation_id TEXT NOT NULL,
              reason TEXT NOT NULL,
              requested_action TEXT,
              summary TEXT NOT NULL,
              status TEXT NOT NULL,
              created_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS receipts (
              id TEXT PRIMARY KEY,
              conversation_id TEXT NOT NULL,
              event TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_ms INTEGER NOT NULL
            );
            """
        )


def ensure_conversation(conversation_id: str | None) -> str:
    cid = conversation_id or new_id("conv")
    t = now_ms()
    with db_connect() as conn:
        row = conn.execute("SELECT id FROM conversations WHERE id = ?", (cid,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO conversations(id,status,created_ms,updated_ms) VALUES(?,?,?,?)",
                (cid, "OPEN", t, t),
            )
    return cid


def save_message(conversation_id: str, actor: str, body: str) -> None:
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO messages(id,conversation_id,actor,body,created_ms) VALUES(?,?,?,?,?)",
            (new_id("msg"), conversation_id, actor, body, now_ms()),
        )
        conn.execute(
            "UPDATE conversations SET updated_ms = ? WHERE id = ?",
            (now_ms(), conversation_id),
        )


def append_receipt(conversation_id: str, event: str, payload: dict[str, Any]) -> str:
    receipt_id = new_id("rct")
    record = {
        "receipt_id": receipt_id,
        "timestamp_ms": now_ms(),
        "conversation_id": conversation_id,
        "event": event,
        **payload,
    }
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO receipts(id,conversation_id,event,payload_json,created_ms) VALUES(?,?,?,?,?)",
            (receipt_id, conversation_id, event, json.dumps(record, sort_keys=True), record["timestamp_ms"]),
        )
    with RECEIPT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return receipt_id


def create_escalation(conversation_id: str, reason: str, action: str | None, summary: str) -> str:
    escalation_id = new_id("esc")
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO escalations(id,conversation_id,reason,requested_action,summary,status,created_ms) VALUES(?,?,?,?,?,?,?)",
            (escalation_id, conversation_id, reason, action, summary, "OPEN", now_ms()),
        )
        conn.execute("UPDATE conversations SET status = 'HUMAN_REQUIRED', updated_ms = ? WHERE id = ?", (now_ms(), conversation_id))
    return escalation_id


def create_contact_request(conversation_id: str, arguments: dict[str, Any]) -> str:
    req_id = new_id("contact")
    name = str(arguments.get("name") or "").strip()[:200]
    email = str(arguments.get("email") or "").strip()[:320]
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO contact_requests(id,conversation_id,name,email,created_ms) VALUES(?,?,?,?,?)",
            (req_id, conversation_id, name or None, email or None, now_ms()),
        )
    return req_id


class ModelAdapter:
    name = "base"

    async def propose(self, message: str, knowledge: str) -> ModelProposal:
        raise NotImplementedError


class MockAdapter(ModelAdapter):
    """Deterministic adapter for local experiment and safety acceptance tests."""

    name = "mock"

    async def propose(self, message: str, knowledge: str) -> ModelProposal:
        text = message.lower().strip()
        if any(x in text for x in ("live agent", "human", "talk to someone", "agent please")):
            return ModelProposal(type="ESCALATE", message="I've passed this to a human for review.", reason="CUSTOMER_REQUEST")
        if "delete" in text and any(x in text for x in ("data", "account", "everything")):
            return ModelProposal(
                type="ACTION",
                action="delete_customer_data",
                arguments={},
                message="This deletion request requires human review.",
                reason="CONSEQUENTIAL_ACTION",
            )
        if any(x in text for x in ("contact me", "call me", "follow up", "get in touch")):
            return ModelProposal(
                type="ACTION",
                action="create_contact_request",
                arguments={},
                message="I've created a contact request for human follow-up.",
                reason="CONTACT_REQUEST",
            )
        if "soc 2" in text and any(x in text for x in ("guarantee", "pass", "certif")):
            return ModelProposal(type="ESCALATE", message="I can't establish that guarantee from the approved support context.", reason="UNSUPPORTED_CLAIM")
        if "price" in text or "cost" in text or "1,900" in text:
            return ModelProposal(type="ANSWER", message="The Public Exposure Review is EUR 1,900 excluding VAT.", reason="SUPPORTED_KNOWLEDGE")
        if "public exposure review" in text or "what do you sell" in text or "what does" in text:
            return ModelProposal(
                type="ANSWER",
                message="The Public Exposure Review is a fixed, bounded, unauthenticated outside-in review of one authorised public-facing system. It is human-led with manual review, and it is not a penetration test, automated vulnerability scan, or continuous EASM.",
                reason="SUPPORTED_KNOWLEDGE",
            )
        return ModelProposal(type="ESCALATE", message="I can't establish that from the approved support context, so this needs human review.", reason="UNKNOWN")


SYSTEM_PROMPT = """You are a bounded support worker. Use only SUPPORT_CONTEXT for factual claims about WitnessOps.
Return JSON only with keys: type, message, action, arguments, reason.
type must be ANSWER, ACTION, or ESCALATE.
Allowed action names the model may request are create_contact_request, request_human, delete_customer_data.
Never invent prices, scope, guarantees, delivery commitments, compliance outcomes, discounts, or customer-specific terms.
If support context does not establish an answer, use ESCALATE.
Never claim an action executed; the policy controller decides execution after your proposal.
"""


class OpenAICompatibleAdapter(ModelAdapter):
    def __init__(self, name: str, base_url: str, model: str, token: str | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.token = token

    async def propose(self, message: str, knowledge: str) -> ModelProposal:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + "\n\nSUPPORT_CONTEXT:\n" + knowledge},
                {"role": "user", "content": message},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        try:
            return ModelProposal.model_validate_json(raw)
        except ValidationError as exc:
            raise RuntimeError("model returned invalid proposal schema") from exc


def get_adapter() -> ModelAdapter:
    provider = os.getenv("SUPPORT_MODEL_PROVIDER", "mock").strip().lower()
    model = os.getenv("SUPPORT_MODEL", "").strip()
    if provider == "mock":
        return MockAdapter()
    if provider == "ollama":
        return OpenAICompatibleAdapter(
            "ollama",
            os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
            model or "llama3.2",
        )
    if provider == "huggingface":
        token = os.getenv("HF_TOKEN")
        if not token:
            raise RuntimeError("HF_TOKEN is required for huggingface provider")
        if not model:
            raise RuntimeError("SUPPORT_MODEL is required for huggingface provider")
        return OpenAICompatibleAdapter(
            "huggingface",
            os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1"),
            model,
            token,
        )
    raise RuntimeError(f"unsupported SUPPORT_MODEL_PROVIDER: {provider}")


def policy_decide(
    proposal: ModelProposal,
    policy: dict[str, Any],
    *,
    trusted_answer: bool = False,
) -> PolicyDecision:
    if proposal.type == "ANSWER":
        if trusted_answer:
            return PolicyDecision(None, "ANSWER", False, proposal.reason)
        return PolicyDecision(None, "REQUIRE_HUMAN", False, "MODEL_ANSWER_REQUIRES_HUMAN")
    if proposal.type == "ESCALATE":
        return PolicyDecision(proposal.action, "REQUIRE_HUMAN", False, proposal.reason or "MODEL_ESCALATION")
    action = proposal.action or ""
    rule = policy.get("actions", {}).get(action)
    if rule is None:
        return PolicyDecision(action, "DENY", False, "ACTION_NOT_ALLOWLISTED")
    execution = rule.get("execution")
    if execution == "AUTO":
        return PolicyDecision(action, "ALLOW", False, "POLICY_AUTO")
    if execution == "HUMAN_ONLY":
        return PolicyDecision(action, "REQUIRE_HUMAN", False, "POLICY_HUMAN_ONLY")
    return PolicyDecision(action, "DENY", False, "POLICY_DEFAULT_DENY")


app = FastAPI(title="WitnessOps Bounded Support Agent", version="0.1.0")

_LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "testclient"}


@app.middleware("http")
async def loopback_only(request: Request, call_next):
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK_CLIENTS:
        return JSONResponse(
            status_code=403,
            content={"detail": "experimental application is restricted to loopback clients"},
        )
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    init_storage()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "experimental", "provider": get_adapter().name}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    cid = ensure_conversation(req.conversation_id)
    save_message(cid, "customer", req.message)
    adapter = get_adapter()
    knowledge = load_knowledge()
    try:
        proposal = await adapter.propose(req.message, knowledge)
    except Exception as exc:
        escalation_id = create_escalation(cid, "MODEL_ERROR", None, "Model execution failed; human review required.")
        receipt_id = append_receipt(cid, "MODEL_FAILURE", {"actor": "support-controller", "provider": adapter.name, "executed": False, "error_type": type(exc).__name__, "escalation_id": escalation_id})
        reply = "I couldn't safely complete that request, so I've passed it for human review."
        save_message(cid, "assistant", reply)
        return ChatResponse(conversation_id=cid, message=reply, status="HUMAN_REQUIRED", receipt_id=receipt_id)

    decision = policy_decide(
        proposal,
        load_policy(),
        trusted_answer=adapter.name == "mock",
    )
    status = "OPEN"
    reply = proposal.message
    execution_result: dict[str, Any] = {}

    if decision.result == "ALLOW" and decision.action == "create_contact_request":
        contact_id = create_contact_request(cid, proposal.arguments)
        decision.executed = True
        execution_result = {"contact_request_id": contact_id}
    elif decision.result == "ALLOW" and decision.action == "request_human":
        escalation_id = create_escalation(cid, "CUSTOMER_REQUEST", decision.action, proposal.message)
        decision.executed = True
        status = "HUMAN_REQUIRED"
        execution_result = {"escalation_id": escalation_id}
    elif decision.result == "REQUIRE_HUMAN":
        escalation_id = create_escalation(cid, decision.reason, decision.action, proposal.message)
        status = "HUMAN_REQUIRED"
        execution_result = {"escalation_id": escalation_id}
        if decision.action == "delete_customer_data":
            reply = "I've passed this deletion request for human review. No deletion has been performed."
        elif decision.reason == "MODEL_ANSWER_REQUIRES_HUMAN":
            reply = "I can't independently verify that model answer, so I've passed it for human review."
    elif decision.result == "DENY":
        status = "DENIED"
        reply = "That action is not authorised for this support worker and was not executed."

    receipt_id = append_receipt(
        cid,
        "ACTION_DECISION",
        {
            "actor": "support-controller",
            "provider": adapter.name,
            "model_proposal": proposal.model_dump(),
            "requested_action": decision.action,
            "policy_result": decision.result,
            "policy_reason": decision.reason,
            "executed": decision.executed,
            "execution_result": execution_result,
        },
    )
    save_message(cid, "assistant", reply)
    return ChatResponse(conversation_id=cid, message=reply, status=status, receipt_id=receipt_id)


@app.get("/api/operator/escalations")
def escalations() -> list[dict[str, Any]]:
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT id,conversation_id,reason,requested_action,summary,status,created_ms FROM escalations WHERE status='OPEN' ORDER BY created_ms ASC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/operator/conversations/{conversation_id}")
def conversation(conversation_id: str) -> dict[str, Any]:
    with db_connect() as conn:
        conv = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        messages = conn.execute("SELECT actor,body,created_ms FROM messages WHERE conversation_id = ? ORDER BY created_ms", (conversation_id,)).fetchall()
    return {"conversation": dict(conv), "messages": [dict(m) for m in messages]}


CUSTOMER_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Bounded Support v0</title></head>
<body><main style='max-width:720px;margin:40px auto;font-family:sans-serif'><h1>Bounded Support v0</h1><p>Experimental, non-production.</p><div id='log'></div><form id='f'><input id='m' style='width:75%' placeholder='Ask a support question' required><button>Send</button></form><button id='human'>Talk to a human</button></main><script>
let cid=null;const log=document.getElementById('log');
function add(actor,text){const p=document.createElement('p');const b=document.createElement('b');b.textContent=actor+': ';p.append(b,document.createTextNode(text));log.append(p);}
async function send(message){add('You',message);const r=await fetch('/api/chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({message,conversation_id:cid})});const d=await r.json();cid=d.conversation_id;add('Support',d.message);}
document.getElementById('f').onsubmit=e=>{e.preventDefault();const m=document.getElementById('m');send(m.value);m.value='';};document.getElementById('human').onclick=()=>send('Talk to a human');</script></body></html>"""

OPERATOR_HTML = """<!doctype html><html><head><meta charset='utf-8'><title>Operator Queue</title></head><body><main style='max-width:900px;margin:40px auto;font-family:sans-serif'><h1>Human Queue</h1><div id='q'>Loading…</div></main><script>
function line(label,value){const p=document.createElement('p');p.textContent=label+value;return p;}
async function load(){const r=await fetch('/api/operator/escalations');const d=await r.json();const q=document.getElementById('q');q.replaceChildren();if(!d.length){q.append(line('','No open escalations.'));return;}for(const x of d){const a=document.createElement('article');a.style='border:1px solid #ccc;padding:12px;margin:12px 0';const id=document.createElement('b');id.textContent=x.conversation_id;a.append(id,line('Reason: ',x.reason),line('Requested action: ',x.requested_action||'none'),line('',x.summary));q.append(a);}}
load();</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def customer_ui() -> str:
    return CUSTOMER_HTML


@app.get("/operator", response_class=HTMLResponse)
def operator_ui() -> str:
    return OPERATOR_HTML
