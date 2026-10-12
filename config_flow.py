"""Config flow to set up the China Earthquake Alert integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_MIN_MAGNITUDE,
    CONF_RADIUS_KM,
    CONF_SCAN_INTERVAL,
    CONF_WS_CHANNELS,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_MIN_MAGNITUDE,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WS_CHANNELS,
    DOMAIN,
    WS_CHANNEL_LABELS,
)

INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=1,
        max=60,
        step=1,
        unit_of_measurement="分钟",
        mode=NumberSelectorMode.BOX,
    )
)
RADIUS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=10,
        max=2000,
        step=10,
        unit_of_measurement="公里",
        mode=NumberSelectorMode.BOX,
    )
)
MAGNITUDE_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=9, step=0.1, mode=NumberSelectorMode.BOX)
)


class EarthquakeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for China Earthquake Alert."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step: pick the alert target location."""
        errors: dict[str, str] = {}

        if user_input is not None:
            location = user_input["location"]
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
            await self.async_set_unique_id(f"{DOMAIN}-{latitude:.3f}-{longitude:.3f}")
            self._abort_if_unique_id_configured()
            name = (user_input.get("name") or "").strip() or "地震预警"
            return self.async_create_entry(
                title=name,
                data={"location": {"latitude": latitude, "longitude": longitude}, "name": name},
            )

        # 默认带入 HA 家庭位置（设置 → 系统 → 常规 → 位置）
        default_location = {
            "latitude": self.hass.config.latitude or DEFAULT_LATITUDE,
            "longitude": self.hass.config.longitude or DEFAULT_LONGITUDE,
        }
        schema = vol.Schema(
            {
                vol.Required("location", default=default_location): LocationSelector(
                    LocationSelectorConfig(radius=False)
                ),
                vol.Optional("name"): TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Create the options flow handler."""
        return EarthquakeOptionsFlow(config_entry)


class EarthquakeOptionsFlow(config_entries.OptionsFlow):
    """Handle options: polling interval / alert radius / min magnitude."""

    def __init__(self, config_entry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self._entry.options.get(
                        CONF_SCAN_INTERVAL,
                        int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60),
                    ),
                ): INTERVAL_SELECTOR,
                vol.Required(
                    CONF_RADIUS_KM,
                    default=self._entry.options.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
                ): RADIUS_SELECTOR,
                vol.Required(
                    CONF_MIN_MAGNITUDE,
                    default=self._entry.options.get(
                        CONF_MIN_MAGNITUDE, DEFAULT_MIN_MAGNITUDE
                    ),
                ): MAGNITUDE_SELECTOR,
                vol.Required(
                    CONF_WS_CHANNELS,
                    default=self._entry.options.get(
                        CONF_WS_CHANNELS, DEFAULT_WS_CHANNELS
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": value, "label": label}
                            for value, label in WS_CHANNEL_LABELS.items()
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
