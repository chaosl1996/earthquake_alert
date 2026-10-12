"""Binary sensor for the China Earthquake Alert integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    """Set up the earthquake alert binary sensor."""
    coordinator: EarthquakeCoordinator = hass.data[DOMAIN][entry.entry_id]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data["name"],
        manufacturer=MANUFACTURER,
        model="中国地震台网速报",
        entry_type=DeviceEntryType.SERVICE,
    )

    async_add_entities([EarthquakeAlertBinarySensor(coordinator, entry, device_info)])


class EarthquakeAlertBinarySensor(
    CoordinatorEntity[EarthquakeCoordinator], BinarySensorEntity
):
    """告警状态：阈值命中的地震在告警持续期内为 on。"""

    _attr_has_entity_name = True
    _attr_translation_key = "alert"
    _attr_icon = "mdi:bell-alert"

    def __init__(
        self,
        coordinator: EarthquakeCoordinator,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry.entry_id}-alert"

    @property
    def is_on(self) -> bool:
        """最新一条合格地震仍在告警持续期内为 on。"""
        return self.coordinator.alerting is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """触发当前告警的地震详情。"""
        return self.coordinator.quake_attributes(self.coordinator.alerting)
