"""Client for fetching earthquake quick reports.

主源为中国地震台网速报镜像（api.wolfx.jp，JSON 对象，键 No1..NoN），
失败时降级 USGS GeoJSON feed。所有时间统一转 UTC 存储，展示时转北京时间。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    CENC_URL,
    REQUEST_TIMEOUT,
    SOURCE_CENC,
    SOURCE_USGS,
    USER_AGENT,
    USGS_URL,
)

_LOGGER = logging.getLogger(__name__)

TZ_CHINA = ZoneInfo("Asia/Shanghai")

EARTH_RADIUS_KM = 6371.0

# 地震波平均传播速度（地壳平均值，仅作估算参考）
P_WAVE_KM_S = 6.0  # 纵波：先到，震感较轻
S_WAVE_KM_S = 3.5  # 横波：主震感来源，倒计时以它为准


@dataclass
class Earthquake:
    """一次地震速报。"""

    event_id: str
    place: str
    magnitude: float
    origin_time: datetime  # UTC
    latitude: float
    longitude: float
    depth_km: float | None = None
    # 台网给出的官方烈度（如有）
    intensity: str | None = None
    source: str = SOURCE_CENC
    # 以下字段由 coordinator 按配置坐标补齐
    distance_km: float | None = None
    estimated_intensity: float | None = None
    # 波到达配置坐标的时刻（UTC，按震源距估算）
    p_arrival_time: datetime | None = None
    s_arrival_time: datetime | None = None

    def wave_eta_seconds(self, now: datetime | None = None) -> int | None:
        """S 波（主震感）距到达的剩余秒数，已到达为负数，无估算为 None。"""
        if self.s_arrival_time is None:
            return None
        now = now or datetime.now(timezone.utc)
        return round((self.s_arrival_time - now).total_seconds())

    def event_data(self) -> dict[str, Any]:
        """触发 earthquake_alert 事件时携带的数据（时间为北京时间 ISO 格式）。"""
        return {
            "event_id": self.event_id,
            "magnitude": self.magnitude,
            "place": self.place,
            "distance_km": round(self.distance_km, 1)
            if self.distance_km is not None
            else None,
            "depth_km": self.depth_km,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "origin_time": self.origin_time.astimezone(TZ_CHINA).isoformat(),
            "estimated_intensity": self.estimated_intensity,
            "intensity": self.intensity,
            # 波到达信息：eta_seconds 为 S 波剩余秒数（可为负），arrival_time 为其北京时间
            "eta_seconds": self.wave_eta_seconds(),
            "p_wave_eta_seconds": round(
                (self.p_arrival_time - datetime.now(timezone.utc)).total_seconds()
            )
            if self.p_arrival_time
            else None,
            "arrival_time": self.s_arrival_time.astimezone(TZ_CHINA).isoformat()
            if self.s_arrival_time
            else None,
            "felt": felt_description(self.estimated_intensity)
            if self.estimated_intensity is not None
            else None,
            "source": self.source,
        }


@dataclass
class EarthquakeUpdate:
    """一次刷新得到的全部数据。"""

    quakes: list[Earthquake] = field(default_factory=list)
    fetched_at: datetime | None = None


def _to_float(value: Any) -> float | None:
    """接口字段为 str/num 混合，统一容错转换。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点间球面距离（公里）。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_intensity(magnitude: float, distance_km: float) -> float:
    """按经验公式估算烈度：I = M - 1.5·log10(d/10)，下限 1.0（仅为粗略参考）。"""
    return max(
        1.0,
        round(magnitude - 1.5 * math.log10(max(distance_km, 1.0) / 10.0), 1),
    )


def felt_description(intensity: float) -> str:
    """按估算烈度给出通俗震感描述（参考中国地震烈度表，粗略分级）。"""
    if intensity < 2:
        return "多数人无感"
    if intensity < 3:
        return "轻微震感，静止的人有感"
    if intensity < 4:
        return "明显震感，门窗作响、悬挂物晃动"
    if intensity < 5:
        return "强烈震感，不稳物品可能坠落"
    if intensity < 6:
        return "剧烈震动，物品坠落、家具移位"
    return "破坏性震动，建筑可能受损"


def compute_wave_arrivals(quake: Earthquake, target_lat: float, target_lon: float) -> None:
    """按震源距估算 P/S 波到达配置坐标的时刻（就地补齐到 quake 上）。

    震源距 = sqrt(震中距² + 深度²)，深度未知时按震中距近似。
    """
    depth = quake.depth_km or 0.0
    hypocentral = math.hypot(quake.distance_km or 0.0, depth)
    quake.p_arrival_time = quake.origin_time + timedelta(
        seconds=hypocentral / P_WAVE_KM_S
    )
    quake.s_arrival_time = quake.origin_time + timedelta(
        seconds=hypocentral / S_WAVE_KM_S
    )


def parse_cenc(payload: dict[str, Any]) -> list[Earthquake]:
    """解析中国地震台网速报列表（wolfx 镜像格式）。"""
    quakes: list[Earthquake] = []
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        time_str = item.get("time")
        magnitude = _to_float(item.get("magnitude"))
        latitude = _to_float(item.get("latitude"))
        longitude = _to_float(item.get("longitude"))
        if not time_str or magnitude is None or latitude is None or longitude is None:
            continue
        try:
            origin_time = (
                datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=TZ_CHINA)
                .astimezone(timezone.utc)
            )
        except ValueError:
            continue
        intensity = item.get("intensity")
        quakes.append(
            Earthquake(
                event_id=str(item.get("EventID") or f"{time_str}-{item.get('location')}"),
                place=str(item.get("location") or "未知"),
                magnitude=magnitude,
                origin_time=origin_time,
                latitude=latitude,
                longitude=longitude,
                depth_km=_to_float(item.get("depth")),
                intensity=str(intensity) if intensity not in (None, "") else None,
                source=SOURCE_CENC,
            )
        )
    if not quakes:
        raise ValueError("未能从中国地震台网镜像解析到任何地震速报数据")
    return quakes


def parse_usgs(payload: dict[str, Any]) -> list[Earthquake]:
    """解析 USGS GeoJSON feed（降级数据源）。"""
    quakes: list[Earthquake] = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        magnitude = _to_float(props.get("mag"))
        time_ms = props.get("time")
        if magnitude is None or time_ms is None or len(coords) < 2:
            continue
        quakes.append(
            Earthquake(
                event_id=str(feature.get("id") or time_ms),
                place=str(props.get("place") or "未知"),
                magnitude=magnitude,
                origin_time=datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc),
                latitude=float(coords[1]),
                longitude=float(coords[0]),
                depth_km=_to_float(coords[2]) if len(coords) > 2 else None,
                source=SOURCE_USGS,
            )
        )
    if not quakes:
        raise ValueError("未能从 USGS 解析到任何地震速报数据")
    return quakes


async def _fetch_json(session: aiohttp.ClientSession, url: str) -> Any:
    headers = {"User-Agent": USER_AGENT}
    try:
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        ) as response:
            response.raise_for_status()
            # content_type=None：容忍镜像站未按标准返回 application/json
            return await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ConnectionError(f"请求地震数据失败: {url}") from err


async def async_fetch_earthquakes(session: aiohttp.ClientSession) -> list[Earthquake]:
    """抓取地震速报：优先中国地震台网镜像，失败降级 USGS。"""
    try:
        return parse_cenc(await _fetch_json(session, CENC_URL))
    except (ConnectionError, ValueError) as err:
        _LOGGER.warning("中国地震台网镜像获取失败，改用 USGS: %s", err)
    return parse_usgs(await _fetch_json(session, USGS_URL))
