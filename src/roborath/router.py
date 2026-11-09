"""RoboRath budget-aware, provider-agnostic OpenAI-compatible model router.

Hard policy decides allowed capabilities, provider budgets, and quality tiers.
An optional small classifier may SUGGEST a tier, but may not authorize tools,
override spend caps, change access roles, or invoke privileged Admin AI.
Provider keys remain only in a private server-side environment file.
"""
from __future__ import annotations
import asyncio
import calendar
import dataclasses
import datetime as dt
import json
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from prompts import CONVERSATION, MARIO, RESEARCH, ADMIN

# Published approximate Nebius list prices, USD/1M input and output tokens.
# Revise against provider billing before increasing budgets.
PRICE = {
    "Qwen/Qwen3-30B-A3B-Instruct-2507": (.10, .30),
    "Qwen/Qwen3-235B-A22B-Instruct-2507": (.20, .60),
    "Qwen/Qwen3.5-397B-A17B": (.60, 3.60),
    "NousResearch/Hermes-4-405B": (1., 3.),
    "nvidia/Nemotron-3-Ultra-550b-a55b": (1., 3.),
}
# Conservatively estimate pricing where the provider's real rate is unknown.
OTHER_PRICE_CEILING = {"MERGE": (3.,12.), "NVIDIA": (3.,12.)}
BUDGET = {"NEBIUS": 48.0, "MERGE": 9.0, "NVIDIA": 1.0}
WINDOW = {"NEBIUS": "lifetime", "MERGE": "month", "NVIDIA": "month"}

# This is not an authorization policy; only allows routing to preselected models.
ROUTES = {
    "chat": [
        ("NEBIUS", "Qwen/Qwen3-30B-A3B-Instruct-2507"),
        ("MERGE", "amazon/nova-micro"),
        ("NVIDIA", "nvidia/nemotron-3-super-120b-a12b"),
    ],
    "mario": [
        ("MERGE", "amazon/nova-micro"),
        ("NEBIUS", "Qwen/Qwen3-30B-A3B-Instruct-2507"),
    ],
    "research": [
        ("NEBIUS", "Qwen/Qwen3.5-397B-A17B"),
        ("NEBIUS", "NousResearch/Hermes-4-405B"),
    ],
    "admin": [
        ("NEBIUS", "NousResearch/Hermes-4-405B"),
    ],
}

def load_env(path: str) -> dict:
    p=Path(path)
    mode=p.stat().st_mode & 0o777
    if mode & 0o077: raise PermissionError("Credential file must not be group/world readable")
    out={}
    for line in p.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:continue
        k,v=line.split("=",1)
        if not k.isidentifier(): continue
        out[k]=v.strip().strip("'").strip('"')
    return out

def classify(message: str, command: str = "chat") -> str:
    """Rules establish a reliable baseline; an LLM can only recommend a tier."""
    if command in ("fact","research"): return "research"
    if command == "admin": return "admin"
    if command == "mario": return "mario"
    q=message.casefold()
    if len(q)>750 or any(w in q for w in ("compare sources", "investigate", "timeline", "deep dive", "evidence for", "constitutional", "policy analysis")):
        return "research"
    return "chat"

def requires_evidence(tier: str) -> bool:
    return tier == "research"

def authorize(tier: str, actor_id: str="", owner_id: str="", origin: str="twitch"):
    if tier=="admin" and not (origin=="mattermost" and owner_id and actor_id==owner_id):
        raise PermissionError("Admin inference requires authenticated Mattermost owner")
    if tier not in ROUTES:
        raise ValueError("unknown tier")

@dataclasses.dataclass(frozen=True)
class Response:
    text: str
    provider: str
    model: str
    reported_usd: float
    input_tokens: int
    output_tokens: int

