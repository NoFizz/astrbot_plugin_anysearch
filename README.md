<h1 align="center">AnySearch 智能搜索/astrbot_plugin_anysearch_x</h1>

<p align="center">
  <img src="logo.png" width="128" height="128" alt="astrbot_plugin_anysearch_x logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.0.0-blue?style=flat" alt="version">
  <img src="https://img.shields.io/badge/license-AGPL--3.0-green?style=flat" alt="license">
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat" alt="python">
  <img src="https://img.shields.io/badge/AstrBot->=4.26.0-orange?style=flat" alt="AstrBot version">
</p>

基于 AnySearch API v3 的 AstrBot 搜索插件，配置 API 地址后 LLM 自动获得联网搜索能力，支持 40 种垂直能力标签精准搜索。

<p align="center">
  <img src="https://count.getloli.com/@astrbot_plugin_anysearch_x?theme=moebooru" alt="Moe Counter">
</p>

## 功能特性

- **通用搜索**：支持任意关键词的网页搜索，API 自动路由到最佳数据源
- **垂直能力标签搜索**：40 种 tag 覆盖金融、学术、代码、法律、安全、医疗、商业、旅游等领域
- **自动触发**：LLM 根据用户问题自动判断是否需要搜索及使用哪个工具
- **智能重试**：网络错误、服务器 5xx、429 限流自动重试（指数退避 + 随机抖动 + Retry-After 感知）
- **结果缓存**：LRU + TTL 内存缓存，相同查询不重复调用 API
- **请求指标**：统计请求量、成功率、缓存命中率、平均延迟，插件卸载时输出汇总
- **连接池管理**：复用 HTTP Session，限制并发连接数，防止耗尽端口
- **输入校验**：关键词最长 500 字符，URL 最长 2048 字符，仅允许 http/https 协议
- **模块化架构**：models / client / cache / main 分层组织，单向依赖，便于维护与测试
- **配额耗尽明确报错**：402 配额用尽时记录日志并返回友好提示，提示配置 API Key（不自动注册、不自动重试）
- **网页正文提取**：通过 MCP 协议提取网页正文（markdown），匿名可用，超出长度自动截断

## 插件架构

### 模块结构

插件按模块化架构组织，依赖方向为单向（箭头指向被依赖方）：

```
models ← client ← cache ← main
```

- `models.py`：异常层级、请求常量、40 个能力 tag 目录（17 类）
- `client.py`：AnySearchClient，请求构造、错误映射、重试与配额耗尽错误、MCP 网页提取
- `cache.py`：LRU + TTL 内存缓存
- `main.py`：插件类、LLM 工具注册、指标统计、生命周期

禁止反向 import（如 `client` 不得 import `main`）。

## 安装

### 方法一：通过插件市场安装（推荐）

1. 打开 AstrBot WebUI → 插件管理 → 插件市场。
2. 添加插件源（如尚未添加）：
   - 源名称：`AstrBot Official Plugin Market`
   - 源地址：`https://cloud-test.astrbot.app/api/v1/market/plugins.json`
3. 在插件市场中搜索 **AnySearch 智能搜索**（`astrbot_plugin_anysearch_x`），点击安装。
4. 等待安装完成，确认插件已启用。

### 方法二：从 GitHub 安装

1. 打开 AstrBot WebUI → 插件管理 → 新增插件。
2. 选择 **从 GitHub 安装**。
3. 填入仓库地址：
   ```
   https://github.com/NoFizz/astrbot_plugin_anysearch_x
   ```
4. 等待安装完成，确认插件已启用。

### 方法三：手动安装

1. 将本仓库克隆或下载到 AstrBot 的插件目录：
   ```bash
   cd AstrBot/data/plugins
   git clone https://github.com/NoFizz/astrbot_plugin_anysearch_x.git
   ```
