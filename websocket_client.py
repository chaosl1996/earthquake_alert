"""Wolfx WebSocket 实时预警通道。

连接 wss://ws-api.wolfx.jp 的 EEW 通道（cq_eew / sc_eew / cenc_eew）与
cenc_eqlist 速报推送通道。EEW 由预警网在震后数秒自动发布，比轮询速报
快一个量级；断线按指数退避自动重连，服务端心跳保活。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TZ_CHINA, Earthquake, _to_float
from .const import (
    SOURCE_CENC,
    WS_BASE,
    WS_CHANNEL_SOURCES,
    WS_PING_INTERVAL,
    WS_RECONNECT_MAX_DELAY,
)

_LOGGER = logging.getLogger(__name__)


def parse_eew_message(msg: dict[str, Any], channel: str) -> list[Earthquake]:
    """把一条 WebSocket 帧解析为 Earthquake 列表（字段名容错，未知帧返回空）。"""
    source = WS_CHANNEL_SOURCES.get(channel, SOURCE_CENC)
    quakes: list[Earthquake] = []

    def _one(item: dict[str, Any]) -> Earthquake | None:
        # EEW 帧：Mag / EpiCenter / Otime；速报帧：magnitude / location / time
        time_raw = item.get("Otime") or item.get("time") or item.get("OriginTime")
        magnitude = _to_float(item.get("Mag") or item.get("magnitude") or item.get("MagM"))
        latitude = _to_float(item.get("Latitude") or item.get("latitude"))
        longitude = _to_float(item.get("Longitude") or item.get("longitude"))
        if not time_raw or magnitude is None or latitude is None or longitude is None:
            return None
        time_str = str(time_raw).replace("T", " ").split(".")[0][:19]
        try:
            origin_time = (
                datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=TZ_CHINA)
                .astimezone(timezone.utc)
            )
        except ValueError:
            return None
        event_id = str(
            item.get("EventId")
            or item.get("EventID")
            or item.get("Number")
            or f"{channel}-{time_str}"
        )
        intensity = item.get("Intensity") or item.get("intensity")
        return Earthquake(
            event_id=f"{channel}-{event_id}",
            place=str(item.get("EpiCenter") or item.get("location") or "未知"),
            magnitude=magnitude,
            origin_time=origin_time,
            latitude=latitude,
            longitude=longitude,
            depth_km=_to_float(item.get("Depth") or item.get("depth")),
            intensity=str(intensity) if intensity not in (None, "") else None,
            source=source,
        )

    # 速报列表帧形如 {"type":"cenc_eqlist","data":[...]}
    items = msg.get("data") if isinstance(msg.get("data"), list) else [msg]
    for item in items:
        if isinstance(item, dict):
            quake = _one(item)
            if quake:
                quakes.append(quake)
    return quakes


class WolfxWebSocketListener:
    """单通道 WebSocket 监听器：连接后推送帧交给协调器处理，断线自动重连。"""

    def __init__(self, hass: HomeAssistant, coordinator, channel: str) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.channel = channel
        self._task: asyncio.Task | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """启动监听任务（非阻塞，重连循环内部自行管理生命周期）。"""
        self._task = self.hass.async_create_background_task(
            self._run(), name=f"{self.coordinator.name}-ws-{self.channel}"
        )

    async def stop(self) -> None:
        """停止监听并等待任务退出。"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._connected = False

    async def _run(self) -> None:
        session = async_get_clientsession(self.hass)
        url = f"{WS_BASE}/{self.channel}"
        backoff = 5
        while True:
            try:
                # heartbeat：客户端 30s ping 保活，由 aiohttp 自动处理
                async with session.ws_connect(
                    url,
                    heartbeat=WS_PING_INTERVAL,
                    proxy=None,
                    timeout=30,
                ) as ws:
                    _LOGGER.info("实时预警通道已连接: %s", self.channel)
                    self._connected = True
                    backoff = 5
                    async for msg in ws:
                        if msg.type.name == "TEXT":
                            self._handle_text(msg.data)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 — 网络类异常种类多，统一退避重连
                self._connected = False
                self.coordinator.async_set_ws_state(self.channel, False)
                _LOGGER.warning(
                    "实时预警通道 %s 断开，%s 秒后重连: %s",
                    self.channel,
                    backoff,
                    str(err)[:120],
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX_DELAY)

    def _handle_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            msg_type = str(msg.get("type") or "")
            if msg_type in ("heartbeat", "ping"):
                self.coordinator.async_set_ws_state(self.channel, True)
                return
            quakes = parse_eew_message(msg, self.channel)
            if quakes:
                self.coordinator.async_set_ws_state(self.channel, True)
                self.hass.async_create_task(
                    self.coordinator.async_handle_ws_quakes(quakes)
                )
        except (ValueError, TypeError) as err:
            _LOGGER.debug("忽略无法解析的 %s 帧: %s (%s)", self.channel, raw[:80], err)
