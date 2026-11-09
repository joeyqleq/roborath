"""Answers latest-upload questions from official YouTube channel Atom feeds.

Never infer a specific video title from a general search-result listing.
A creator nickname without a verified handle/channel cannot establish ownership.
"""
from __future__ import annotations

import re
from datetime import datetime,timezone
from urllib.parse import quote
from xml.etree import ElementTree
import httpx

YT_ATOM="http://www.w3.org/2005/Atom"
YT_NS="http://www.youtube.com/xml/schemas/2015"
NS={"a":YT_ATOM,"yt":YT_NS}
# Identity confirmed against the YouTube @ShmuleyShow channel on 2026-11-09.
VERIFIED_CREATORS={
    "rabbi shmuley": ("ShmuleyShow","UCIFGLFUgxRufs0od0acMzuQ"),
    "shmuley": ("ShmuleyShow","UCIFGLFUgxRufs0od0acMzuQ"),
}
HANDLE=re.compile(r"(?<!\w)@([a-z0-9_.-]{3,30})\b",re.I)
CHANNEL_ID=re.compile(r'"(?:externalId|channelId)"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"')


def known_channel(question:str):
    lower=question.casefold()
    match=HANDLE.search(question)
    if match:
        return match.group(1),None
    for needle,record in VERIFIED_CREATORS.items():
        if needle in lower:
            return record
    return None


def _parse_feed(contents:bytes,channel_id:str)->tuple[str,str,str,str]:
    if len(contents)>256_000:
        raise ValueError("YouTube feed is unusually large")
    root=ElementTree.fromstring(contents)
    feed_id=root.findtext("yt:channelId",namespaces=NS)
    if feed_id not in (channel_id,channel_id.removeprefix("UC")):
        raise ValueError("YouTube feed channel mismatch")
    channel=root.findtext("a:title",namespaces=NS) or "YouTube"
    recent=[]
    for entry in root.findall("a:entry",NS):
        title=(entry.findtext("a:title",namespaces=NS) or "").strip()
        vid=(entry.findtext("yt:videoId",namespaces=NS) or "").strip()
        published=(entry.findtext("a:published",namespaces=NS) or "").strip()
        if not title or not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid):
            continue
        try:
            dt=datetime.fromisoformat(published.replace("Z","+00:00"))
            if dt.tzinfo is None:continue
        except ValueError:continue
        recent.append((dt,title,vid))
    if not recent: raise LookupError("No published videos in verified feed")
    published,title,vid=max(recent,key=lambda item:item[0])
    return channel,title,published.astimezone(timezone.utc).date().isoformat(),"https://www.youtube.com/watch?v="+vid


async def newest_video(question:str,http:httpx.AsyncClient)->tuple[str,str]:
    """Return (short factual title/date statement, full verified link).

    Fails explicitly; never guess from unrelated web-search results.
    """
    selected=known_channel(question)
    if not selected:
        return "", ""
    handle,channel_id=selected
    if not channel_id:
        safe_handle=quote(handle,safe="")
        resp=await http.get("https://www.youtube.com/@" +safe_handle+"/videos",
                            follow_redirects=True,timeout=11,
                            headers={"User-Agent":"Mozilla/5.0"})
        resp.raise_for_status()
        if len(resp.content)>2_500_000:
            raise ValueError("unexpectedly large channel page")
        ids=CHANNEL_ID.findall(resp.text)
        if not ids:
            raise LookupError("Could not identify official YouTube channel")
        channel_id=ids[0]
    feed=await http.get("https://www.youtube.com/feeds/videos.xml",
                        params={"channel_id":channel_id},follow_redirects=True,
                        timeout=11)
    feed.raise_for_status()
    channel,title,published,url=_parse_feed(feed.content,channel_id)
    statement=f"Latest published upload in {channel} (@{handle}), {published}: {title}"
    return statement,url
