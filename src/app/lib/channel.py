
import base64
from datetime import datetime, timedelta
from app.lib.utils import get_validated_proxies, update_seen_online_proxies
from app.lib.tg import get_last_sent_message_age_in_seconds, send_telegram_message, cleanup_telegram_messages
from app.lib.db import get_connection
from app.lib.prometheus import fetch_uptime_stats
from app.lib.constants import MAKE_POST_INTERVAL_SECONDS

MAX_LATENCY_MS = 20000

async def make_post():    
    online_proxies = [proxy for proxy in await get_validated_proxies() if proxy.online]
    print(f"Found {len(online_proxies)} online proxies.")
    await update_seen_online_proxies(online_proxies)

    if not can_make_new_post(MAKE_POST_INTERVAL_SECONDS):
        print("Cooldown active. Skipping post.")
        return

    uptime_stats = await fetch_uptime_stats()
    print(f"Fetched uptime stats for {len(uptime_stats)} proxies.")
    online_proxies_data = []
    connection = get_connection()
    cursor = connection.cursor()
    created_at_list = cursor.execute(
        "SELECT stable_id, datetime(created_at, '+3 hours') AS created_at FROM seen_online WHERE stable_id IN ({seq})"
        .format(seq=','.join(['?']*len(online_proxies))), 
        [proxy.stableId for proxy in online_proxies]
    ).fetchall()

    connection.close()
        
    for proxy in online_proxies:
        if proxy.latencyMs > MAX_LATENCY_MS:
            print(f"Skipping proxy {proxy.name} due to high latency: {proxy.latencyMs}ms")
            continue
        decoded_url = base64.b64decode(proxy.originalData).decode('utf-8')
        print(decoded_url)
        created_at = next((row["created_at"] for row in created_at_list if row["stable_id"] == proxy.stableId), None)
        online_proxies_data.append({ "name": proxy.name, "decoded_url": decoded_url, "latency": proxy.latencyMs, "created_at": created_at, "uptime": uptime_stats.get(proxy.stableId, 100) })
    
    if len(online_proxies_data) > 0:
        online_proxies_data = sorted(online_proxies_data, key=lambda p: (p["uptime"], -datetime.strptime(p["created_at"], "%Y-%m-%d %H:%M:%S").timestamp(), -p["latency"]), reverse=True)
        message = "\n".join([f"**{p['latency']}ms** | `{p['name']}`\n`добавлен: {p['created_at']} | аптайм: {p['uptime'] if p['uptime'] > 0 else 100}%`\n```\n{p['decoded_url']}\n```\n" for p in online_proxies_data])
        await cleanup_telegram_messages()
        await send_telegram_message(message)
        print(f"Posted {len(online_proxies_data)} proxies to Telegram.")
    else:
        print("No online proxies to post. Cleaning up old messages.")
        await cleanup_telegram_messages()    
    

def can_make_new_post(cooldown_seconds: int) -> bool:
    now_hour = (datetime.now() + timedelta(hours=3)).hour
    if now_hour < 6:
        return False

    age = get_last_sent_message_age_in_seconds()
    return age is None or age >= cooldown_seconds