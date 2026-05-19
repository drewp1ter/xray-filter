import os
import re
import base64
import asyncio
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.lib.utils import download_text_file, filter_unique, is_valid_source_url, get_validated_proxies, extract_proxy_target, get_seen_online_proxies, update_seen_online_proxies
from app.lib.constants import PROMETHEUS_PUSHGATEWAY_URL
from app.lib.db import get_connection
from app.lib.channel import make_post
import httpx

router = APIRouter()


@router.get("/proxies", response_class=PlainTextResponse, )
def get_proxies(
    filter_type: str | None = Query(default=None, pattern="^(hiddify)$")
):
    lists = os.getenv("PROXY_LISTS", "")
    if not lists:
        raise HTTPException(status_code=500, detail="No proxy list URLs configured")

    urls = [url for url in re.split(r"\s*[;,\n]\s*", lists) if url and is_valid_source_url(url)]
    if not urls:
        raise HTTPException(status_code=500, detail="No valid proxy list URLs configured")

    proxy_lines: list[str] = get_seen_online_proxies()
    with ThreadPoolExecutor(max_workers=min(4, len(urls))) as executor:
        futures = {executor.submit(download_text_file, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                proxy_lines.extend(future.result().splitlines())
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to download proxy list from {url}: {exc}")
    proxies = filter_unique(proxy_lines)
        
    if filter_type == "hiddify":
        proxies = [line for line in proxies if 'xtls-rprx-vision-udp443' not in line]

    return PlainTextResponse(content="\n".join(proxies), media_type="text/plain", headers={"profile-update-interval": "24"})


@router.get("/proxies/online", response_class=PlainTextResponse)
async def get_online_proxies():    
    validated_proxies = sorted(await get_validated_proxies(), key=lambda p: p.latencyMs if p.latencyMs > 0 else float('inf'))
    online_proxies = []
    connection = get_connection()
    cursor = connection.cursor()
    for proxy in validated_proxies:
        if not proxy.online or proxy.latencyMs >= 10000:
            continue
        decodedURL = base64.b64decode(proxy.originalData).decode('utf-8')
        online_proxies.append(f"**{proxy.latencyMs}ms** | `{unquote(proxy.name)}`\n```\n{decodedURL}\n```\n")
        _, _, authority = extract_proxy_target(decodedURL)
        cursor.execute("SELECT 1 FROM seen_online WHERE authority = ?", (authority,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO seen_online (name, authority, url) VALUES (?, ?, ?)", (proxy.name, authority, decodedURL))    
        else:
            cursor.execute("UPDATE seen_online SET last_seen = CURRENT_TIMESTAMP WHERE authority = ?", (authority,))       
    connection.commit()
    connection.close()
    return "\n".join(online_proxies)


@router.post("/metrics/push")
async def push_metrics(body: str = Body(..., media_type="text/plain")):
    try:
        response = httpx.post(PROMETHEUS_PUSHGATEWAY_URL, content=body, headers={"Content-Type": "text/plain"})
        response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to push metrics to Prometheus Pushgateway: {exc}")
    
    asyncio.create_task(make_post())
    return {"status": "success", "message": "Metrics pushed successfully"}


