"""Bounded, nonprivileged public web evidence for conversational replies.

No admin tools, private data, paywalls, or execution of retrieved content.
A keyless metasearch library can be rate-limited/unavailable; fail explicitly.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

LIVE_HINT = re.compile(
    r"\b(weather|temperature|forecast|right now|currently|today|tonight|"
    r"latest|breaking|news|recent|up.to.date|web search|look up|lookup|"
    r"search for|search the web|what happened|who won|202[5-9])\b", re.I)
WEATHER = re.compile(r"\b(?:weather|temperature|forecast)\b", re.I)
LOCATION = re.compile(
    r"\b(?:in|for|at|around|near)\s+([\w .,'-]{2,90}?)"
    r"(?:\s+(?:right now|currently|today|tonight|this morning|"
    r"at the moment)|\s*[?!.,]*$)", re.I)
NOW = re.compile(r"\b(now|current|today|tonight|right now|at the moment)\b", re.I)

WMO = {
    0:"clear",1:"mainly clear",2:"partly cloudy",3:"overcast",
    45:"fog",48:"freezing fog",51:"light drizzle",53:"moderate drizzle",
    55:"dense drizzle",56:"light freezing drizzle",57:"dense freezing drizzle",
    61:"slight rain",63:"moderate rain",65:"heavy rain",66:"light freezing rain",
    67:"heavy freezing rain",71:"slight snowfall",73:"moderate snowfall",
    75:"heavy snowfall",77:"snow grains",80:"light rain showers",
    81:"moderate rain showers",82:"violent rain showers",
    85:"slight snow showers",86:"heavy snow showers",
    95:"thunderstorm",96:"thunderstorm with hail",99:"heavy thunderstorm with hail",
}


def needs_lookup(question: str) -> bool:
    return bool(LIVE_HINT.search(question))


def _bing_rss(query: str) -> list[dict[str, str]]:
    """Read Bing's public RSS search feed if metasearch engines fail.

    Require multiple query terms in titles so dictionary results for 'won'
    cannot masquerade as an answer to a Formula 1 winners query.
    """
    response = httpx.get(
        "https://www.bing.com/search",
        params={"q":query[:250],"format":"rss","mkt":"en-US","setlang":"en-US"},
        headers={"User-Agent":"Mozilla/5.0"},
        timeout=8,follow_redirects=False)
    response.raise_for_status()
    if len(response.content)>300_000:
        return []
    root = ElementTree.fromstring(response.content)
    stop = {"what","when","where","which","about","latest","current","today",
            "right","from","with","have","that","search","whose","winner",
            "won","some","time","this","year","what's"}
    relevant = set(re.findall(r"[a-z]{4,}",query.casefold())) - stop
    results = []
    for item in root.findall(".//item")[:8]:
        title=(item.findtext("title") or "").strip()
        url=(item.findtext("link") or "").strip()
        words=set(re.findall(r"[a-z]{4,}",title.casefold()))
        if len(words & relevant) < min(2,len(relevant)):
            continue
        results.append({"title":title,"href":url})
        if len(results)>=3:
            break
    return results


def _search_sync(query: str) -> tuple[str, str]:
    # Short, bounded snippets only. Do not fetch or execute linked webpages.
    from ddgs import DDGS
    items = []
    # Keyless upstream search engines can rate-limit one provider. Try two
    # explicit backends; never fabricate results after a provider failure.
    for backend in ("google", "bing"):
        try:
            with DDGS(timeout=7) as client:
                items = client.text(query, backend=backend, max_results=3) or []
            if items:
                break
        except Exception:
            continue
    if not items:
        try:
            items=_bing_rss(query)
        except (httpx.HTTPError, ElementTree.ParseError, ValueError):
            items=[]
    lines = []
    first_domain = ""
    for item in items[:2]:
        url = str(item.get("href") or item.get("url") or "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        domain = parsed.hostname.removeprefix("www.")
        title = re.sub(r"\s+", " ", str(item.get("title", "")))[:95]
        if not first_domain:
            first_domain = domain
        lines.append(f"{title} ({domain}) {url[:230]}")
    # Search snippets are not verified article text; never let an LLM invent
    # a winner, date, or alleged fact merely from these result titles.
    if not lines:
        return "", ""
    return "Web results (open for details): " + " | ".join(lines), first_domain


async def _weather(question: str, http: httpx.AsyncClient) -> tuple[str, str]:
    m = LOCATION.search(question)
    if not m:
        return "", ""
    place = m.group(1).strip(" ,.?'")
    if not place:
        return "", ""
    geo = await http.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": place, "count": 1}, timeout=8)
    geo.raise_for_status()
    found = geo.json().get("results", [])
    if not found:
        return "", ""
    where = found[0]
    lat, lon = where["latitude"], where["longitude"]
    resp = await http.get("https://api.open-meteo.com/v1/forecast",
                          params={"latitude": lat, "longitude": lon,
                                  "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                                  "timezone": "auto"}, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    current = data["current"]
    label = where.get("name", place)
    if where.get("country"):
        label += ", " + where["country"]
    if where.get("feature_code") == "PCLI":
        label += " (country-center reading; local weather varies)"
    # A deterministic response prevents the model from hallucinating the WMO
    # condition: for example 73 means SNOW, not partly cloudy.
    condition=WMO.get(int(current["weather_code"]), "conditions unclassified")
    local_time=current["time"].replace("T"," ")
    text=(
        f"{label}: {current['temperature_2m']}°C, {condition}; "
        f"humidity {current['relative_humidity_2m']}%, "
        f"precip {current['precipitation']} mm, wind {current['wind_speed_10m']} km/h. "
        f"At {local_time} local. Source: Open-Meteo."
    )
    return text, "open-meteo.com"


async def lookup(question: str, http: httpx.AsyncClient, *, forced: bool = False) -> tuple[str, str]:
    if not forced and not needs_lookup(question):
        return "", ""
    if WEATHER.search(question) and (NOW.search(question) or "forecast" in question.casefold()):
        try:
            return await asyncio.wait_for(_weather(question, http), timeout=18)
        except (httpx.HTTPError, asyncio.TimeoutError, KeyError, ValueError, TypeError):
            pass
    try:
        return await asyncio.wait_for(asyncio.to_thread(_search_sync, question[:250]), timeout=12)
    except Exception:
        return "", ""
