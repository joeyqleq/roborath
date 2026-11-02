"""Start/complete Twitch device OAuth for the separate RoboRath account.

No tokens, client secrets, or device codes are printed. The verification
user code is deliberately displayed for the owner to type into Twitch.
Run on ORA3 as jq (it reads /home/jq/credentials.env).
"""
import json
import os
import pathlib
import sys
import time
import httpx
from router import load_env
from twitch_auth import check_identity, write_token_file

ROOT=pathlib.Path("/home/jq/.config/roborath")
FILE=ROOT/"device-auth.json"
MASTER="/home/jq/credentials.env"
URL="https://id.twitch.tv/oauth2"

def start():
    c=load_env(MASTER)
    client_id=c.get("ROBORATH_TWITCH_CLIENT_ID")
    if not client_id:raise SystemExit("Missing Twitch app Client ID")
    if FILE.exists():
        obj=json.loads(FILE.read_text())
        if time.time()<obj["expires_at"]-30:
            print("Authorize RoboRath at",obj["verification_uri"])
            print("One-time user code:",obj["user_code"])
            print("Seconds remaining:",int(obj["expires_at"]-time.time()))
            return
    with httpx.Client(timeout=16) as h:
        r=h.post(URL+"/device",data={"client_id":client_id,"scopes":"chat:read chat:edit"})
        if r.status_code!=200:
            print("Twitch device setup failed, HTTP",r.status_code)
            return
        data=r.json()
    info={"client_id":client_id,
          "device_code":data["device_code"],
          "user_code":data["user_code"],
          "verification_uri":data["verification_uri"],
          "interval":max(5,int(data.get("interval",5))),
          "expires_at":time.time()+int(data.get("expires_in",1800))}
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    write_token_file(FILE,info)
    print("Sign in to Twitch as the separate roborath account.")
    print("Authorize at",info["verification_uri"])
    print("One-time user code:",info["user_code"])
    print("Seconds remaining:",int(info["expires_at"]-time.time()))
    print("Then ask ChatGPT to finish RoboRath authorization.")

def finish():
    if not FILE.is_file():
        print("Start authorization first")
        return
    d=json.loads(FILE.read_text())
    if time.time()>d["expires_at"]:
        print("Device authorization expired; start again")
        return
    c=load_env(MASTER)
    with httpx.Client(timeout=16) as h:
        data={"client_id":d["client_id"],"device_code":d["device_code"],
              "grant_type":"urn:ietf:params:oauth:grant-type:device_code",
              "client_secret":c.get("ROBORATH_TWITCH_CLIENT_SECRET","")}
        response=h.post(URL+"/token",data=data)
        if response.status_code!=200:
            print("Not authorized yet or token exchange rejected. HTTP",response.status_code)
            try:print("Twitch status:",str(response.json().get("message",""))[:80])
            except Exception:pass
            return
        tokens=response.json()
        verify=h.get(URL+"/validate",headers={"Authorization":"OAuth "+tokens["access_token"]})
        verify.raise_for_status()
        user_id=check_identity(verify.json(),d["client_id"],"roborath")
    dest=ROOT/"oauth.json"
    write_token_file(dest,tokens)
    print("RoboRath OAuth VERIFIED. Numeric Twitch user ID:",user_id)
    print("Tokens safely stored in",str(dest),"mode 0600.")
    FILE.unlink()
    print("Next: install private OAuth file for roborath service account, confirm relay access.")
if __name__=="__main__":
    if len(sys.argv)!=2 or sys.argv[1] not in ("start","finish"):
        raise SystemExit("Usage: python -m device_oauth start|finish")
    globals()[sys.argv[1]]()
