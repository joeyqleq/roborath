"""Confidential Twitch OAuth with localhost authorization and durable token refresh.

Run initial authorize ONLY on the operator's own computer. Secrets and token
files are local credentials and must never be checked into Git or sent to chat.
"""
import json
import os
import secrets
import stat
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

AUTH="https://id.twitch.tv/oauth2/authorize"
TOKEN="https://id.twitch.tv/oauth2/token"
VALIDATE="https://id.twitch.tv/oauth2/validate"
SCOPES={"chat:read","chat:edit"}

def read_token_file(path):
    file=Path(path)
    info=file.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise PermissionError("token file must be a regular file with chmod 600")
    return json.loads(file.read_text())

def write_token_file(path,data):
    file=Path(path)
    file.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if file.exists():
        read_token_file(file)
    # An exclusive new temp file prevents following pre-existing symlinks.
    tmp=file.with_name(file.name+"."+secrets.token_hex(6)+".tmp")
    try:
        fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"w") as out:
            json.dump(data,out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp,file)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass

def check_identity(verified,client_id,required_login="roborath"):
    if verified.get("client_id")!=client_id:
        raise PermissionError("client ID mismatch")
    if verified.get("login","").lower()!=required_login.lower():
        raise PermissionError("authorized Twitch account is not RoboRath")
    if not SCOPES.issubset(set(verified.get("scopes",[]))):
        raise PermissionError("missing minimum IRC chat scopes")
    user_id=verified.get("user_id","")
    if not user_id.isdecimal():
        raise PermissionError("invalid authenticated Twitch user ID")
    return user_id

async def access_token(client_id,client_secret,path,required_login="roborath"):
    """Refresh before expiry; validate client and immutable account identity."""
    saved=read_token_file(path)
    async with httpx.AsyncClient(timeout=15) as client:
        async def validate(tok):
            r=await client.get(VALIDATE,headers={"Authorization":"OAuth "+tok})
            return r.json() if r.status_code==200 else None
        verified=await validate(saved["access_token"])
        if not verified or verified.get("expires_in",0)<900:
            if not client_secret or not saved.get("refresh_token"):
                raise PermissionError("OAuth reauthorization required")
            r=await client.post(TOKEN,data={"grant_type":"refresh_token",
                "client_id":client_id,"client_secret":client_secret,
                "refresh_token":saved["refresh_token"]})
            r.raise_for_status()
            new=r.json()
            if "access_token" not in new or "refresh_token" not in new:
                raise RuntimeError("Twitch refresh returned incomplete tokens")
            candidate={**saved,**new}
            verified=await validate(candidate["access_token"])
            if not verified:raise PermissionError("refreshed token is invalid")
            check_identity(verified,client_id,required_login)
            write_token_file(path,candidate)
            saved=candidate
        bot_id=check_identity(verified,client_id,required_login)
        return saved["access_token"],bot_id

def authorize(client_id,client_secret,path,redirect="http://localhost:3000"):
    """One-time interactive setup, desktop-only, with CSRF state validation."""
    if not client_id or not client_secret:
        raise ValueError("client ID and secret must be supplied locally")
    u=urlsplit(redirect)
    if (u.scheme,u.hostname,u.port)!=("http","localhost",3000) or u.path not in ("","/"):
        raise ValueError("registered redirect must exactly match http://localhost:3000")
    state=secrets.token_urlsafe(32)
    observed={}
    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            p=urlsplit(self.path)
            args=parse_qs(p.query)
            if p.path!="/" or args.get("state",[None])[0]!=state:
                self.send_error(400,"Invalid OAuth callback")
                return
            observed["code"]=args.get("code",[None])[0]
            observed["error"]=args.get("error",[None])[0]
            self.send_response(200 if observed["code"] else 400)
            self.send_header("Content-Type","text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"RoboRath OAuth received. You can close this tab.")
        def log_message(self,*args):pass
    url=AUTH+"?"+urlencode({"client_id":client_id,"response_type":"code",
        "redirect_uri":redirect,"scope":"chat:read chat:edit",
        "state":state,"force_verify":"true"})
    server=HTTPServer(("127.0.0.1",3000),Receiver)
    server.timeout=120
    print("Opening Twitch authorization for RoboRath. Never paste tokens into chat.")
    webbrowser.open(url)
    try:server.handle_request()
    finally:server.server_close()
    if not observed.get("code"):
        raise RuntimeError("OAuth was not completed")
    with httpx.Client(timeout=15) as client:
        response=client.post(TOKEN,data={"client_id":client_id,
            "client_secret":client_secret,"grant_type":"authorization_code",
            "redirect_uri":redirect,"code":observed["code"]})
        response.raise_for_status()
        tokens=response.json()
        r=client.get(VALIDATE,headers={"Authorization":"OAuth "+tokens["access_token"]})
        r.raise_for_status()
        user_id=check_identity(r.json(),client_id)
        write_token_file(path,tokens)
    return user_id

async def resolve_users(client_id,token,names=("joeyleq","rath_bone")):
    """Resolve stable numeric user IDs without trusting chat display names."""
    async with httpx.AsyncClient(timeout=15) as client:
        r=await client.get("https://api.twitch.tv/helix/users",
            params=[("login",name) for name in names],
            headers={"Client-ID":client_id,"Authorization":"Bearer "+token})
        r.raise_for_status()
        found={user["login"].lower():user["id"] for user in r.json().get("data",[])}
        return {name:found.get(name.lower()) for name in names}
