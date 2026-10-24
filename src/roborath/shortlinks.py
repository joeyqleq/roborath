"""Source-only shortener: no user-supplied arbitrary URL-shortening service."""
from __future__ import annotations
import asyncio
import ipaddress
import re
from urllib.parse import urlsplit

URL = re.compile(r"https?://[^\s<>\])}]+",re.I)

def public_source_url(url:str)->bool:
    try:
        p=urlsplit(url)
        if p.scheme not in {"https","http"} or p.username or p.password or p.port not in (None,80,443):
            return False
        host=p.hostname or ""
        if not host or "." not in host or host.endswith((".local",".internal",".localhost")):
            return False
        try:
            ipaddress.ip_address(host.strip("[]"))
            return False
        except ValueError: pass
        if len(url)>2048: return False
        return True
    except ValueError: return False

async def shorten_sources(text:str,http_client,limit:int=2):
    """Only rewrite http(s) citations already in the verified AI response.

    Never return unshortened URLs. is.gd may be unavailable or rate-limited;
    in that case the output visibly records a missing shortlink.
    """
    raw=str(text)
    output=[]
    last=0
    count=0
    for match in URL.finditer(raw):
        output.append(raw[last:match.start()])
        url=match.group().rstrip(".,")
        tail=match.group()[len(url):]
        replacement="[source link unavailable]"
        if count<limit and public_source_url(url):
            try:
                reply=await http_client.get("https://is.gd/create.php",
                        params={"format":"simple","url":url},timeout=6)
                if reply.status_code==200:
                    candidate=reply.text.strip()
                    parsed=urlsplit(candidate)
                    if parsed.scheme=="https" and parsed.hostname in {"is.gd","v.gd"} and len(candidate)<50:
                        replacement=candidate
            except Exception:
                pass
        output.append(replacement+tail)
        count+=1
        last=match.end()
    output.append(raw[last:])
    return "".join(output)
