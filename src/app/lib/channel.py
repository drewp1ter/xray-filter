
import base64
from datetime import datetime
from app.lib.utils import get_validated_proxies, update_seen_online_proxies
from app.lib.tg import get_last_sent_message_age_in_seconds, send_telegram_message, cleanup_telegram_messages
from app.lib.db import get_connection
from app.lib.prometheus import fetch_uptime_stats
from app.lib.constants import MAKE_POST_INTERVAL_SECONDS

async def make_post():    
    online_proxies = [proxy for proxy in await get_validated_proxies() if proxy.online]
    await update_seen_online_proxies(online_proxies)

    if not can_make_new_post(MAKE_POST_INTERVAL_SECONDS):
        return

    uptime_stats = await fetch_uptime_stats()
    online_proxies_data = []
    connection = get_connection()
    cursor = connection.cursor()
    created_at_list = cursor.execute(
        "SELECT stable_id, created_at FROM seen_online WHERE stable_id IN ({seq})"
        .format(seq=','.join(['?']*len(online_proxies))), 
        [proxy.stableId for proxy in online_proxies]
    ).fetchall()

    connection.close()
        
    for proxy in online_proxies:
        decodedURL = base64.b64decode(proxy.originalData).decode('utf-8')
        created_at = next((row["created_at"] for row in created_at_list if row["stable_id"] == proxy.stableId), None)
        online_proxies_data.append({ "name": proxy.name, "url": decodedURL, "latency": proxy.latencyMs, "created_at": created_at, "uptime": uptime_stats.get(proxy.stableId, 100) })
    
    online_proxies_data = sorted(online_proxies_data, key=lambda p: (p["uptime"], -datetime.strptime(p["created_at"], "%Y-%m-%d %H:%M:%S").timestamp()), reverse=True)
    message = "\n".join([f"**{p['latency']}ms** | `{p['name']}`\n`добавлен: {p['created_at']} | аптайм: {p['uptime']}%`\n```\n{p['url']}\n```\n" for p in online_proxies_data])

    await cleanup_telegram_messages()
    await send_telegram_message(message)
    

def can_make_new_post(cooldown_seconds: int) -> bool:
    age = get_last_sent_message_age_in_seconds()
    return age is None or age >= cooldown_seconds