"""The China Earthquake Alert integration.

轮询中国地震台网速报（wolfx 镜像，失败降级 USGS），按配置的位置计算震中距离
与估算烈度；命中“最小震级 + 告警半径”阈值时发出 earthquake_alert 事件供自动化
推送通知。自动化示例：

```yaml
automation:
  - triggers:
      - trigger: event
        event_type: earthquake_alert
    actions:
      - action: notify.mobile_app_xxx
        data:
          title: "地震速报 M{{ trigger.event.data.magnitude }}"
          message: >-
            {{ trigger.event.data.place }}，距你
            {{ trigger.event.data.distance_km }} 公里，S 波
            {{ trigger.event.data.eta_seconds }} 秒后到达，震感：{{
            trigger.event.data.felt }}（估算烈度 {{
            trigger.event.data.estimated_intensity }}）
```
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_WS_CHANNELS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WS_CHANNELS,
    DOMAIN,
    WS_CHANNEL_LABELS,
)
from .coordinator import EarthquakeCoordinator
from .websocket_client import WolfxWebSocketListener

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up China Earthquake Alert from a config entry."""
    interval_min = int(
        entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds() // 60
        )
    )
    location = entry.data["location"]
    coordinator = EarthquakeCoordinator(
        hass,
        latitude=location["latitude"],
        longitude=location["longitude"],
        options=entry.options,
        scan_interval=timedelta(minutes=interval_min),
    )
    # 首次刷新失败不阻塞加载：网络闪断时实体短暂显示未知，
    # 协调器按轮询间隔自动重试，避免集成进入报错-重试循环。
    await coordinator.async_refresh()

    # WebSocket 实时预警通道：默认仅重庆局预警（cq_eew），可在选项中增减
    channels = entry.options.get(CONF_WS_CHANNELS) or DEFAULT_WS_CHANNELS
    listeners = [
        WolfxWebSocketListener(hass, coordinator, channel)
        for channel in channels
        if channel in WS_CHANNEL_LABELS
    ]
    for listener in listeners:
        coordinator.register_ws_channel(listener.channel)
        listener.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    # 监听器单独存放，避免污染实体平台读取的协调器引用
    hass.data.setdefault(f"{DOMAIN}_ws", {})[entry.entry_id] = listeners
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
        for listener in hass.data.get(f"{DOMAIN}_ws", {}).pop(entry.entry_id, []):
            await listener.stop()
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