2. 安装依赖：
   ```bash
   pip install -r astrbot_plugin_anysearch_x/requirements.txt
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
| `extract_max_length` | int | `8000` | 网页正文提取最大返回字符数（MCP 提取，超出截断） |

### 获取 API Key

1. 访问 [AnySearch 官网](https://www.anysearch.com) 注册账号
2. 进入 [API Key 管理页面](https://anysearch.com/console/api-keys) 创建 API Key
3. 免费额度：每日 1000 次调用、20 QPS，无需付费即可使用

> 未配置 API Key 时以匿名模式运行，按 IP 限流（约每分钟 10 次请求）。
> 匿名或 Key 额度用尽（HTTP 402）时，插件记录错误日志并返回提示，请配置 `api_key` 以获得完整免费额度（每日 1000 次、20 QPS）。

## 使用示例

本插件注册了 3 个 LLM 工具，由 LLM 根据用户问题自动调用，用户无需手动触发。

| 工具名 | 说明 | 触发场景 |
|--------|------|----------|
| `anysearch_web_search` | 通用网页搜索 | "今天有什么新闻？"、"搜索 Python 文档" |
| `anysearch_advanced_search` | 垂直领域精准搜索（LLM 根据查询自动判断领域，可省略 tag 走自动路由） | "帮我查苹果公司财报"、"搜索 CVE-2024-1234 漏洞详情" |
| `anysearch_extract` | 网页正文提取（MCP，匿名可用） | 需要网页完整正文时 |

### 垂直能力标签（40 种）

`anysearch_advanced_search` 的 `tag` 参数为可选（格式：`类别.子类别`），由 LLM 根据查询内容自动判断领域后填写；**判断不了时省略 tag，即按普通搜索自动路由，搜索照常进行**。传入无效/不相关的 tag 时插件会忽略它并按普通搜索处理（不会报错阻塞）。以下目录供参考：

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

## 插件逻辑详解

本章介绍插件内部的工作逻辑：LLM 工具如何注册与调用、搜索请求如何执行、tag 如何自动路由与降级、错误如何重试与提示、网页正文如何提取，以及缓存与指标的工作方式。内容基于 v2.0.0 源码（main.py / client.py / models.py / cache.py），可作为二次开发与排障的参考。

### 1. 工具注册与 LLM 调用流程

插件在 `__init__` 中通过 `context.add_llm_tools(*self._build_tools())` 一次性注册 3 个 LLM 工具。每个工具都是 `astrbot.api.FunctionTool` 数据类实例，由 name、description、parameters（JSON Schema）、handler 四个字段构成，不使用装饰器式工具注解：

| 工具名 | 对应方法 | 说明 |
|--------|----------|------|
| `anysearch_web_search` | `AnySearchPlugin._web_search` | 通用网页搜索，API 自动路由到最佳数据源 |
| `anysearch_advanced_search` | `AnySearchPlugin._advanced_search` | 垂直领域精准搜索（tag + params） |
| `anysearch_extract` | `AnySearchPlugin._extract_tool` | 网页正文提取（MCP，匿名可用） |

注册示意（省略 parameters 细节）：

```python
context.add_llm_tools(
    FunctionTool(
        name="anysearch_web_search",
        description="搜索网页并返回相关结果。...",
        parameters={"type": "object", "properties": {...}, "required": ["query"]},
        handler=AnySearchPlugin._web_search,  # 未绑定类方法
    ),
    # 另有 anysearch_advanced_search、anysearch_extract 两个工具
)
```

是否搜索、调用哪个工具、传什么参数，全部由 LLM 在对话中自主决定。插件只负责把工具清单提供给模型，用户无需手动触发。工具的调用契约是 `handler(event, **kwargs)`：event 由框架位置传入，工具参数以关键字传入，handler 直接返回字符串给 LLM。

handler 的注册方式有一个容易踩坑的细节：`_build_tools()` 中传入的是**未绑定类方法**（如 `AnySearchPlugin._web_search`），而不是绑定方法 `self._web_search`。原因是 AstrBot 加载插件时，会用 `functools.partial` 把插件实例绑定到 handler 上（`astrbot/core/star/star_manager.py:1295`）。若传入绑定方法，partial 会把插件实例再次作为第一个参数绑定，调用时参数错位，直接抛出 TypeError。

工具参数 schema 的编写同时适配了 AstrBot 的两种工具调用模式：

- **full 模式**：一次性下发完整参数 schema，LLM 直接填好全部参数后调用工具。
- **skills_like 模式**：两阶段调用。阶段 1 只发送工具名与描述，让 LLM 先选择工具；阶段 2 只发送选中工具的参数 schema，让 LLM 补全参数（`tool_loop_agent_runner.py` 中的 re-query 逻辑）。

因此所有参数的 description 都自带「（必填）/（可选）」标注，`anysearch_advanced_search` 的 tag 描述内嵌完整 40 个 tag 目录与必填参数标注，保证无论哪种模式下，LLM 都能独立且正确地调用。

### 2. 搜索执行流程

`anysearch_web_search` 与 `anysearch_advanced_search` 共用核心方法 `_run_search()`，差异只在前者不携带 tag/params。整体时序：

```
用户提问 → LLM 选择工具并给出参数
        → handler 入参校验（空 query / 超过 500 字符）
        → 查缓存（命中直接返回，记缓存命中）
        → 信号量（并发 ≤ 3）→ 惰性创建 / 复用 AnySearchClient
        → POST {api_base}/v1/search
        → 按 URL 去重并格式化为 json / markdown
        → 写入缓存 → 返回文本给 LLM → LLM 组织最终回答
