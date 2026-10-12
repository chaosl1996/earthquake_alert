"""Constants for the China Earthquake Alert integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "earthquake_alert"

MANUFACTURER = "中国地震台网"

# 主源：中国地震台网速报镜像（免费、无 key）。
# 注：官方 news.ceic.ac.cn 接口被 WAF 拦截且证书过期，故采用社区镜像。
CENC_URL = "https://api.wolfx.jp/cenc_eqlist.json"
# 降级源：USGS 全球地震 GeoJSON（域名是 earthquake 单数）。
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"

SOURCE_CENC = "中国地震台网"
SOURCE_USGS = "USGS"

# WebSocket 实时预警通道（wolfx ws-api）：EEW 为预警网震后秒级自动发布，
# 与 1~5 分钟的速报相比对近震才有波前倒计时价值。已实测 101 握手成功。
WS_BASE = "wss://ws-api.wolfx.jp"
CONF_WS_CHANNELS = "ws_channels"
DEFAULT_WS_CHANNELS = ["cq_eew"]
WS_CHANNEL_LABELS = {
    "cq_eew": "重庆市地震局预警",
    "sc_eew": "四川省地震局预警",
    "cenc_eew": "中国地震预警网",
    "cenc_eqlist": "中国地震台网速报推送",
}
# EEW 通道到数据来源文案的映射
WS_CHANNEL_SOURCES = {
    "cq_eew": "重庆地震局预警",
    "sc_eew": "四川地震局预警",
    "cenc_eew": "中国地震预警网",
    "cenc_eqlist": "中国地震台网",
}
WS_PING_INTERVAL = 30
WS_RECONNECT_MAX_DELAY = 300  # 断线重连退避上限（秒）

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30

# options 配置项
CONF_SCAN_INTERVAL = "scan_interval"  # 单位：分钟
CONF_RADIUS_KM = "radius_km"
CONF_MIN_MAGNITUDE = "min_magnitude"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)
DEFAULT_RADIUS_KM = 300
DEFAULT_MIN_MAGNITUDE = 4.0

# HA 家庭位置未设置时的兜底坐标（北京）
DEFAULT_LATITUDE = 39.9042
DEFAULT_LONGITUDE = 116.4074

# 满足阈值的新地震触发的事件类型（自动化里用 event 平台监听）
EVENT_EARTHQUAKE = "earthquake_alert"
# 告警二进制传感器保持 on 的时长
ALERT_DURATION = timedelta(minutes=15)
# 已播报事件 ID 的内存上限，防止长期运行时无限增长
FIRED_IDS_MAX = 200
