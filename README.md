# AnySearch 智能搜索

基于 AnySearch API v3 的 AstrBot 搜索插件，配置 API 地址后 LLM 自动获得联网搜索能力，支持 42 种垂直能力标签精准搜索。

## 功能

- **通用搜索**：支持任意关键词的网页搜索，API 自动路由到最佳数据源
- **垂直能力标签搜索**：42 种 tag 覆盖金融、学术、代码、法律、安全、医疗、商业、旅游等领域
- **自动触发**：LLM 根据用户问题自动判断是否需要搜索及使用哪个工具
- **智能重试**：网络错误、服务器 5xx、429 限流自动重试（指数退避 + 随机抖动 + Retry-After 感知）
- **结果缓存**：LRU + TTL 内存缓存，相同查询不重复调用 API
- **请求指标**：统计请求量、成功率、缓存命中率、平均延迟，插件卸载时输出汇总
- **连接池管理**：复用 HTTP Session，限制并发连接数，防止耗尽端口
- **输入校验**：关键词最长 500 字符，URL 最长 2048 字符，仅允许 http/https 协议

## 注册与获取 API Key

1. 访问 [AnySearch 官网](https://www.anysearch.com) 注册账号
2. 进入 [API Key 管理页面](https://anysearch.com/console/api-keys) 创建 API Key
3. 免费额度：每日 1000 次调用、20 QPS，无需付费即可使用

## 安装

### 通过 AstrBot 插件市场

在 WebUI 插件市场搜索"AnySearch"直接安装。

### 手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/NoFizz/astrbot_plugin_anysearch.git
```

然后在 WebUI 插件管理页面刷新并启用即可。

## LLM 工具

插件注册了 3 个 LLM 工具，LLM 会根据用户问题自动选择合适的工具：

| 工具名 | 说明 | 触发场景 |
|--------|------|----------|
| `anysearch_web_search` | 通用网页搜索 | "今天有什么新闻？"、"搜索 Python 文档" |
| `anysearch_advanced_search` | 垂直能力标签搜索（42 种 tag） | "帮我查苹果公司财报"、"搜索 CVE-2024-1234 漏洞详情" |
| `anysearch_extract` | 网页正文提取（当前不可用） | 待 AnySearch 官方发布专业版后启用 |

## 垂直能力标签（42 种）

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

## 插件配置

在 AstrBot WebUI 中配置以下参数：

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

## 常见问题

### API Key 在哪获取？

访问 https://www.anysearch.com 注册账号，然后在 https://anysearch.com/console/api-keys 创建 API Key。免费额度为每日 1000 次调用。

### 搜索无结果怎么办？

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

## 版本

**当前版本**：v1.0.0

## 作者

NoFizz

## 许可证

AGPL-3.0
