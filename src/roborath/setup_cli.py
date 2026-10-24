"""RoboRath Twitch operator setup (run locally, never on public chat)."""
import argparse
import asyncio
import getpass
import os
from pathlib import Path
from twitch_auth import authorize, access_token, resolve_users

def config_secret():
    secret=os.getenv("TWITCH_CLIENT_SECRET","")
    return secret or getpass.getpass("Rotated Twitch client secret (hidden): ")

async def resolve(client_id,secret,path):
    token,bot_id=await access_token(client_id,secret,path)
    accounts=await resolve_users(client_id,token,("joeyleq","rath_bone"))
    print("authorized RoboRath Twitch account ID:",bot_id)
    for login,uid in accounts.items():
        print("verified user ID for",login,":",uid or "not found")
    if not all(accounts.values()):
        raise SystemExit("One or more Twitch users could not be resolved")

def main():
    parser=argparse.ArgumentParser(description="RoboRath Twitch OAuth owner setup")
    parser.add_argument("command",choices=("authorize","resolve-ids","status"))
    parser.add_argument("--token-file",
        default=os.getenv("TWITCH_TOKEN_FILE",str(Path.home()/".local/share/roborath/private/oauth.json")))
    args=parser.parse_args()
    client_id=os.getenv("TWITCH_CLIENT_ID","")
    if args.command=="status":
        print("RoboRath OAuth file exists:",Path(args.token_file).is_file())
        print("Client ID configured:",bool(client_id))
        print("No token contents displayed.")
        return
    if not client_id:raise SystemExit("Set TWITCH_CLIENT_ID locally first")
    secret=config_secret()
    if args.command=="authorize":
        user_id=authorize(client_id,secret,args.token_file)
        print("Authorized roborath user ID:",user_id)
        print("Keep the OAuth file private. Never send it in chat or commit it.")
    else:
        asyncio.run(resolve(client_id,secret,args.token_file))

if __name__=="__main__":main()
