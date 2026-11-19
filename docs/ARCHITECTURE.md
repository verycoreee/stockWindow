# StockWindow 架构设计与扩展指南

本项目刻意避免将网络请求、Win32 任务栏适配、配置持久化与 UI 控件耦合在同一文件中，采用严格的 **五层单向依赖结构**，确保后续加功能（例如新增数据源、增加价格预警、切换显示模板、接入插件）时不必推翻旧代码。

---

## 1. 分层总览

```text
src/stock_window/
├── models/      # 纯数据结构（StockItem / StockQuote / SearchResult / AppConfig）
├── config/      # JSON 原子持久化 + 缺省值合并（与 UI 解耦）
├── providers/   # 【扩展点 1】行情与搜索数据源抽象及注册中心
├── services/    # 【扩展点 2】轮询调度服务 + 显示格式化/配色策略
├── platform/    # 【扩展点 3】Windows 任务栏贴靠、全屏隐藏、全局热键（隔离 Win32 API）
├── ui/          # PySide6 视图层（只消费 Service 与 Model，不直接发 HTTP 请求）
├── app.py       # Composition Root：统一装配各层对象，绑定信号与槽
└── main.py      # 程序入口（单实例锁、日志、启动事件循环）
```

### 依赖规则（核心约束）

| 层级 | 允许依赖 | 禁止依赖 |
|---|---|---|
| `models` | Python 标准库 | 其余所有层 |
| `config` | `models` | `providers` / `services` / `platform` / `ui` |
| `providers` | `models`, `requests` | `services` / `platform` / `ui` |
| `services` | `models`, `providers` | `platform` / `ui` |
| `platform` | `ctypes` / Win32 API | `providers` / `services` / `ui` |
| `ui` | `models`, `services`, `platform`, `PySide6` | 直接发 HTTP 请求、直接解析行情原始报文 |

> `app.py` 是唯一允许同时看见全部层级的“装配器”。以后新增模块时，只在 `app.py` 里接线即可。

---

## 2. 三大预留扩展点

### 扩展点 1：新增行情 / 搜索数据源（`providers/`）

所有数据源必须继承 `providers/base.py` 中的 `QuoteProvider` 或 `SearchProvider`，并向 `ProviderRegistry` 注册。

例如后续要接入 **东方财富**、**新浪**、**通达信直连** 或 **黄金/加密货币接口**：
1. 新建 `src/stock_window/providers/eastmoney.py`，实现 `fetch_quotes(symbols)` 和/或 `search(keyword)`；
2. 在 `providers/registry.py` 的 `create_default_registry()` 中注册该 Provider 名称；
3. 在 `data/config.json` 将 `polling.provider` 改为新名称即可切换，**无需修改 `services` 和 `ui` 任何代码**。

### 扩展点 2：新增显示样式与告警策略（`services/formatter.py`）

`DisplayFormatter` 负责把 `(StockItem, StockQuote | None, AppearanceConfig)` 转成渲染友好的 `FormattedStockView`（纯文本 + 颜色十六进制值 + 悬停详情 Tooltip）。

后续如果要扩展：
- 涨跌幅超过阈值时才轻微变色（“只在异常波动时提醒，平时纯灰”）
- 支持自定义显示模板（如 `{alias} {pct}`、`{name} {price}`）
- 支持本地成本价盈亏计算

只需扩展 `DisplayFormatter` 和 `AppearanceConfig` 字段，`TaskbarBar` 控件只负责按 `FormattedStockView` 绘制。

### 扩展点 3：操作系统适配（`platform/`）

所有 `ctypes` / `user32` 调用（任务栏坐标计算、无焦点置顶、`WS_EX_TOOLWINDOW`、全屏应用检测、全局老板键 `RegisterHotKey`）都隔离在 `platform/win32_taskbar.py`，通过 `TaskbarPlatformAdapter` 抽象接口对外提供服务。后续升级 Win11 版本补丁或做更细致的托盘对齐时，只需改这一个文件。

---

## 3. 配置与隐私边界

- 运行期配置默认写入项目根目录下的 `data/config.json`（已被 `.gitignore` 忽略）。
- 仓库内不保存任何个人自选股列表；首次启动若无配置文件，仅生成 1 条公开指数示例（`sh000001 上证指数`）。
- 写入配置采用“写临时文件 → 原子替换”策略，避免异常退出导致配置文件损坏。