```

逐步说明：

1. **输入校验**：query 为空时直接返回「请提供有效的搜索关键词。」；超过 500 字符（`MAX_QUERY_LEN`）返回「搜索失败：关键词过长。」。两种情况都不发请求。
2. **缓存查询**：以 query + tag + params + max_results + format 生成缓存键（见第 6 节）查缓存，命中直接返回缓存结果，并计入缓存命中指标。
3. **信号量限流**：`asyncio.Semaphore(3)` 把并发搜索限制为 3 个，避免突发请求压垮 API 或耗尽连接。
4. **惰性创建客户端**：首次请求时用双检锁创建 `AnySearchClient`，aiohttp session 在整个插件生命周期内复用，连接池 `limit=20`、`limit_per_host=5`、DNS 缓存 60 秒；插件关闭后拒绝创建新客户端。
5. **请求 API**：`POST {api_base}/v1/search`，请求体包含 query、max_results、zone、language、format 五个固定字段，`advanced_search` 还会按需携带 tag、params 两个可选字段；配置了 api_key 时附 `Authorization: Bearer` 头。

```json
{
  "query": "Python asyncio 教程",
  "max_results": 10,
  "zone": "cn",
  "language": "zh-CN",
  "format": "json"
}
```

6. **格式化结果**：按 URL 去重后，按配置输出 json 或 markdown 格式文本；结果为空时返回「未找到相关搜索结果。建议更换关键词或切换搜索区域。」
7. **写缓存**：仅成功结果写入缓存，失败不缓存。
8. **异常兜底**：任何异常都会计入失败指标并转换为用户友好的中文提示（分类见第 4 节），handler 永不抛异常。

延迟指标优先取 API 返回的 `metadata.search_time_ms`，缺失时用本地计时兜底。

### 3. tag 自动路由与降级设计

`anysearch_advanced_search` 的 tag 参数是**自由字符串**而非枚举，其描述内嵌完整 40 个 tag 目录（17 类，来自 `models.TAG_DIRECTORY`）与示例映射，由 LLM 根据查询内容自行判断领域后填写。设计上遵循「尽量不阻塞、可自纠」的原则：

- **省略 tag = 普通搜索**：tag 为空时不携带该字段，API 自动路由到最佳数据源，搜索照常进行。描述中明确告知 LLM：不要因为没传 tag 而担心搜索失败，也不要强行编造不相关的 tag。
- **必填参数标注**：16 个 tag 有必填 params，目录中以「(需 xxx)」标注，例如 `code.doc(需 library)`、`security.vuln(需 type,value)`、`travel.flight(需 departure,arrival,date)`。
- **handler 缺参校验**：所选 tag 位于必填表（`TAG_REQUIRED_PARAMS`）但缺少必填参数时，直接返回友好提示（附示例值），不发请求，避免 400 反复失败。
- **降级处理**：无效 tag 或非法 params 不会报错阻塞搜索。插件记 warning 日志、忽略该参数并按普通搜索处理，结果前加提示前缀（如 `[tag 'xxx' 无效，已按普通搜索处理]`），LLM 看到提示后可自行纠正。params 兼容 dict 与 JSON 字符串两种传法，解析失败或不是对象时同样降级。

部分 tag 与必填 params 示例：

| tag | 必填 params | 示例 |
|-----|-------------|------|
| `code.doc` | `library` | `{"library": "react"}` |
| `finance.quote` | `type` | `{"type": "stock", "symbol": "AAPL"}` |
| `security.vuln` | `type`、`value` | `{"type": "cve", "value": "CVE-2024-1234"}` |
| `travel.flight` | `departure`、`arrival`、`date` | `{"departure": "PEK", "arrival": "HND", "date": "2026-08-05"}` |

注：部分 tag 存在条件必填（如 `finance.fundamental` 的 symbol/cn_code 按 type 而定），不在 handler 校验范围内，由 API 返回 400 后 message 原样返回给 LLM 自纠兜底。

### 4. 错误处理与重试

重试逻辑内置于 `AnySearchClient.search()`，总尝试次数 = 首次请求 + 最多 2 次重试（`MAX_EXTRA_ATTEMPTS = 2`）：

| 状态码 / 错误 | 异常类型 | 是否重试 | 处理方式 |
|---------------|----------|----------|----------|
| 网络错误、超时 | `aiohttp.ClientConnectorError`、`asyncio.TimeoutError` | 重试 | 指数退避 + 抖动，耗尽后按网络/超时提示 |
| 429 限流 | `AnySearchRateLimitError` | 重试 | 优先 `data.retry_after`，回退 `Retry-After` 头 |
| 5xx（500/502/503/504） | `AnySearchAPIError` | 重试 | 指数退避 + 抖动 |
| 401/403 认证失败 | `AnySearchAuthError` | 不重试 | 提示配置正确的 API Key |
| 402 配额耗尽 | `AnySearchQuotaExhaustedError` | 不重试 | 记录 error 日志 + 提示配置 Key 或等待重置 |
| 400 及其他 | `AnySearchAPIError` | 不重试 | message 原样返回给 LLM 便于自纠 |

具体行为：

- **重试等待**：`max(2^attempt + random(0, 1), retry_after)` 秒，即指数退避加随机抖动；429 时优先取响应体 `data.retry_after`，否则回退到 `Retry-After` 响应头，保证至少等待建议时间。
- **不重试的理由**：401/403 重试无意义（Key 无效不会自己变好）；402 配额用尽后插件**没有自动注册、自动恢复机制**，即使响应中附带备用 Key（`data.api_key`）也会被故意忽略，只做日志与友好提示。
- **402 的 symbol 区分**：日志中区分 `daily_free_quota_exhausted`（匿名日额度）、`quota_exhausted`（付费额度）、`user_daily_quota_exhausted`（用户日额度）三种情况。
- **429 携带配额信息**：`AnySearchRateLimitError` 附带 retry_after、limit、remaining、reset_at，供上层决策；429 的 `X-RateLimit-*` 响应头会记入 debug 日志。
- 每次重试都会调用 `retry_callback`，计入指标中的重试次数。

### 5. 网页正文提取（extract）逻辑

网页正文提取走 MCP JSON-RPC 协议，请求 `POST {api_base}/mcp` 端点，**不是** REST 风格的 `/v1/extract`（该端点不存在）。一次提取包含三次顺序调用：

1. `initialize`：声明协议版本 `2025-03-26` 与客户端信息（id=1）。
2. `notifications/initialized`：MCP 规范要求 initialize 成功后必须发送的通知（无 id，响应通常为 202，跳过解析）。
3. `tools/call extract`：`{"name": "extract", "arguments": {"url": url}}`（id=2），从响应 `result.content[]` 中拼接所有 `type == "text"` 的文本。

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize",
 "params": {"protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "astrbot_plugin_anysearch_x", "version": "2.0.0"}}}
{"jsonrpc": "2.0", "method": "notifications/initialized"}
{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
 "params": {"name": "extract", "arguments": {"url": "https://example.com"}}}
```

