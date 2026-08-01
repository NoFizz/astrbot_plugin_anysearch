<h1 align="center">AnySearch 智能搜索/astrbot_plugin_anysearch</h1>

<p align="center">
  <img src="logo.png" width="128" height="128" alt="astrbot_plugin_anysearch logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue?style=flat" alt="version">
  <img src="https://img.shields.io/badge/license-AGPL--3.0-green?style=flat" alt="license">
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat" alt="python">
  <img src="https://img.shields.io/badge/AstrBot->=4.26.0-orange?style=flat" alt="AstrBot version">
</p>

基于 AnySearch API v3 的 AstrBot 搜索插件，配置 API 地址后 LLM 自动获得联网搜索能力，支持 42 种垂直能力标签精准搜索。

<p align="center">
  <img src="https://count.getloli.com/@astrbot_plugin_anysearch?theme=moebooru" alt="Moe Counter">
</p>

## 功能特性

- **通用搜索**：支持任意关键词的网页搜索，API 自动路由到最佳数据源
- **垂直能力标签搜索**：42 种 tag 覆盖金融、学术、代码、法律、安全、医疗、商业、旅游等领域
- **自动触发**：LLM 根据用户问题自动判断是否需要搜索及使用哪个工具
- **智能重试**：网络错误、服务器 5xx、429 限流自动重试（指数退避 + 随机抖动 + Retry-After 感知）
- **结果缓存**：LRU + TTL 内存缓存，相同查询不重复调用 API
- **请求指标**：统计请求量、成功率、缓存命中率、平均延迟，插件卸载时输出汇总
- **连接池管理**：复用 HTTP Session，限制并发连接数，防止耗尽端口
- **输入校验**：关键词最长 500 字符，URL 最长 2048 字符，仅允许 http/https 协议

## 安装

### 方法一：通过插件市场安装（推荐）

1. 打开 AstrBot WebUI → 插件管理 → 插件市场。
2. 添加插件源（如尚未添加）：
   - 源名称：`AstrBot Official Plugin Market`
   - 源地址：`https://cloud-test.astrbot.app/api/v1/market/plugins.json`
3. 在插件市场中搜索 **AnySearch 智能搜索**（`astrbot_plugin_anysearch`），点击安装。
4. 等待安装完成，确认插件已启用。

### 方法二：从 GitHub 安装

1. 打开 AstrBot WebUI → 插件管理 → 新增插件。
2. 选择 **从 GitHub 安装**。
3. 填入仓库地址：
   ```
   https://github.com/NoFizz/astrbot_plugin_anysearch
   ```
4. 等待安装完成，确认插件已启用。

### 方法三：手动安装

1. 将本仓库克隆或下载到 AstrBot 的插件目录：
   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/NoFizz/astrbot_plugin_anysearch.git
   ```
2. 安装依赖：
   ```bash
   pip install -r astrbot_plugin_anysearch/requirements.txt
   ```
3. 在 AstrBot WebUI 中重载插件，或重启 AstrBot。

### 安装后检查

- 确认 `requirements.txt` 中的依赖已正确安装。
- 在 WebUI 插件管理中确认插件状态为"已启用"且无报错。
- 在插件设置中填写 API 配置后即可使用。

## 配置说明

在 AstrBot WebUI 插件管理中点击本插件进行配置。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `api_base` | string | `https://api.anysearch.com` | AnySearch API 地址 |
| `api_key` | string | 空 | API Key（可选），在 anysearch.com 控制台获取 |
| `max_results` | int | `10` | 最大返回结果数（1-20，用户自定义） |
| `format` | string | `json` | 输出格式：`json` 或 `markdown` |
| `zone` | string | `cn` | 搜索区域：`cn`（中国）或 `intl`（国际） |
| `language` | string | `zh-CN` | 语言偏好 |
| `timeout` | int | `15` | 请求超时时间（秒），最小值 3 |
| `cache_ttl` | int | `300` | 搜索结果缓存时间（秒），0 表示禁用缓存 |
| `extract_max_length` | int | `8000` | 网页正文提取最大字符数（预留，待专业版启用） |

### 获取 API Key

