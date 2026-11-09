#!/usr/bin/env python3
"""Provision the RoboRath runtime environment from ORA3's private inventory.

Run as root on ORA3. Never print secrets, copy them into Git, or expose
Shodan/Admin AI credentials to the public-chat bot.
"""
import os
import pwd
import tempfile
from pathlib import Path

MASTER=Path("/home/jq/credentials.env")
DEST=Path("/etc/roborath.env")

def values():
    if MASTER.stat().st_mode & 0o077:
        raise PermissionError("master credential inventory must be private")
    result={}
    for line in MASTER.read_text().splitlines():
        if line.lstrip().startswith("#") or "=" not in line:continue
        key,val=line.split("=",1)
        result[key]=val.strip().strip("'").strip('"')
    return result

def quote(value):
    if any(x in value for x in ("\n","\r","\x00")):
        raise ValueError("multiline or binary secrets not supported")
    return '"'+value.replace("\\","\\\\").replace('"','\\"')+'"'

def main():
    if os.geteuid()!=0:raise PermissionError("run as root on ORA3")
    d=values()
    mapping={
        "TWITCH_IRC_NICK":"ROBORATH_TWITCH_LOGIN",
        "TWITCH_CHANNEL_LOGIN":"ROBORATH_TWITCH_CHANNEL",
        "TWITCH_CLIENT_ID":"ROBORATH_TWITCH_CLIENT_ID",
        "TWITCH_CLIENT_SECRET":"ROBORATH_TWITCH_CLIENT_SECRET",
        "ROBORATH_OWNER_TWITCH_USER_ID":"ROBORATH_OWNER_TWITCH_USER_ID",
        "ROBORATH_STREAMER_TWITCH_USER_ID":"ROBORATH_STREAMER_TWITCH_USER_ID",
        "MATTERMOST_URL":"MATTERMOST_BASE_URL",
        "MATTERMOST_BOT_TOKEN":"MATTERMOST_RELAY_BOT_TOKEN",
        "MATTERMOST_CHANNEL_ID":"MATTERMOST_RELAY_CHANNEL_ID",
        "MM_FACTCHECK_USER_ID":"MATTERMOST_FACTCHECK_AGENT_ID",
        "MERGE_BASE_URL":"MERGE_BASE_URL","MERGE_API_KEY":"MERGE_API_KEY",
        "NEBIUS_BASE_URL":"NEBIUS_BASE_URL","NEBIUS_API_KEY":"NEBIUS_API_KEY",
        "NVIDIA_BASE_URL":"NVIDIA_BASE_URL","NVIDIA_API_KEY":"NVIDIA_API_KEY",
    }
    environment={dest:d.get(source,"") for dest,source in mapping.items()}
    environment.update({
       "TWITCH_TOKEN_FILE":"/var/lib/roborath/private/oauth.json",
       "GT_TWITCH_DB":"/var/lib/roborath/chat.sqlite3",
       "ROBORATH_ROUTER_LEDGER":"/var/lib/roborath/spend.sqlite3",
       "NVIDIA_VERIFIED":"false",
       "ROBORATH_LOCAL_DECISION_ENABLED":"true",
       "ROBORATH_OWNER_ONLY_TEST_MODE":"true",
       "GT_USER_COOLDOWN_SECONDS":"8",
       "GT_GLOBAL_REPLY_COOLDOWN_SECONDS":"4",
       "GT_LOG_RETENTION_DAYS":"30",
    })
    if not all(environment.get(k,"").isdecimal() for k in ("ROBORATH_OWNER_TWITCH_USER_ID",
                                                          "ROBORATH_STREAMER_TWITCH_USER_ID")):
        raise ValueError("verified immutable Twitch owner and broadcaster IDs are required")
    if DEST.exists():
        p=Path("/etc/roborath.env.pre-provision")
        if not p.exists():
            import shutil
            shutil.copy2(DEST,p)
            p.chmod(0o600)
    temp=Path("/etc/roborath.env.stage-"+str(os.getpid()))
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,"w") as f:
            for key,value in environment.items():
                f.write(key+"="+quote(value)+"\n")
            f.flush();os.fsync(f.fileno())
        os.replace(temp,DEST)
    finally:
        if temp.exists():temp.unlink()
    print("Provisioned ORA3 /etc/roborath.env, mode 0600.")
    print("Twitch app configured:",bool(environment["TWITCH_CLIENT_SECRET"]))
    print("Router provider keys configured:",
          ", ".join(k for k in ("MERGE","NEBIUS","NVIDIA") if environment.get(k+"_API_KEY")))
    print("Mattermost relay configured:",bool(environment.get("MATTERMOST_BOT_TOKEN") and environment.get("MATTERMOST_CHANNEL_ID")))
    print("No credentials displayed. This command did not enable the service.")

if __name__=="__main__":main()
