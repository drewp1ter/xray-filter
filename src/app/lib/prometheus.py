from pydantic import BaseModel
from typing import Literal
import httpx
from app.lib.constants import PROMETHEUS_API_URL, PROMETHEUS_QUERY

class PrometheusMetric(BaseModel):
    address: str
    job: Literal["xray-checker"]
    name: str | None = None
    protocol: Literal["vless", "trojan", "ss", "shadowsocks", "vmess", "hysteria", "hysteria2"]
    stable_id: str


PrometheusValue = tuple[float, str]


class PrometheusResultItem(BaseModel):
    metric: PrometheusMetric
    value: PrometheusValue


class PrometheusData(BaseModel):
    resultType: Literal["vector"]
    result: list[PrometheusResultItem]


class PrometheusResponse(BaseModel):
    status: Literal["success"]
    data: PrometheusData


StableId = str
UptimeStats = dict[StableId, int]


async def fetch_uptime_stats() -> UptimeStats:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(PROMETHEUS_API_URL + "/query", params={"query": PROMETHEUS_QUERY})
        response.raise_for_status()
        data = PrometheusResponse.model_validate(response.json())
        stats = {}
        for item in data.data.result:
            stats[item.metric.stable_id] = int(float(item.value[1]))
        return stats
    except Exception as exc:
        print(f"Failed to fetch uptime stats from Prometheus: {exc}")
        return {}