会话管理：首次响应的 `Mcp-Session-Id` 头会被回传到后续请求（Streamable HTTP 会话管理）。响应解析同时兼容 JSON 与 SSE（`text/event-stream` 的 `data:` 行）两种格式，请求头 `Accept` 声明为 `application/json, text/event-stream`。

其他行为：

- 匿名可用，配置了 api_key 时携带 `Authorization: Bearer` 头。
- 仅接受 http/https 协议 URL，长度超过 2048 字符（`MAX_URL_LEN`）直接拒绝，不发请求。
- 独立的 30 秒超时（`EXTRACT_TIMEOUT_SEC`，对齐 API 的 504 上限），与搜索超时无关。
- 返回的 markdown 截断到 `extract_max_length`（默认 8000 字符）。
- 错误分类提示：415 目标不是 HTML 内容、502 目标页面抓取失败、504 提取超时。提取不做重试。

### 6. 缓存与指标

**SearchCache**（`cache.py`）：纯标准库实现的 LRU + TTL 内存缓存，容量上限 128 条。

- 默认 TTL 300 秒（`cache_ttl` 配置）；设为 0 时插件不创建缓存实例，即完全禁用。
- 只缓存成功结果，失败不写入，避免把错误结果缓存起来反复返回。
- `make_key()` 用 MD5 生成键：每段参数先拼长度前缀（`len:value`）再以 `|` 连接，防止分隔符碰撞导致不同查询命中同一缓存项。web_search 与 advanced_search 分别以 `("search", query, "", "", max_results, format)` 与 `("search", query, tag, params_json, max_results, format)` 构造键，tag 与 params 不同不会互相串缓存。

