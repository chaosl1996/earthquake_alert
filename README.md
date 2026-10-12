# China Earthquake Alert（中国地震预警）

[![GitHub Release](https://img.shields.io/github/v/release/chaosl1996/earthquake_alert)](https://github.com/chaosl1996/earthquake_alert/releases)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/license-MIT-green)](#许可证)

一个 Home Assistant 自定义集成：接入中国地震台网速报与地震预警网实时通道，按你设定的目标位置计算震中距离、估算烈度与地震波到达时间，命中阈值时通过事件触发通知。

![logo](brand/logo.png)

---

## 功能特性

- **双数据通道**
  - **实时预警通道（WebSocket）**：接入重庆/四川地震局、中国地震预警网等紧急地震速报（EEW），震后数秒推送，近震也有波前倒计时价值。
  - **速报轮询（HTTP）**：中国地震台网速报镜像，失败自动降级到 USGS，作为兜底。
- **位置感知**：以任意目标坐标（默认跟随 HA 家庭位置）为基准，用 Haversine 公式计算震中距，支持多实例覆盖家、老家、公司等多个地点。
- **烈度与震感估算**：按震级与距离估算烈度，并给出通俗震感描述。
- **P/S 波到达与倒计时**：估算 P 波、S 波到达时刻，提供 S 波（主震感）剩余秒数倒计时。
- **事件驱动**：命中「最小震级 + 告警半径」阈值时发出 `earthquake_alert` 事件，自动化里即可自由推送。

> ⚠️ **关于"实时"的诚实说明**：EEW 通道是震后**数秒**级别的仪器自动发布，对近震而言预警时间窗极短（S 波每秒约 3.5 km，30 km 外仅约 9 秒）。本集成适合做"叫醒、联动、速报归档"，**不能替代官方地震预警 App 的逃生功能**。

---

## 安装

### 方式一：HACS（推荐）

1. HACS → 右上角 ⋮ → **Custom repositories**
2. 添加仓库 `https://github.com/chaosl1996/earthquake_alert`，类别选 **Integration**
3. 搜索 **China Earthquake Alert** → 下载
4. 重启 Home Assistant

### 方式二：手动安装

```bash
cd /path/to/homeassistant/config
git clone https://github.com/chaosl1996/earthquake_alert.git \
  custom_components/earthquake_alert
```

重启 Home Assistant。

---

## 配置

**设置 → 设备与服务 → 添加集成 → 搜索"地震"**

| 配置项 | 说明 | 默认 |
|---|---|---|
| 预警目标位置 | 地图选点，距离与告警均按此坐标计算，默认带入 HA 家庭位置 | 家庭位置 |
| 名称 | 集成实例名称，留空为"地震预警" | — |

### 选项（集成页面 → 配置）

| 选项 | 说明 | 默认 |
|---|---|---|
| 数据刷新间隔 | 轮询速报的间隔（分钟） | 5 |
| 告警半径 | 超过此距离的地震不告警（公里） | 300 |
| 最小告警震级 | 低于此震级的地震不告警 | 4.0 |
| 实时预警通道 | WebSocket 秒级推送通道（可多选） | 重庆地震局预警 |

可选实时预警通道：

| 通道 | 数据来源 |
|---|---|
| `cq_eew` | 重庆市地震局预警 |
| `sc_eew` | 四川省地震局预警 |
| `cenc_eew` | 中国地震预警网 |
| `cenc_eqlist` | 中国地震台网速报推送 |

> 添加多个集成实例可覆盖多个目标地址（如家、老家），各自独立计算与告警。

---

## 实体

| 实体 | 类型 | 说明 |
|---|---|---|
| `sensor.*_latest_earthquake` | 传感器 | 最新一条地震，状态为震级，属性含震中/距离/烈度/波到达等 |
| `sensor.*_wave_countdown` | 传感器 | S 波（主震感）到达剩余秒数，已到达为 0 |
| `binary_sensor.*_alert` | 二进制传感器 | 阈值命中且在持续期内为"开启"（默认持续 15 分钟） |

### 「最新地震」主要属性

| 属性 | 示例 |
|---|---|
| 震中 | 四川宜宾市高县 |
| 震级 / 深度（公里） | 4.4 / 10 |
| 发震时刻 | 2026-10-12 23:55:00 |
| 距本机距离（公里） | 218.3 |
| 估算烈度 / 官方烈度 | 3.5 / — |
| 震感预估 | 明显震感，门窗作响、悬挂物晃动 |
| 预计P波到达 / 预计S波到达 | 2026-10-12 23:55:36 / 23:56:02 |
| S波倒计时（秒） | 272 |
| 数据来源 | 重庆地震局预警 |
| 实时预警通道 | cq_eew 已连接 |
| 数据更新时间 | 2026-10-12 23:56:10 |

---

## 事件与自动化

集成在命中阈值时发出 `earthquake_alert` 事件。

### 事件数据

| 字段 | 说明 |
|---|---|
| `event_id` | 事件唯一 ID |
| `magnitude` / `depth_km` | 震级 / 深度 |
| `place` | 震中地点 |
| `latitude` / `longitude` | 震中坐标 |
| `origin_time` | 发震时刻（北京时间 ISO） |
| `distance_km` | 距目标位置距离 |
| `estimated_intensity` / `intensity` | 估算烈度 / 官方烈度 |
| `felt` | 震感文字描述 |
| `eta_seconds` | S 波剩余秒数（可为负） |
| `p_wave_eta_seconds` | P 波剩余秒数 |
| `arrival_time` | S 波到达时刻（北京时间 ISO） |
| `source` | 数据来源 |

### 示例：推送通知

```yaml
automation:
  - alias: 地震预警通知
    triggers:
      - trigger: event
        event_type: earthquake_alert
    actions:
      - action: notify.mobile_app_xxx
        data:
          title: "地震预警 M{{ trigger.event.data.magnitude }}"
          message: >-
            {{ trigger.event.data.place }}，距你
            {{ trigger.event.data.distance_km }} 公里，S 波
            {{ trigger.event.data.eta_seconds }} 秒后到达，震感：{{
            trigger.event.data.felt }}（估算烈度 {{
            trigger.event.data.estimated_intensity }}）
```

### 示例：强震联动（开灯 + 语音播报）

```yaml
automation:
  - alias: 强震联动
    triggers:
      - trigger: event
        event_type: earthquake_alert
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.estimated_intensity >= 4 }}"
    actions:
      - action: light.turn_on
        target:
          entity_id: all
      - action: tts.speak
        target:
          entity_id: tts.piper
        data:
          message: >
            地震预警，{{ trigger.event.data.place }}发生
            {{ trigger.event.data.magnitude }}级地震，
            预计{{ trigger.event.data.eta_seconds }}秒后到达。
```

---

## 调试与验证

1. **开发者工具 → 事件 → 监听** `earthquake_alert`
2. **集成 → 配置**，临时改为：间隔 `1` 分钟、半径 `2000` 公里、震级 `1.0`
3. 保存后首个刷新周期即会对当前合格地震发事件 —— 说明整条链路通了
4. 验证完改回常规阈值（5 分钟 / 300 公里 / 4.0）

> 日常默认阈值下触发频率很低（一年几次），长期安静是正常现象。

---

## 数据源与实时性

| 层级 | 延迟 | 来源 | 是否公开 |
|---|---|---|---|
| 手机预警（秒级波形流） | 秒级 | ICL / CENC 专用台网 | ❌ 需授权 |
| **EEW 紧急地震速报** | **震后数秒** | 川渝地震局 / 中国预警网 | ✅ 本集成使用 |
| 自动速报 | 震后 1~2 分钟 | 中国地震台网 | ✅ 本集成使用 |
| 正式速报 | 震后 3~5 分钟 | 中国地震台网（人工审核） | ✅ 本集成使用 |

- 主源：`api.wolfx.jp/cenc_eqlist.json`（中国地震台网速报镜像，免费无 key）
- 降级源：USGS `earthquake.usgs.gov` GeoJSON
- 实时通道：`wss://ws-api.wolfx.jp/*`（WebSocket，断线指数退避自动重连）

> 公开 API 拿不到波前秒级数据；本集成做到了公开渠道的实时上限。

---

## 免责声明

本集成数据来自第三方公开接口，仅供参考，**不构成任何形式的安全保障**。地震预警请以中国地震局及各地震局官方发布为准，并遵循当地应急部门的避险指引。

---

## 许可证

MIT
