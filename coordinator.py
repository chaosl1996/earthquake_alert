"""Coordinator that polls earthquake quick reports and fires alert events."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TZ_CHINA,
    Earthquake,
    EarthquakeUpdate,
    async_fetch_earthquakes,
    compute_wave_arrivals,
    estimate_intensity,
    felt_description,
    haversine_km,
)
from .const import (
    ALERT_DURATION,
    CONF_MIN_MAGNITUDE,
    CONF_RADIUS_KM,
    DEFAULT_MIN_MAGNITUDE,
    DEFAULT_RADIUS_KM,
    EVENT_EARTHQUAKE,
    FIRED_IDS_MAX,
    MANUFACTURER,
)

_LOGGER = logging.getLogger(__name__)


class EarthquakeCoordinator(DataUpdateCoordinator[EarthquakeUpdate]):
    """所有实体共享一个协调器，每次更新拉取一次速报列表并按配置评估告警。"""

    def __init__(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        options: dict[str, Any],
        scan_interval: timedelta,
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.radius_km = float(options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
        self.min_magnitude = float(options.get(CONF_MIN_MAGNITUDE, DEFAULT_MIN_MAGNITUDE))
        self._fired_ids: set[str] = set()
        self._ws_channels: dict[str, bool] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=MANUFACTURER,
            update_interval=scan_interval,
        )

    @property
    def latest(self) -> Earthquake | None:
        """最新一条速报（按发震时间倒序后的第一条）。"""
        if self.data and self.data.quakes:
            return self.data.quakes[0]
        return None

    @property
    def alerting(self) -> Earthquake | None:
        """当前告警对应的地震（阈值命中且在持续期内），无则 None。"""
        if not self.data:
            return None
        for quake in self.data.quakes:  # 已按发震时间倒序
            if quake.magnitude >= self.min_magnitude and (
                quake.distance_km or 0
            ) <= self.radius_km:
                # 最新一条合格地震已超出告警持续期即视为解除
                if quake.origin_time + ALERT_DURATION >= datetime.now(timezone.utc):
                    return quake
                return None
        return None

    def quake_attributes(self, quake: Earthquake | None) -> dict[str, Any]:
        """实体共享的中文属性（时间均为北京时间）。"""
        if quake is None:
            return {}
        attrs: dict[str, Any] = {
            "震中": quake.place,
            "震级": quake.magnitude,
            "深度（公里）": quake.depth_km,
            "发震时刻": quake.origin_time.astimezone(TZ_CHINA).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "距本机距离（公里）": round(quake.distance_km, 1)
            if quake.distance_km is not None
            else None,
            "估算烈度": quake.estimated_intensity,
            "官方烈度": quake.intensity,
            "震感预估": felt_description(quake.estimated_intensity)
            if quake.estimated_intensity is not None
            else None,
            "预计P波到达": quake.p_arrival_time.astimezone(TZ_CHINA).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if quake.p_arrival_time
            else None,
            "预计S波到达": quake.s_arrival_time.astimezone(TZ_CHINA).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if quake.s_arrival_time
            else None,
            "S波倒计时（秒）": max(0, quake.wave_eta_seconds() or 0),
            "纬度": quake.latitude,
            "经度": quake.longitude,
            "数据来源": quake.source,
            "实时预警通道": self.ws_status_text,
        }
        if self.data and self.data.fetched_at:
            attrs["数据更新时间"] = self.data.fetched_at.astimezone(TZ_CHINA).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return attrs

    async def async_handle_ws_quakes(self, quakes: list[Earthquake]) -> None:
        """WebSocket 推送入口：评估告警并把地震并入实体数据（按发震时间倒序）。"""
        changed = False
        for quake in quakes:
            await self.async_evaluate_quake(quake)
            data = self.data or EarthquakeUpdate(quakes=[], fetched_at=None)
            existing = [q for q in data.quakes if q.event_id != quake.event_id]
            existing.append(quake)
            existing.sort(key=lambda q: q.origin_time, reverse=True)
            self.data = EarthquakeUpdate(
                quakes=existing[:50],
                fetched_at=datetime.now(timezone.utc),
            )
            changed = True
        if changed:
            self.async_update_listeners()

    @property
    def ws_status_text(self) -> str:
        """实时预警通道连接状态文案（供实体属性展示）。"""
        if not self._ws_channels:
            return "未启用"
        on = sorted(name for name, ok in self._ws_channels.items() if ok)
        off = sorted(name for name, ok in self._ws_channels.items() if not ok)
        parts = [f"{n} 已连接" for n in on] + [f"{n} 未连接" for n in off]
        return "，".join(parts)

    def register_ws_channel(self, channel: str) -> None:
        """登记一个实时预警通道（初始为未连接）。"""
        self._ws_channels[channel] = False

    def async_set_ws_state(self, channel: str, connected: bool) -> None:
        """更新通道连接状态，变化时刷新实体属性。"""
        if self._ws_channels.get(channel) != connected:
            self._ws_channels[channel] = connected
            if self.data:
                self.async_update_listeners()

    async def async_evaluate_quake(self, quake: Earthquake) -> bool:
        """补齐距离/烈度/波到达并按阈值判定；命中且未播报过则发事件。"""
        quake.distance_km = haversine_km(
            self.latitude, self.longitude, quake.latitude, quake.longitude
        )
        quake.estimated_intensity = estimate_intensity(
            quake.magnitude, quake.distance_km
        )
        compute_wave_arrivals(quake, self.latitude, self.longitude)
        if quake.magnitude < self.min_magnitude or quake.distance_km > self.radius_km:
            return False
        if quake.event_id in self._fired_ids:
            return False
        self._fired_ids.add(quake.event_id)
        # 首次刷新即会对列表中已有的合格地震各播报一次（便于配置后立即验证），
        # 后续仅播报新出现的地震；WebSocket 预警帧按事件 ID 去重。
        self.hass.bus.async_fire(EVENT_EARTHQUAKE, quake.event_data())
        _LOGGER.info(
            "地震告警: M%s %s 距离 %.0f 公里 (%s)",
            quake.magnitude,
            quake.place,
            quake.distance_km,
            quake.source,
        )
        return True

    async def _async_update_data(self) -> EarthquakeUpdate:
        session = async_get_clientsession(self.hass)
        try:
            quakes = await async_fetch_earthquakes(session)
        except (ConnectionError, ValueError) as err:
            raise UpdateFailed(str(err)) from err

        quakes.sort(key=lambda q: q.origin_time, reverse=True)
        for quake in quakes:
            await self.async_evaluate_quake(quake)

        if len(self._fired_ids) > FIRED_IDS_MAX:
            self._fired_ids.clear()
        return EarthquakeUpdate(quakes=quakes, fetched_at=datetime.now(timezone.utc))
