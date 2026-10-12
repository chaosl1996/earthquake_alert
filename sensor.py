"""Sensors for the China Earthquake Alert integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import EarthquakeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up earthquake sensors from a config entry."""
    coordinator: EarthquakeCoordinator = hass.data[DOMAIN][entry.entry_id]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data["name"],
        manufacturer=MANUFACTURER,
        model="中国地震台网速报",
        entry_type=DeviceEntryType.SERVICE,
    )

    async_add_entities(
        [
            LatestEarthquakeSensor(coordinator, entry, device_info),
            WaveCountdownSensor(coordinator, entry, device_info),
        ]
    )


class LatestEarthquakeSensor(CoordinatorEntity[EarthquakeCoordinator], SensorEntity):
    """最新一条地震速报，状态为震级。"""

    _attr_has_entity_name = True
    _attr_translation_key = "latest_earthquake"
    _attr_icon = "mdi:waves"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: EarthquakeCoordinator,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry.entry_id}-latest"

    @property
    def native_value(self) -> float | None:
        """最新地震的震级。"""
        latest = self.coordinator.latest
        return latest.magnitude if latest else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """最新地震的详情（含距本机距离与估算烈度）。"""
        return self.coordinator.quake_attributes(self.coordinator.latest)


class WaveCountdownSensor(CoordinatorEntity[EarthquakeCoordinator], SensorEntity):
    """最新地震的 S 波（主震感）到达倒计时，单位秒，已到达或无数据为 0。

    注意：数值仅在协调器刷新时更新（默认 5 分钟），自动化请优先使用
    事件数据中的 arrival_time 时间戳做精确判断。
    """

    _attr_has_entity_name = True
    _attr_translation_key = "wave_countdown"
    _attr_icon = "mdi:timer-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "秒"

    def __init__(
        self,
        coordinator: EarthquakeCoordinator,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry.entry_id}-wave-countdown"

    @property
    def native_value(self) -> int:
        """S 波剩余秒数，向下截断为 0。"""
        latest = self.coordinator.latest
        if latest is None:
            return 0
        return max(0, latest.wave_eta_seconds() or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """倒计时对应的地震详情（含预计波到达时刻与震感预估）。"""
        return self.coordinator.quake_attributes(self.coordinator.latest)
