"""Bounded, nonprivileged public web evidence for conversational replies.

No admin tools, private data, paywalls, or execution of retrieved content.
A keyless metasearch library can be rate-limited/unavailable; fail explicitly.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import time
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

# SearXNG is useful only when the operator configures a stable, private service
# address. Never bake a Docker container IP into application code: those are
# ephemeral. Several trusted endpoints can be comma-separated for fallback.
SEARXNG_URLS_ENV = "ROBORATH_SEARXNG_URLS"
_searx_failures: dict[str, float] = {}
_SEARX_COOLDOWN_SECONDS = 30.0

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
    items = _searxng(query)
    if not items:
        items = _ddgs_search(query)
    if not items:
        try:
            items=_bing_rss(query)
        except (httpx.HTTPError, ElementTree.ParseError, ValueError):
            items=[]
    return _format_results(items)


def _searxng(query: str) -> list[dict[str, str]]:
    """Query configured SearXNG instances; failure is isolated per endpoint.

    Endpoints are trusted operator configuration, not chat input. Only HTTP(S)
    origins without userinfo, query, fragment or nonstandard ports are allowed.
    Redirects are disabled, responses are size-limited, and linked pages are
    never fetched here.
    """
    endpoints = [value.strip().rstrip("/") for value in
                 os.getenv(SEARXNG_URLS_ENV, "").split(",") if value.strip()]
    now = time.monotonic()
    for endpoint in endpoints[:3]:
        try:
            parsed = urlsplit(endpoint)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                    parsed.username or parsed.password or parsed.query or parsed.fragment or
                    not re.fullmatch(r"[A-Za-z0-9._:-]+", parsed.hostname)):
                continue
            if _searx_failures.get(endpoint, 0) > now:
                continue
            with httpx.stream(
                    "GET", endpoint + "/search",
                    params={"q": query[:250], "format": "json",
                            "language": "en", "categories": "general"},
                    headers={"Accept": "application/json", "User-Agent": "RoboRath/0.1 search"},
                    timeout=4, follow_redirects=False) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 512_000:
                        raise ValueError("SearXNG response too large")
            data = json.loads(body)
            results = data.get("results", [])
            if not isinstance(results, list):
                raise ValueError("SearXNG response schema invalid")
            items = []
            for result in results[:10]:
                if not isinstance(result, dict):
                    continue
                url = str(result.get("url") or result.get("pretty_url") or "")
                title = str(result.get("title") or "")
                if _safe_search_result(url) and title.strip():
                    items.append({"href": url, "title": title})
            _searx_failures.pop(endpoint, None)
            if items:
                return items
        except Exception:
            # Treat network, transport and malformed-provider failures alike;
            # DDGS and Bing remain independently available.
            _searx_failures[endpoint] = now + _SEARX_COOLDOWN_SECONDS
    return []


def _safe_search_result(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        try:
            ipaddress.ip_address(host.strip("[]"))
            return False
        except ValueError:
            pass
        return (parsed.scheme == "https" and bool(host) and not parsed.username and
                not parsed.password and parsed.port in (None, 443) and
                "." in host and not host.endswith((".local", ".internal", ".localhost")) and
                len(url) <= 2048)
    except ValueError:
        return False


def _ddgs_search(query: str) -> list[dict[str, str]]:
    """Try keyless DDGS backends in order; never fabricate on provider error."""
    try:
        from ddgs import DDGS
        for backend in ("google", "bing"):
            try:
                with DDGS(timeout=7) as client:
                    items = client.text(query, backend=backend, max_results=3) or []
                if items:
                    return items
            except Exception:
                continue
    except ImportError:
        pass
    return []


def _format_results(items: list[dict[str, str]]) -> tuple[str, str]:
    """Present titles and public URLs as discovery leads, never verified facts."""
    lines = []
    first_domain = ""
    seen_urls: set[str] = set()
    seen_domains: set[str] = set()
    for item in items[:10]:
        if len(lines) >= 2:
            break
        url = str(item.get("href") or item.get("url") or "")
        if not _safe_search_result(url):
            continue
        parsed = urlsplit(url)
        domain = (parsed.hostname or "").removeprefix("www.")
        canonical_url = parsed._replace(fragment="").geturl()
        if canonical_url in seen_urls or domain in seen_domains:
            continue
        seen_urls.add(canonical_url)
        seen_domains.add(domain)
        title = re.sub(r"\s+", " ", str(item.get("title", "")))[:95]
        # Do not relay snippets: search providers return untrusted text and the
        # title is only a discovery lead, not evidence that a claim is true.
        title = re.sub(r"[\x00-\x1f\x7f]", " ", title).strip()
        if not title:
            continue
        if not first_domain:
            first_domain = domain
        lines.append(f"{title} ({domain}) {url[:230]}")
    if not lines:
        return "", ""
    return "Search leads only; titles are not verified facts: " + " | ".join(lines), first_domain


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
