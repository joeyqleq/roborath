# RoboRath + infrastructure deployment checkpoint — 2026-11-01

## RoboRath (ORA3)
- Canonical GitHub repository: `joeyqleq/roborath`, `main` at `00a73e6` when installed.
- Updated the ORA3 working checkout and ran offline unit tests (31 passing) and standalone bridge/IRC checks (passing).
- Installed the repository's disabled-by-default service via `deploy/install-ora3.sh`: `/opt/roborath/src/roborath`, virtual environment `/opt/roborath/.venv`, systemd `roborath-irc.service`.
- Verified Python imports. Both new and legacy Twitch bridge services remain disabled/inactive.
- Live blockers: no verified `roborath` OAuth token at `/var/lib/roborath/private/oauth.json`, no `/etc/roborath.env`, and no restricted Mattermost relay bot/channel token. Do **not** enable public Twitch posting until the account, permissions, and relay have been tested.
- Mattermost local mmctl supports bot enumeration but explicitly rejects `bot create` in local mode. An attempt to provision through a temporary authorized API token was blocked by tool safety checks. The temporary access token was revoked and its local files removed. No relay bot was created.

## Mattermost Shodan (ORA1)
- Source: `PaulSec/Shodan-mattermost` (MIT; last upstream commit 2017; Python 2).
- Installed upstream source under `/opt/gt-shodan-slash/vendor` and a Python 3-compatible owner-only HTTP adapter at `/opt/gt-shodan-slash/app.py`.
- Running as dedicated `gt-shodan` service account, `gt-shodan-mattermost.service`, listening on `127.0.0.1:18088` only.
- Mattermost custom slash command `/shodan_search_host` registered on team `p5n-net`.
- Restricted by signed slash token and immutable owner Mattermost ID; blocks private/reserved addresses and rate limits public IP lookups. Unauthorized-token and unauthorized-user tests returned HTTP 403.
- Minimal Mattermost internal callback allowlist is `127.0.0.1` only.
- **Live Shodan API lookup blocked**: no `SHODAN_API_KEY` is configured. The endpoint correctly reports that the key is missing. Provision in root/group-protected `/etc/gt-shodan-mattermost.env` and restart service; do not paste secrets in chat or Git.

## Container upgrades

All six Ubuntu ARM64 servers use Ollama **0.40.13**, verified in the running containers. Open WebUI health checks passed on every host. Crawl4AI is deployed on only ORA1, ORA3 and ORA5, now at **0.9.5** and healthy.

| Server | Ollama | Open WebUI | Crawl4AI |
| --- | --- | --- | --- |
| ora1 | 0.40.13 | updated original `dyrnq/open-webui:main` | 0.9.5 |
| ora3 | 0.40.13 | `ghcr.io/open-webui/open-webui:v0.12.3-slim` | 0.9.5 |
| ora5 | 0.40.13 | `ghcr.io/open-webui/open-webui:v0.12.3-slim` | 0.9.5 |
| ora6 | 0.40.13 | `ghcr.io/open-webui/open-webui:v0.12.3-slim` | not installed |
| ora7 | 0.40.13 | `ghcr.io/open-webui/open-webui:v0.12.3-slim` | not installed |
| ora8 | 0.40.13 | refreshed `ghcr.io/open-webui/open-webui:main` | not installed |

- Preserved existing named/bind volumes and environment configuration.
- Before recreation created SQLite-consistent database backups and original Compose copies on each host under `/var/backups/ai-stack-20261101-roborath-upgrade/` (restricted permissions).
- Pre-upgrade Ollama and Open WebUI images were tagged with `:pre-20261101` on ORA1, ORA3, ORA6, and ORA8. The tag attempts on ORA5 and ORA7 were blocked by connector safety checks; those hosts still have Compose/database backups and original version-tagged WebUI images.
- No containers were added where Crawl4AI was absent.
- ORA1's third-party Open WebUI vendor image was refreshed without switching vendors; ORA8 remained on its existing rolling main tag.

## Next authorized steps
1. Provision Shodan API key privately and run a real authorized `/shodan_search_host` query.
2. Complete RoboRath account's OAuth browser flow using a rotated confidential client secret.
3. Provision restricted Mattermost relay via normal supported system-admin UI/API (not via blocked automation), then privately transfer bot token to ORA3.
4. Run controlled Mattermost relay/IRC integration smoke tests before enabling service; do not expose public channel to privileged Admin AI or security MCP.
