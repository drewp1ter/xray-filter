import os
import re
import base64
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.utils.utils import download_text_file, filter_unique, is_valid_source_url, get_validated_proxies

router = APIRouter()


@router.get("/proxies", response_class=PlainTextResponse)
def get_proxies():
    lists = os.getenv("PROXY_LISTS", "")
    if not lists:
        raise HTTPException(status_code=500, detail="No proxy list URLs configured")

    urls = [url for url in re.split(r"\s*[;,\n]\s*", lists) if url and is_valid_source_url(url)]
    if not urls:
        raise HTTPException(status_code=500, detail="No valid proxy list URLs configured")

    proxy_lines: list[str] = []

    with ThreadPoolExecutor(max_workers=min(4, len(urls))) as executor:
        futures = {executor.submit(download_text_file, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                proxy_lines.extend(future.result().splitlines())
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to download proxy list from {url}: {exc}")

    proxies = filter_unique(proxy_lines)
    return PlainTextResponse(content="\n".join(proxies), media_type="text/plain", headers={"profile-update-interval": "24"})


@router.get("/proxies/count")
def get_proxies_count():
    global proxies
    return {"count": len(proxies)}


@router.get("/proxies/online", response_class=PlainTextResponse)
async def get_online_proxies():    
    validated_proxies = sorted(await get_validated_proxies(), key=lambda p: p.latencyMs if p.latencyMs > 0 else float('inf'))
    online_proxies = [f"**{p.latencyMs}ms** | `{unquote(p.name)}`\n```\n{base64.b64decode(p.originalData).decode('utf-8')}\n```\n" for p in validated_proxies if p.online and p.latencyMs < 10000]
    return "\n".join(online_proxies)