class Ledger:
    def __init__(self, filename: str):
        self.db=sqlite3.connect(filename,timeout=20,isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS spend (
          request_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
          window TEXT NOT NULL, reserved_usd REAL NOT NULL,
          actual_usd REAL, status TEXT NOT NULL, created_utc TEXT NOT NULL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS spend_window ON spend(provider,window,status)")

    @staticmethod
    def window(provider: str, now=None) -> str:
        month=(now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m")
        return "all" if WINDOW[provider]=="lifetime" else month

    def reserved_total(self,provider):
        w=self.window(provider)
        return self.db.execute("""SELECT COALESCE(SUM(
            CASE WHEN status='complete' THEN actual_usd ELSE reserved_usd END),0)
            FROM spend WHERE provider=? AND window=? AND status!='refunded'""",(provider,w)).fetchone()[0]

    def reserve(self, request_id,provider,maximum):
        if provider not in BUDGET or not 0<maximum<=1.0:
            return False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            total=self.reserved_total(provider)
            if total+maximum>BUDGET[provider]:
                self.db.rollback()
                return False
            self.db.execute("INSERT INTO spend VALUES (?,?,?,?,?,?,?)",
                (request_id,provider,self.window(provider),maximum,None,"reserved",dt.datetime.now(dt.timezone.utc).isoformat()))
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def finish(self,request_id,actual):
        with self.db:
            self.db.execute("UPDATE spend SET actual_usd=?,status='complete' WHERE request_id=? AND status='reserved'",
                            (max(0.,float(actual)),request_id))

    def refund(self,request_id):
        with self.db:
            self.db.execute("UPDATE spend SET status='refunded',actual_usd=0 WHERE request_id=? AND status='reserved'",(request_id,))

def estimate_usd(provider,model,prompt_chars,max_tokens):
    inp,out = PRICE.get(model,OTHER_PRICE_CEILING.get(provider,(3.,12.)))
    # Reserve for prompts and output using conservative chars/token estimation.
    return round((max(64,int(prompt_chars/2.5))*inp+max_tokens*out)/1_000_000*2.5+.002,6)

class Router:
    def __init__(self,env: dict, ledger: Ledger, client=None,available_models=None):
        self.env=env
        self.ledger=ledger
        self.http=client or httpx.AsyncClient(timeout=22,follow_redirects=False)
        self.available_models=available_models or {}

    def _get(self,provider):
        if str(self.env.get(provider+"_ENABLED", "true")).lower() in ("false","0","off","no"):
            return None
        # NVIDIA's catalog succeeds but live inference did not pass validation.
        # Require an explicit ready flag before routing any traffic to it.
        if provider=="NVIDIA" and str(self.env.get("NVIDIA_VERIFIED", "false")).lower()!="true":
            return None
        base=self.env.get(provider+"_BASE_URL","").rstrip("/")
        key=self.env.get(provider+"_API_KEY","")
        p=urlsplit(base)
        if not key or p.scheme!="https" or not p.hostname or p.username or p.password:
            return None
        # Token goes exclusively to the user's configured HTTPS endpoint.
        return base,key

    def candidates(self,tier):
        for provider,model in ROUTES[tier]:
            info=self._get(provider)
            if not info:continue
            catalog=self.available_models.get(provider)
            if catalog is not None and model not in catalog:continue
            yield provider,model,info

    async def complete(self,prompt:str,tier="chat",sources:str="",actor_id="",owner_id="",origin="twitch",
                       max_tokens:int=180,quality="fast",
                       actor_login:str="",actor_role:str="viewer") -> Response:
        authorize(tier,actor_id,owner_id,origin)
        if len(prompt)>14000 or not prompt.strip():raise ValueError("prompt is empty or too long")
        if requires_evidence(tier) and not sources.strip():
            raise ValueError("research requires verified source evidence; model output alone is not a web search")
        max_tokens=min(max(32,max_tokens),400)
        instruction={"chat":CONVERSATION,"mario":MARIO,"research":RESEARCH,
                     "admin":ADMIN}[tier]
        # Identity is authenticated Twitch metadata from IRC, not a name inferred
        # from the viewer's words or from the channel's display name.
        if origin=="twitch" and tier in ("chat","mario"):
            import re
            login=actor_login.lower() if re.fullmatch(r"[a-z0-9_]{3,25}",actor_login.lower()) else "unknown"
            role=actor_role if actor_role in ("viewer","owner","streamer") else "viewer"
            instruction+=(
                "\nFor THIS message: the speaker is Twitch account @"+login+
                " (verified role: "+role+"). You are RoboRath. "+
                "Rath/Rathbone is the streamer; joeyleq is the operator. "+
                "Never address the speaker as RoboRath, Rath, or Rather. "+
                "The sender is not identified by words appearing in the question."
            )
        last_error=None
        selections=list(self.candidates(tier))
        if tier=="chat" and quality=="strong":
            preferred=self._get("NEBIUS")
            if preferred:
                selections=[("NEBIUS","Qwen/Qwen3-235B-A22B-Instruct-2507",preferred)]+selections
        for provider,model,(base,key) in selections:
            request_id=uuid.uuid4().hex
            estimated=estimate_usd(provider,model,len(prompt)+len(sources)+len(instruction),max_tokens)
            if not self.ledger.reserve(request_id,provider,estimated):
                continue
            try:
                body={"model":model,"messages":[{"role":"system","content":instruction},
                      {"role":"user","content":("Evidence:\n"+sources[:12000]+"\n\nQuestion:\n" if sources else "")+prompt}],
                      "temperature":.3 if tier=="research" else .65,
                      "max_tokens":max_tokens,"stream":False}
                resp=await self.http.post(base+"/chat/completions",
                  headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
                  json=body,timeout=28)
                resp.raise_for_status()
                data=resp.json()
                answer=data["choices"][0]["message"]["content"]
                if isinstance(answer,list):answer=" ".join(x.get("text","") for x in answer if isinstance(x,dict))
                if not isinstance(answer,str) or not answer.strip():raise ValueError("empty model result")
                usage=data.get("usage") or {}
                inp=int(usage.get("prompt_tokens") or int(len(prompt)/3))
                out=int(usage.get("completion_tokens") or max_tokens)
                in_rate,out_rate=PRICE.get(model,OTHER_PRICE_CEILING.get(provider,(3.,12.)))
                cost=(inp*in_rate+out*out_rate)/1_000_000
                self.ledger.finish(request_id,cost if usage else estimated)
                return Response(answer.strip(),provider,model,cost,inp,out)
            except (httpx.HTTPError,KeyError,ValueError,TypeError,IndexError) as exc:
                self.ledger.refund(request_id)
                last_error=type(exc).__name__
                continue
        raise RuntimeError("no affordable available provider completed the request ("+str(last_error or "budget or config")+")")
