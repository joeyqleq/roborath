# ORA3 operations, deployment and rollback

This runbook distinguishes checked live state from the local working tree. GitHub pushes do not update ORA3 automatically. Public bot access stays closed until the owner explicitly authorizes it.

## Verified snapshot, 2026-11-10

- ORA3 `roborath-irc.service`: active, enabled, zero systemd restarts at inspection.
- ORA3 source checkout `/home/jq/projects/roborath` and installed runtime `/opt/roborath`: both at `b69675c`.
- `ROBORATH_OWNER_ONLY_TEST_MODE=true` and `ROBORATH_FACT_RELAY_ENABLED=true` were reported by the live process. Secret values were not printed.
- ORA1 Mattermost private relay channel membership: owner `p5n`, specialist `greenthumb-ai`, and `roborath-relay` bot. The bot is non-admin.
- One short private synthetic FactCheck request produced a source-attributed final answer in 6.43 seconds. This confirms a bounded synthetic request/reply, not independent proof of actual source-retrieval calls, token billing, broad factual accuracy, or public Twitch delivery.
- No production deployment of the newer local work has occurred. Local tests and reports describe source checkout only.

Recheck live state before an operation. Keep output limited to service state, Git hashes, and boolean configuration presence; never print `/etc/roborath.env`, token files, private channel messages, or unredacted SQLite rows.

## Safe read-only inspection

From an authorized SSH session, check service and revisions without displaying configuration values:

```sh
sudo systemctl is-active roborath-irc.service
sudo systemctl is-enabled roborath-irc.service
sudo systemctl show roborath-irc.service -p NRestarts -p MainPID --no-pager
git -C /home/jq/projects/roborath rev-parse --short HEAD
git -C /opt/roborath rev-parse --short HEAD
```

For private environment checks, print only allow-listed flag names and `present`/`missing` status using a reviewed local script. Do not run `cat`, `env`, or `systemctl show -p Environment` against the live secrets. Read logs with bounded time ranges and redact user content and request material.

## Owner-only QA operation

`ROBORATH_OWNER_ONLY_TEST_MODE=true` means only immutable owner Twitch ID `1414798445` may receive public replies. Existing user grants and the streamer's unlimited AI-use policy do not bypass this QA gate. Scheduled Follow reminders are paused. Keep the separate ORA1 relay private and non-admin. Never toggle public mode or send a public test as part of a code deployment unless the owner explicitly authorizes that test.

The source repository contains new stream transcript, verification, timer, rule and output-validation code. Its presence in Git does not imply those features are installed or currently enabled on ORA3.

## Approved release preparation

Only after code review and local tests pass, and after the owner authorizes the release:

1. Record the current source and installed revisions, service status, `NRestarts`, service user, owner-only QA flag state, and database file path/size/permissions. Confirm no unrelated source edits are present on the server.
2. Stop only `roborath-irc.service` for a consistent database snapshot. Do not stop Mattermost or other ORA services.
3. Create a private root-owned backup directory with mode `0700`. Copy `/etc/roborath.env` and private OAuth material using mode `0600`; never display or paste their contents. Preserve the prior source/runtime revision.
4. Use SQLite's online backup API for `/var/lib/roborath/chat.sqlite3`, not a raw copy of a live WAL database. For example, an approved root-owned Python helper should open the source with `sqlite3.connect('file:/var/lib/roborath/chat.sqlite3?mode=ro', uri=True)` and call `source.backup(destination)` where the destination is a new file inside the private backup directory, then close both connections. Set the backup file to `0600`, verify it opens and has expected tables, and keep it out of Git and logs. Include any separate spend/analytics database if the live configuration uses one.
5. Fetch the intended non-force-pushed main revision and verify its full commit hash. Run the documented install procedure. Do not use `enable --now` as a routine update; preserve the existing enabled state and start only the specific service after installation.
6. Start the service and check health, `NRestarts`, installed revision, and safe owner-only operation. Do not disclose or post to public chat. A private relay smoke test must be short, bounded, and return only final content.

The production procedure is intentionally approval-gated; these instructions do not authorize a release, public-mode change, purchase, or public test.

## Rollback

If the updated service fails during an approved deployment, stop only `roborath-irc.service`, restore the previous source/runtime revision and its matching application files, and restore the SQLite backup only if the new code migrated or damaged the schema. Keep the service stopped while restoring the database. Restore the corresponding private environment and OAuth files with their original owner and restrictive permissions. Start the same service and verify the old revision, active state, `NRestarts`, owner-only QA flag, and database open/read checks. Do not restore a database from a newer schema into older code unless compatibility has been verified. Preserve a redacted incident note; do not upload backup artifacts.

## Relay isolation

Mattermost relay lives in the existing ORA1 server and private `roborath-relay` channel. The relay account must remain non-admin and limited to the dedicated channel and specialist agent. Do not add Admin AI, filesystem access, shell execution, Shodan, or unrestricted tools. The synthetic QA result mentioned above does not prove the end-to-end evidence chain or paid token usage.

## First-time setup reference

The RoboRath Twitch account OAuth was already verified and installed on ORA3 as user ID `1591621882`; do not repeat setup as part of routine deploys. The owner ID is `1414798445`. Resolve the broadcaster's numeric Twitch ID through authenticated Twitch data rather than guessing it. Secret rotation, new account creation and scopes are separate owner-approved tasks. Use [.env.example](../.env.example) for variable names only; never populate it with live values.
