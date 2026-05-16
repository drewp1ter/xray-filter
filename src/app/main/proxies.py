import os
import re
import base64
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from uptime_kuma_api import MonitorType, UptimeKumaApi
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.utils.utils import download_text_file, filter_unique, is_valid_source_url, get_validated_proxies, extract_proxy_target
from app.constants import KUMA_URL, KUMA_LOGIN, KUMA_PASSWORD, XRAY_CHECKER_URL
from app.db import get_connection

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

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT url FROM seen_online")
    proxy_lines: list[str] = [row["url"] for row in cursor.fetchall()]
    connection.close()

    with ThreadPoolExecutor(max_workers=min(4, len(urls))) as executor:
        futures = {executor.submit(download_text_file, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                proxy_lines.extend(future.result().splitlines())
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to download proxy list from {url}: {exc}")

    proxies = filter_unique(sorted(proxy_lines, key=lambda line: line.strip().lower()))
        
    if filter_type == "hiddify":
        proxies = [line for line in proxies if 'xtls-rprx-vision-udp443' not in line]

    return PlainTextResponse(content="\n".join(proxies), media_type="text/plain", headers={"profile-update-interval": "24"})


@router.get("/proxies/count")
def get_proxies_count():
    global proxies
    return {"count": len(proxies)}


@router.get("/proxies/online", response_class=PlainTextResponse)
async def get_online_proxies():    
    validated_proxies = sorted(await get_validated_proxies(), key=lambda p: p.latencyMs if p.latencyMs > 0 else float('inf'))
    online_proxies = []
    connection = get_connection()
    cursor = connection.cursor()
    is_kuma_available = False
    with UptimeKumaApi(KUMA_URL) as kuma:
        try:
            kuma.login(KUMA_LOGIN, KUMA_PASSWORD)
            is_kuma_available = True
        except Exception as exc:
            print(f"Failed to login to Uptime Kuma: {exc}")
        for proxy in validated_proxies:
            if not proxy.online or proxy.latencyMs >= 10000:
                continue
            decodedURL = base64.b64decode(proxy.originalData).decode('utf-8')
            online_proxies.append(f"**{proxy.latencyMs}ms** | `{unquote(proxy.name)}`\n```\n{decodedURL}\n```\n")
            _, _, authority = extract_proxy_target(decodedURL)
            cursor.execute("SELECT 1 FROM seen_online WHERE authority = ?", (authority,))
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO seen_online (name, authority, url) VALUES (?, ?, ?)", (proxy.name, authority, decodedURL))
                if is_kuma_available:
                    try:
                        kuma.add_monitor(
                            type=MonitorType.HTTP,      
                            name=proxy.name,
                            url=f"{XRAY_CHECKER_URL}/config/{proxy.stableId}",
                            interval=1800,
                            maxretries=3,
                            retryInterval=60,
                            description=decodedURL
                        )
                    except Exception as exc:
                        print(f"Failed to add monitor for {proxy.name} in Uptime Kuma: {exc}")
                        cursor.execute("DELETE FROM seen_online WHERE authority = ?", (authority,))    
            else:
                cursor.execute("UPDATE seen_online SET last_seen = CURRENT_TIMESTAMP WHERE authority = ?", (authority,))    
        kuma.disconnect()       
    connection.commit()
    connection.close()
    return "\n".join(online_proxies)
