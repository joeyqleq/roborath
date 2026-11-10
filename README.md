# RoboRath

RoboRath is an ordinary Twitch chat account for `rath_bone`, with its bot process on ORA3 and its restricted AI relay in a private Mattermost channel on ORA1. It can answer explicit chat requests, search for current material, relay source-backed fact checks/research, track Mario Kart results, and run bounded text reminders and stream rules.

## Current state

The ORA3 `roborath-irc.service` was verified active and enabled with zero systemd restarts on 2026-11-10. Its checked-out and installed code were still at `b69675c`; this workspace contains later local work and is not proof of deployment. `ROBORATH_OWNER_ONLY_TEST_MODE=true` remains active, so only verified Twitch owner ID `1414798445` receives replies. The dedicated ORA1 channel membership was verified as the private owner `p5n`, specialist `greenthumb-ai`, and non-admin relay account `roborath-relay`.

A private synthetic FactCheck QA request returned a final answer with source attribution in 6.43 seconds. That verifies a bounded request/reply path, but does not independently prove the specialist's actual source retrieval calls, provider model billing, accuracy across question types, or public Twitch delivery. No production deployment has been made from the local changes. See [implementation and QA reports](docs/IMPLEMENTATION-2026-11-10.md), [QA matrix](docs/QA-2026-11-10.md), and [service benchmark](docs/SERVICES-2026-11-10.md).

The owner clarified that the configured Hermes route is through Nebius, not OpenRouter; the owner reported `$29.75` available. The live balance was not independently inspected, and no provider or model change was made.

## Source features

- Twitch IRC/EventSub handling, immutable-ID access rules, persisted owner silence, quota grants and refunds.
- Short conversation, current web lookup, explicit `!verify` quick checks and `!verify deep` research, with `!fact` and `!research` compatibility aliases.
- Stream-scoped SQLite transcript storage, attributed text retrieval, opt-out/deletion and 30-day retention.
- Mario Kart rounds, roster, confirmed first-place scores and leaderboards.
- Owner-managed keyword rules, first-message welcome configuration, relative/fixed reminders, and a 20-minute rotating Follow reminder bank.
- Private relay controls and a fail-closed public output boundary for internal tool/reasoning artifacts.

Check the [command reference](docs/commands.md) for exact parser syntax and the [architecture](docs/architecture.md) for trust boundaries. Those files describe source behavior; the revision running on ORA3 must be checked separately.

## Local development and checks

Python 3.11 or later is required. From the repository root:

```sh
python3 -m pip install -e '.[dev]'
python3 -m compileall -q src/roborath
PYTHONPATH=src/roborath python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=src/roborath python3 tests/test_bridge.py
PYTHONPATH=src/roborath python3 tests/test_irc_adapter.py
```

Never copy `/etc/roborath.env`, OAuth tokens, provider keys, or an unredacted production SQLite database into the repository. `.env.example` contains names and examples only. Do not turn off owner-only QA or post public Twitch messages without explicit authorization.

## References

- [Commands, access and limits](docs/commands.md)
- [Architecture and trust boundaries](docs/architecture.md)
- [Live state, backup and rollback](docs/deployment.md)
- [Operator analytics](docs/operator-analytics.md)

## Latest owner and transcript behavior

Verified owner joeyleq receives the Chairman/Boss/Captain/Leader/Comandante voice, with RoboRath as his loyal servant. Owner-only tone is scoped by immutable ID. `Stop replying unless I say banana` persists silence; only the owner’s exact phrase (or explicit resume) resumes. Received public chat and bot sends have plain `username: message` exports, bounded five-hour context retrieval, and 30-day deletion. Per-user words, messages, native replies and bot replies are counted separately. See [analytics/export guide](docs/operator-analytics.md), [model comparison](docs/MODEL-BENCHMARK-2026-11-10.md), and [environment audit](docs/ENVIRONMENT-AUDIT-2026-11-10.md). All changes are source-only pending deployment approval.
