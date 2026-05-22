from urllib.request import urlopen, ProxyHandler, build_opener
from urllib.parse import urlsplit, unquote
import httpx
from fastapi import HTTPException
from typing import Literal
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.lib.db import get_connection
from app.lib.constants import XRAY_CHECKER_URL
import base64
import ipaddress
import socket
import re


def download_text_file(url: str, encoding: str = "utf-8", timeout: float = 15.0, proxy: str | None = None) -> str:
  if proxy:
    parsed_url = urlsplit(url)
    proxy_scheme = parsed_url.scheme or "http"
    opener = build_opener(ProxyHandler({proxy_scheme: proxy}))
    with opener.open(url, timeout=timeout) as response:
      data = response.read()
  else:
    with urlopen(url, timeout=timeout) as response:
      data = response.read()
  return data.decode(encoding)


def extract_proxy_target(line: str) -> tuple[str, int, str] | None:
  candidate = line.strip()
  if not candidate:
    return None

  try:
    parsed = urlsplit(candidate)
    if parsed.netloc and (parsed.hostname is None or parsed.port is None):
      return None
    return parsed.hostname, parsed.port, parsed.netloc
  except:
    return None


def filter_unique(lines: list[str]) -> list[str]:
  unique_lines_step_1: list[str] = []
  unique_lines_step_2: list[str] = []
  seen_authorities: set[str] = set()
  not_resolved: set[str] = set()
  resolved: dict[str, str] = {}
  resolved_ips: set[str] = set()

  for line in lines:
    target = extract_proxy_target(line)
    if target is None:
      continue
    hostname, _, authority = target
    if authority in seen_authorities or hostname == '0.0.0.0':
      continue
    seen_authorities.add(authority)
    if not is_ip_address(hostname) :
      not_resolved.add(hostname)
    unique_lines_step_1.append(line)

  with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(socket.gethostbyname, hostname): hostname for hostname in not_resolved}
    for future in as_completed(futures):
      hostname = futures[future]
      try:
        if future.result() not in resolved and future.result() != '0.0.0.0':
          resolved[hostname] = future.result()
          resolved_ips.add(future.result())
        print(f"Resolved {hostname} to {future.result()}")
      except Exception:
        pass

  for line in unique_lines_step_1:
    target = extract_proxy_target(line)
    hostname, _, authority = target
    if "extra=" in line and not re.search(r"extra=\{.+\}|extra=null", line):
      continue
    if is_ip_address(hostname):
      if hostname in resolved_ips:
        continue
    else:
       line = line.replace(f"@{hostname}", f"@{resolved[hostname]}") if hostname in resolved else line
    unique_lines_step_2.append(re.sub(r"%20t\.me%2Frjsxrd|\s+t\.me/rjsxrd", "", line))

  return unique_lines_step_2


def is_valid_source_url(url: str) -> bool:
  parsed = urlsplit(url.strip())
  return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_ip_address(host: str) -> bool:
  try:
    ipaddress.ip_address(host)
    return True
  except ValueError:
    return False
  
class ProxyItem(BaseModel):
    index: int
    stableId: str
    name: str
    subName: str
    server: str
    port: int
    protocol: Literal["vless", "trojan", "ss", "shadowsocks", "vmess", "hysteria", "hysteria2"]
    proxyPort: int
    online: bool
    latencyMs: int
    originalData: str


class ProxiesResponse(BaseModel):
    success: bool
    data: list[ProxyItem]


async def get_validated_proxies() -> list[ProxyItem]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(XRAY_CHECKER_URL + "/api/v1/proxies")
        response.raise_for_status()
        data = ProxiesResponse.model_validate(response.json())
        if not data.success:
            raise HTTPException(
                status_code=502,
                detail="External API returned unsuccessful response",
            )
        return data.data
           
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=error.response.status_code,
            detail="External API returned an error",
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Cannot connect to external API",
        )
    
    
async def update_seen_online_proxies(proxies: list[ProxyItem]):    
    connection = get_connection()
    cursor = connection.cursor()
    for proxy in proxies:
        if not proxy.online:
            continue
        cursor.execute("SELECT 1 FROM seen_online WHERE stable_id = ?", (proxy.stableId,))
        if cursor.fetchone() is None:
            decodedURL = base64.b64decode(proxy.originalData).decode('utf-8')
            cursor.execute("INSERT INTO seen_online (name, stable_id, url) VALUES (?, ?, ?)", (proxy.name, proxy.stableId, decodedURL))    
        else:
            cursor.execute("UPDATE seen_online SET last_seen = CURRENT_TIMESTAMP WHERE stable_id = ?", (proxy.stableId,))       
    connection.commit()
    connection.close()


def get_seen_online_proxies() -> list[str]:
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT url FROM seen_online")
    proxy_lines: list[str] = [row["url"] for row in cursor.fetchall()]
    connection.close()
    return proxy_lines