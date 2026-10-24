# RoboRath

**RoboRath** is a permissioned AI assistant that participates in [rath_bone's Twitch channel](https://www.twitch.tv/rath_bone) as an ordinary chat account named `roborath`. It relays approved requests to the existing Dr. Greenthumb Mattermost Agents service, on separate infrastructure (ORA3 and ORA1).

**Status:** Source code and automated offline tests are available; **not authorized or live on Twitch yet**. The ORA3 service is intentionally disabled pending verified OAuth, scoped Mattermost relay access and live QA.

## Implemented in the repository

- Twitch IRC WebSocket adapter with verified user-token identity, confidential OAuth localhost authorization and refreshable private token storage.
- Short, informal responses with conservative UTF-8 byte limits, a one-message quick fact-check limit and up to two research messages.
- Two fact checks per user per broadcast, one research request per user per UTC day. Verified owner/streamer exemptions, immutable-ID grants and revocable, scoped supervisors.
- Bounded five-minute chat activity aggregates, 30-day raw chat retention, limited same-stream conversation context, deletion/opt-out and a private-data boundary.
- Mario Kart session mode, roster, typo-tolerant nicknames, two independent first-place reports or operator confirmation, round advancement and leaderboards.
- Text-only notification watches and scheduled reminders stored in SQLite, posted through the paced chat connection.
- A citation-only is.gd shortener which does not publish long fallback URLs.
- Offline unit tests and GitHub Actions CI; an installer that leaves services disabled by default.

No Mem0, Nextcloud, private Twitch broadcaster credentials or moderator roles are required.

## Important documentation

- [Commands, quotas, supervisors and permissions](docs/commands.md)
- [ORA3 installation, Twitch OAuth and Mattermost setup](docs/deployment.md)
- [Trust boundaries and security](docs/architecture.md)
- [Operator-only engagement analytics](docs/operator-analytics.md)

## Tests

```bash
python -m pip install 'httpx>=0.27,<1' 'websockets>=14,<17'
python -m compileall -q src/roborath
PYTHONPATH=src/roborath python -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=src/roborath python tests/test_bridge.py
PYTHONPATH=src/roborath python tests/test_irc_adapter.py
```

## Go-live blockers

The new Twitch application's previously shared secret should be rotated before use. The real `roborath` account must complete its one-time OAuth browser authorization, and the numeric Twitch IDs for owner `joeyleq` and broadcaster `rath_bone` need to be resolved from Twitch. A dedicated private Mattermost channel and non-admin relay bot must be provisioned and tested. Live use and automatic startup are withheld until those checks succeed.

The Mattermost System Console admin plugin, SpiderFoot/ZAP integration and live breaking-news publication **are not installed**. This repository is their canonical implementation home, not evidence they are already running.

RoboRath's public Twitch responses must be human-readable, never expose secret credentials, and never accept privileged instructions based on usernames typed inside a chat message.
