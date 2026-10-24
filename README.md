# RoboRath

AI-assisted Twitch chat companion for **rath_bone**, using the **roborath** Twitch account as a normal viewer and the existing Mattermost Agents deployment.

**Status:** initial, tested IRC bridge source, not a live Twitch bot. This repository is the canonical home for the project.

## What is in this repository

- `src/roborath/irc_adapter.py` — Twitch IRC WebSocket client, explicit normal-account OAuth validation, per-message parsing, paced concise replies.
- `src/roborath/bridge.py` — Mattermost AI relay, SQLite stream/user continuity memory, chat-command routing, viewer opt-out and 30-day pruning.
- `src/roborath/analytics.py` — private aggregate participation statistics using five-minute activity buckets, 180-day summary pruning, and viewer deletion; **not** covert psychological profiling.
- `tests/` — offline tests for IRC parsing, reply formatting, command flow, memory isolation and deletion.
- `deploy/` — a disabled-by-default systemd unit template.
- `docs/architecture.md` — authorization and operational boundaries.

## Roadmap

1. Secure user OAuth authorization for the separate bot account, including durable refresh.
2. Least-privileged Mattermost bot, private relay channel and fact/research command authorization.
3. Per-stream fact quotas (2 per user), per-day research quotas (1 per user), verified broadcaster exemptions and owner/supervisor delegated permissions.
4. Canonical stream archive and search with truthfully disclosed retention and owner-restricted analytics.
5. Mario Kart mode, first-place-only scorekeeping, reminders, controlled breaking-news monitoring and readable shortlinks.
6. Mattermost settings/dashboard; authorized security/SpiderFoot tools with approvals.

No Mem0 or Nextcloud is required. **This repository does not contain Twitch client secrets or live OAuth tokens.**

## Run tests

On ORA3, with the pre-installed Python virtual environment:

```bash
cd /home/jq/projects/roborath
PYTHONPATH=src/roborath /opt/gt-twitch-bridge/.venv/bin/python tests/test_bridge.py
PYTHONPATH=src/roborath /opt/gt-twitch-bridge/.venv/bin/python tests/test_irc_adapter.py
PYTHONPATH=src/roborath /opt/gt-twitch-bridge/.venv/bin/python -m unittest discover -s tests -p test_analytics.py -v
```

The service is **not** started by checking out the repo. Never place real credentials in Git.

## Security

The bot speaks as a normal Twitch user, not as channel moderator. Owner commands must use immutable Twitch identity checks, not claims typed into chat. Keep all privileged tooling out of public chat. See [docs/architecture.md](docs/architecture.md).
