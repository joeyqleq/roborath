"""On-demand, bounded publisher RSS retrieval; reports are attributed, not verdicts."""
import asyncio
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
import html
import re
import time
from xml.etree import ElementTree as ET

from web_lookup import _safe_search_result

FEEDS=(('BBC','https://feeds.bbci.co.uk/news/world/rss.xml'),
       ('Al Jazeera','https://www.aljazeera.com/xml/rss/all.xml'))
_cache={}
_lock=asyncio.Lock()


def is_news_query(query):
    return bool(re.search(r'\b(?:news|breaking|latest|today|currently|right now|world events)\b',query,re.I))


def parse_feed(body,source,now=None):
    if len(body)>512_000 or b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('invalid feed size or declarations')
    now=now or datetime.now(timezone.utc)
    root=ET.fromstring(body)
    rows=[]
    def plain(value):return re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',html.unescape(value or ''))).strip()
    for item in root.findall('.//item')[:100]:
        try:
            published=parsedate_to_datetime(item.findtext('pubDate') or '')
            if published.tzinfo is None:continue
            published=published.astimezone(timezone.utc)
            if not now-timedelta(hours=48)<=published<=now+timedelta(minutes=5):continue
            url=(item.findtext('link') or '').strip()
            title=plain(item.findtext('title'))[:220]
            if not title or not _safe_search_result(url):continue
            rows.append(dict(source=source,title=title,summary=plain(item.findtext('description'))[:500],
                url=url,published=published.isoformat()))
        except (ValueError,TypeError,OverflowError):continue
    return rows


async def fetch_news(query,http):
    async def feed(source,url):
        try:
            async with http.stream('GET',url,timeout=6,follow_redirects=False) as r:
                r.raise_for_status();body=bytearray()
                async for chunk in r.aiter_bytes():
                    body.extend(chunk)
                    if len(body)>512_000:raise ValueError('feed too large')
            return parse_feed(bytes(body),source)
        except Exception:return []
    async with _lock:
        if time.monotonic()>_cache.get('expires',0):
            groups=await asyncio.gather(*(feed(*f) for f in FEEDS))
            _cache.update(rows=[r for group in groups for r in group],expires=time.monotonic()+300)
        rows=list(_cache.get('rows',[]))
    ignored={'what','latest','news','today','breaking','about','tell','world','events','happening','with','right','now','the','give','update'}
    terms=set(re.findall(r'[a-z]{3,}',query.lower()))-ignored
    if terms & {'israel','israeli','palestine','palestinian','gaza','netanyahu'}:
        terms|={'israel','israeli','palestinian','palestine','gaza','netanyahu'}
    ranked=[]
    now=datetime.now(timezone.utc)
    for row in rows:
        if now-datetime.fromisoformat(row['published'])>timedelta(hours=48):continue
        words=set(re.findall(r'[a-z]{3,}',(row['title']+' '+row['summary']).lower()))
        score=len(terms&words)
        if terms and not score:continue
        ranked.append((score,row['published'],row))
    ranked.sort(key=lambda r:(r[0],r[1]),reverse=True)
    chosen=[];seen=set()
    for _,_,row in ranked:
        if row['source'] in seen:continue
        chosen.append(row);seen.add(row['source'])
        if len(chosen)==2:break
    return chosen
