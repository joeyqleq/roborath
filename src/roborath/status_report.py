"""Compact, paginated owner status and access reports for Twitch chat."""
from __future__ import annotations

import os
import sqlite3


MAX_BYTES = 360
PAGE_SIZE = 3


def _clip(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= MAX_BYTES:
        return text
    suffix = "…"
    while text and len((text + suffix).encode("utf-8")) > MAX_BYTES:
        text = text[:-1]
    return text + suffix


def _name(db: sqlite3.Connection, user_id: str) -> str:
    if user_id == "*":
        return "everyone"
    try:
        row = db.execute("SELECT login FROM rr_test_access WHERE user_id=? ORDER BY granted_at DESC LIMIT 1", (user_id,)).fetchone()
        if row and row[0]:
            return "@" + str(row[0])
    except sqlite3.Error:
        pass
    try:
        row = db.execute("SELECT login FROM transcript_messages WHERE twitch_user_id=? ORDER BY created_utc DESC LIMIT 1", (user_id,)).fetchone()
        if row and row[0]:
            return "@" + str(row[0])
    except sqlite3.Error:
        pass
    try:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rr_identity_names'").fetchone()
        if exists:
            row = db.execute("SELECT login FROM rr_identity_names WHERE user_id=?", (user_id,)).fetchone()
            if row and row[0]:
                return "@" + str(row[0])
    except sqlite3.Error:
        pass
    return "id:" + str(user_id)


def _global_state(access) -> tuple[bool, bool]:
    db = access.db
    strict = os.getenv("ROBORATH_OWNER_ONLY_TEST_MODE", "false").casefold() == "true"
    muted = access.muted()
    try:
        row = db.execute("SELECT enabled FROM rr_invoke_global WHERE singleton=1").fetchone()
        global_enabled = bool(row[0]) if row else True
    except sqlite3.Error:
        global_enabled = True
    return strict, (not muted and global_enabled)


def render_status(access, stream_id: str, live: bool, model: str) -> str:
    strict, enabled = _global_state(access)
    invoke_store = getattr(access, "invokes", None)
    state = "MUTED" if access.muted() else "GLOBAL OFF" if not enabled else "QA / grants" if strict else "LIVE" if live else "OFFLINE"
    usage = 0
    if invoke_store is not None:
        try:
            usage = sum(int(row[2]) for row in invoke_store.status(stream_id).get("usage", ()))
        except (sqlite3.Error, TypeError, ValueError):
            pass
    owner_budget = "owner unlimited"
    return _clip(f"{state} | stream {str(stream_id)[:24]} | model {str(model)[:38]} | invokes used {usage} | {owner_budget}")


def render_access(access, stream_id: str, page: int = 1) -> str:
    db = access.db
    strict, enabled = _global_state(access)
    try:
        rules = db.execute("SELECT user_id,allowed,limit_count FROM rr_invoke_rules ORDER BY CASE WHEN user_id='*' THEN 0 ELSE 1 END,user_id").fetchall()
    except sqlite3.Error:
        rules = []
    users: dict[str, tuple[bool, int | None]] = {}
    legacy_caps={}
    wildcard = None
    for uid, allowed, base_limit in rules:
        entry = (bool(allowed), int(base_limit))
        if uid == "*":
            wildcard = entry
        else:
            users[str(uid)] = entry
    try:
        limits = db.execute("SELECT user_id,limit_count FROM rr_invoke_limits WHERE stream_id=?", (str(stream_id),)).fetchall()
        scoped = {str(uid): int(count) for uid, count in limits}
    except sqlite3.Error:
        scoped = {}
    try:
        legacy = db.execute("SELECT user_id,login,group_concat(capability,',') FROM rr_test_access GROUP BY user_id,login ORDER BY login").fetchall()
        for uid, _login, _caps in legacy:
            if str(uid) not in users:legacy_caps[str(uid)]=_caps
            users.setdefault(str(uid), (True, None))
    except sqlite3.Error:
        pass

    page = max(1, int(page))
    rows = []
    if wildcard is not None:
        allowed, base_limit = wildcard
        limit = scoped.get("*", base_limit if base_limit >= 0 else None)
        if limit is not None and limit < 0:limit=None
        rows.append(("everyone", allowed, limit, "*"))
    for uid, (allowed, base_limit) in users.items():
        # A user's explicit unlimited rule takes priority over wildcard quotas.
        limit = scoped.get(uid, None if base_limit is not None and base_limit<0 else scoped.get("*", None))
        if limit is not None and limit < 0:limit=None
        used = 0
        try:
            used = db.execute("SELECT COUNT(*) FROM rr_invoke_usage WHERE user_id=? AND stream_id=? AND used=1", (uid, str(stream_id))).fetchone()[0]
        except sqlite3.Error:
            pass
        remaining = max(0, limit - int(used)) if limit is not None else None
        rows.append((_name(db, uid), allowed, remaining, uid))
    rows.sort(key=lambda item: (item[3] != "*", item[0].casefold()))
    count = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, count)
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    labels = []
    for name, allowed, remaining, uid in selected:
        if not enabled:
            status = "blocked global-off"
        elif not allowed:
            status = "denied"
        elif strict and uid != access.owner_id and access.invokes.access(uid) is None and os.getenv("ROBORATH_QA_GRANTED_TESTERS","false").lower()!="true":
            status = "granted; QA owner-only"
        elif remaining is None:
            status = "allowed; normal quotas" if uid in legacy_caps else "allowed unlimited"
        else:
            status = f"allowed {remaining} left"
        prefix=name+(': '+legacy_caps[uid] if uid in legacy_caps else '')
        labels.append(f"{prefix} {status}")
    if not labels:
        labels = ["No explicit invoke rules"]
    state = "MUTED" if access.muted() else "global off" if not enabled else "QA / grants" if strict else "global on"
    return _clip(f"Owner @joeyleq always allowed | {state} | access {page}/{count}: " + " | ".join(labels))