**PluginMetrics**（`main.py`）：轻量请求指标，统计以下字段：

| 字段 | 含义 |
|------|------|
| 请求总数 / 成功数 / 失败数 | 每次成功或失败调用 +1 |
| 缓存命中 | 缓存直接返回时 +1 |
| 重试次数 | 客户端每次退避重试时 +1（retry_callback） |
| 平均延迟 | 累计延迟 / 成功数（毫秒），优先取 API 的 search_time_ms |

插件卸载（`terminate()`）时输出汇总日志，形如「插件卸载。指标统计: 请求=12 成功=10 失败=2 缓存命中=4 重试=1 平均延迟=312ms」，方便排查插件使用情况。

## 故障排查

### 搜索无结果

1. 检查 `api_base` 配置是否正确
2. 如果未配置 API Key，匿名模式有较低的速率限制，可能被限流
3. 尝试切换 `zone` 配置（`cn` / `intl`）
4. 检查网络连接是否正常

### 网页提取如何工作？

网页正文提取通过 MCP JSON-RPC 协议完成：插件向 `{api_base}/mcp` 端点发送 `tools/call extract` 请求，匿名即可使用。返回内容为 markdown 格式，超出 `extract_max_length`（默认 8000 字符）的部分会被截断。仅支持 http/https 协议链接。

### 缓存如何工作？

相同查询在 `cache_ttl`（默认 300 秒）内会直接返回缓存结果，不重复调用 API。设置 `cache_ttl` 为 0 可禁用缓存。

### 重试机制如何工作？

遇到网络错误、服务器 5xx 错误或 429 限流时，插件会自动重试最多 2 次，使用指数退避加随机抖动。429 响应会解析 `Retry-After` 头作为最小等待时间。401（认证失败）与 402（配额耗尽）直接报错，不重试——配额用尽时请配置 `api_key` 或等待额度重置。

## 许可证

本项目基于 [AGPL-3.0](LICENSE) 许可证开源。

## 作者

**NoFizz** · [GitHub](https://github.com/NoFizz)

如遇问题或有功能建议，欢迎提交 [Issue](https://github.com/NoFizz/astrbot_plugin_anysearch_x/issues)。