1. 访问 [AnySearch 官网](https://www.anysearch.com) 注册账号
2. 进入 [API Key 管理页面](https://anysearch.com/console/api-keys) 创建 API Key
3. 免费额度：每日 1000 次调用、20 QPS，无需付费即可使用

> 未配置 API Key 时以匿名模式运行，有较低的速率限制。

## 使用示例

本插件注册了 3 个 LLM 工具，由 LLM 根据用户问题自动调用，用户无需手动触发。

| 工具名 | 说明 | 触发场景 |
|--------|------|----------|
| `anysearch_web_search` | 通用网页搜索 | "今天有什么新闻？"、"搜索 Python 文档" |
| `anysearch_advanced_search` | 垂直能力标签搜索（42 种 tag） | "帮我查苹果公司财报"、"搜索 CVE-2024-1234 漏洞详情" |
| `anysearch_extract` | 网页正文提取（当前不可用） | 待 AnySearch 官方发布专业版后启用 |

### 垂直能力标签（42 种）

使用 `anysearch_advanced_search` 时，通过 `tag` 参数指定能力标签（格式：`类别.子类别`）：

| 类别 | 可用标签 |
|------|----------|
| **code** | `code.doc`（开发文档）、`code.snippet`（代码片段） |
| **finance** | `finance.quote`（行情）、`finance.news`（新闻）、`finance.fundamental`（财报）、`finance.macro`（宏观）、`finance.calendar`（日历）、`finance.screen`（筛选） |
| **academic** | `academic.search`（论文）、`academic.preprint`（预印本）、`academic.biomedical`（生物医学）、`academic.citation`（引用）、`academic.dataset`（数据集） |
| **legal** | `legal.case`（判决书）、`legal.statute`（法规）、`legal.legislation`（立法） |
| **security** | `security.vuln`（漏洞）、`security.intel`（情报）、`security.scan`（扫描）、`security.noise`（噪音判断） |
| **health** | `health.drug`（药品）、`health.trial`（临床试验）、`health.stats`（卫生统计） |
| **business** | `business.company`（企业）、`business.jobs`（招聘）、`business.people`（联系人）、`business.trade`（贸易） |
| **travel** | `travel.flight`（机票）、`travel.flight_status`（航班动态） |
| **其他** | `social_media.social_media`、`gaming.esports`、`gaming.store`、`energy.electricity`、`energy.production`、`environment.aqi`、`agriculture.fao`、`ip.global`、`resource.image`、`film.torrent`、`general.general` |

部分标签需要搭配 `params` 参数（JSON 格式），例如：
- `code.doc` + `{"library": "react"}`
- `finance.quote` + `{"symbol": "AAPL", "type": "stock"}`
- `security.vuln` + `{"type": "cve", "value": "CVE-2024-1234"}`

## 依赖要求

- Python >= 3.12
- AstrBot >= 4.26.0
- aiohttp >= 3.0.0

## 故障排查

### 搜索无结果

1. 检查 `api_base` 配置是否正确
2. 如果未配置 API Key，匿名模式有较低的速率限制，可能被限流
3. 尝试切换 `zone` 配置（`cn` / `intl`）
4. 检查网络连接是否正常

### 网页提取为什么不可用？

AnySearch 官方当前仅提供免费版，不支持 `/v1/extract` 端点。待官方发布专业版后，插件将自动启用该功能。

### 缓存如何工作？

相同查询在 `cache_ttl`（默认 300 秒）内会直接返回缓存结果，不重复调用 API。设置 `cache_ttl` 为 0 可禁用缓存。

### 重试机制如何工作？

遇到网络错误、服务器 5xx 错误或 429 限流时，插件会自动重试最多 2 次，使用指数退避加随机抖动。429 响应会解析 `Retry-After` 头作为最小等待时间。401（认证失败）和 402（配额耗尽）不会重试。

## 许可证

本项目基于 [AGPL-3.0](LICENSE) 许可证开源。

## 作者

**NoFizz** · [GitHub](https://github.com/NoFizz)

如遇问题或有功能建议，欢迎提交 [Issue](https://github.com/NoFizz/astrbot_plugin_anysearch/issues)。
