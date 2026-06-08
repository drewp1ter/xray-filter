import os
import re
import asyncio
import base64
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.lib.utils import download_text_file, filter_unique, is_valid_source_url, get_seen_online_proxies, read_proxy_list_from_file, numerate_non_unique_proxies_names, get_validated_proxies
from app.lib.constants import PROMETHEUS_PUSHGATEWAY_URL, TG_PROXY
from app.lib.channel import make_post
import httpx

router = APIRouter()

last_seen_online_proxies: list[str] = []
locked = False

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
    proxy_lines.extend(read_proxy_list_from_file("/usr/share/subs.txt"))
    with ThreadPoolExecutor(max_workers=min(4, len(urls))) as executor:
        futures = {executor.submit(download_text_file, url, proxy=TG_PROXY): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                proxy_lines.extend(future.result().splitlines())
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to download proxy list from {url}: {exc}")
    proxies = filter_unique(proxy_lines)
    proxies = numerate_non_unique_proxies_names(proxies)
        
    if filter_type == "hiddify":
        proxies = [line for line in proxies if 'xtls-rprx-vision-udp443' not in line]
    global locked
    locked = True
    return PlainTextResponse(content="\n".join(proxies), media_type="text/plain", headers={"profile-update-interval": "24"})


@router.post("/metrics/push")
async def push_metrics(body: str = Body(..., media_type="text/plain")):
    try:
        response = httpx.post(PROMETHEUS_PUSHGATEWAY_URL, content=body, headers={"Content-Type": "text/plain"})
        response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to push metrics to Prometheus Pushgateway: {exc}")
    
    asyncio.create_task(make_post())
    global locked
    locked = False
    return {"status": "success", "message": "Metrics pushed successfully"}


@router.get("/proxies/online", response_class=PlainTextResponse)
async def get_online_proxies():    
    validated_proxies = sorted(await get_validated_proxies(), key=lambda p: p.latencyMs if p.latencyMs > 0 else float('inf'))
    online_proxies = []
    for proxy in validated_proxies:
        if not proxy.online:
            continue
        decodedURL = base64.b64decode(proxy.originalData).decode('utf-8')
        online_proxies.append(decodedURL)
    sub = "#profile-title: WhiteList\n" + \
          "#profile-locked: false\n" + \
          "#profile-update-interval: 1\n"
    global last_seen_online_proxies, locked
    if (len(online_proxies) > 0 and not locked) or len(last_seen_online_proxies) == 0:
        last_seen_online_proxies = online_proxies
    sub += "\n" + "\n".join(last_seen_online_proxies)
    return sub