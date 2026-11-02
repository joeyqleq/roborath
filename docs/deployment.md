# ORA3 deployment / go-live checklist

This repo intentionally leaves the bot OFF until authorized, validated, and tested.

## A. Prepare ORA3

1. Update working checkout: `cd /home/jq/projects/roborath && git pull --ff-only origin main`
2. Run `sudo bash deploy/install-ora3.sh`. This installs the runtime and systemd unit but **does not enable or start** it.
3. Ensure `/etc/roborath.env` is readable by systemd only: root:root, mode `0600`. Start with the repository's `.env.example` as a reference, never commit the populated file.
4. The private OAuth token file belongs to Linux user `roborath`, mode `0600`, located at `/var/lib/roborath/private/oauth.json`.

## B. Authorize Twitch RoboRath account on the DESKTOP

1. Rotate any previously shared Twitch client secret in the Twitch Developer Console.
2. Configure confidential application callback exactly `http://localhost:3000`.
3. On the desktop, install the Python dependencies `httpx` and `websockets`, and set only the new Client ID in `TWITCH_CLIENT_ID`.
4. Sign into Twitch as **roborath**, not joeyleq or rath_bone, then run:

```sh
PYTHONPATH=src/roborath python src/roborath/setup_cli.py authorize
PYTHONPATH=src/roborath python src/roborath/setup_cli.py resolve-ids
```

The CLI prompts for the client secret with hidden input, validates the logged-in Twitch user, and stores a private OAuth token file. The resolver displays immutable numeric IDs for the verified accounts `joeyleq` and `rath_bone`.

5. Privately transfer the OAuth file to ORA3 through your authenticated SSH/Tailscale connection; **do not** paste it in chat. Copy it to the private destination and assign ownership to `roborath:roborath`. Ensure its parent directory is mode 0700.

## Current ORA1 relay provisioning (2026-11-02)

- **Private channel exists:** `p5n-net:roborath-relay` (channel ID `9h5zep771i8umnacsdpt6nfosy`).
- **Channel membership verified:** owner `p5n` and fact-check agent `greenthumb-ai` (user ID `d66mch8hwtrfzdj795wgctzxra`).
- **Bot account missing:** the separate non-admin `roborath-relay` bot has not yet been created.
- The Mattermost CLI on ORA1 returns **“This command cannot be run in local mode”** for `mmctl --local bot create`. Do not bypass this with server or database writes. Creation requires an authenticated Mattermost system-admin UI/API session.

### Finish via the supported Mattermost administrator UI

1. Sign in to `https://matter.greenthumb.lol` as the existing system administrator `p5n`.
2. Open **System Console → Integrations → Bot Accounts**, then create bot username **`roborath-relay`** with display name **RoboRath Relay**. Leave it a regular non-admin account, not a system administrator.
3. Generate and securely retain its access token. Do **not** paste it in Twitch, GitHub, or a chat message.
4. Add the bot to the `p5n-net` team and the private `roborath-relay` channel, alongside `p5n` and `greenthumb-ai`. No other users or Admin AI.
5. Enter the bot token locally in the owner-only ORA3 `/home/jq/credentials.env` as `MATTERMOST_RELAY_BOT_TOKEN`, and set `MATTERMOST_RELAY_CHANNEL_ID=9h5zep771i8umnacsdpt6nfosy`.
6. Run `sudo python3 /home/jq/projects/roborath/deploy/provision-runtime.py` to update the private `/etc/roborath.env` from the master. This does not activate a service.
7. Before enabling Twitch posting, use the new token to verify the bot account identity and private channel membership, send one harmless internal test to the FactCheck agent, confirm an actual reply, and validate the one-fact/stream research quotas. Only then enable `roborath-irc.service`.

Twitch device authorization has **already completed and been verified** as `roborath` (Twitch user ID `1591621882`); OAuth is installed as a private file at `/var/lib/roborath/private/oauth.json` on ORA3. This step does not need repeating.

## C. Mattermost isolation

- Create a distinct non-admin Mattermost **bot** for public Twitch requests.
- Create a dedicated private relay channel for the bot and the designated FactCheck/Research AI user.
- Never give this bot access to privileged Admin AI, private owner files, secrets, SpiderFoot scans, or unrestricted MCP tools.
- Validate `activate_ai` with a single, harmless test message and a bounded AI response.
- Put the generated Mattermost bot token and channel ID into `/etc/roborath.env` (mode 0600), not into GitHub or chat.

## D. Offline verification

```sh
python -m compileall -q src/roborath
PYTHONPATH=src/roborath python -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=src/roborath python tests/test_bridge.py
PYTHONPATH=src/roborath python tests/test_irc_adapter.py
```

Confirm token refresh on ORA3 and verify the OAuth account is the new RoboRath account. Confirm the configured owner numeric Twitch ID actually resolves to `joeyleq`, and the streamer ID to `rath_bone`. Test the quota reset using **different** broadcast IDs, duplicate message handling, a fact answer, a research answer, a reminder, opt-out, Mario Kart score confirmation, and outbound reply pacing.

## E. Activate only after verification

Run `sudo systemctl enable --now roborath-irc.service` on ORA3 **only after A–D succeed**. The prior `gt-twitch-bridge.service` must remain disabled so two bots cannot respond to the same message.

## Known unfinished integrations

- Native Mattermost System Console / administrator visual analytics view
- Security/ZAP/SpiderFoot tool integration and authorization checks
- Breaking-news source ingestion, editorial verification and deduplicated publication
- Rich historical chat search UI, human-in-the-loop research corrections and voice/video observations
- Offline→live Twitch stream boundary testing and external load tests

No service has been activated through GitHub commits alone.
