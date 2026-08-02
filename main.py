"""AnySearch 智能搜索插件 v2 — 基于 AnySearch API 的 LLM 可调用搜索工具集。

v2 重构要点（相对 v1）:
- 工具注册改用 FunctionTool + context.add_llm_tools（不再使用装饰器式工具注解）；
- HTTP 请求全部委托给 client.AnySearchClient（重试/错误映射/配额耗尽提示在客户端内完成）；
- API Key 原样透传（不再解密混淆）；日志不使用插件名前缀。

SIZE_OK（~300 纯 LOC）: AstrBot 插件框架约定 main.py 为唯一入口；format_search_results
与 PluginMetrics 由 v2 规范要求置于本模块，HTTP 层（client/cache/models）已独立拆分，
此处为框架门面 + 两个测试面纯组件，再拆分将破坏框架加载约定。
"""

from __future__ import annotations

import asyncio
import json
import time

import aiohttp

from astrbot.api import AstrBotConfig, FunctionTool, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .cache import SearchCache
from .client import AnySearchClient
from .models import (
    ALL_TAGS,
    DEFAULT_API_BASE,
    DEFAULT_EXTRACT_MAX_LENGTH,
    MAX_QUERY_LEN,
    MAX_URL_LEN,
    TAG_DIRECTORY,
    TAG_REQUIRED_PARAMS,
    AnySearchAPIError,
    AnySearchAuthError,
    AnySearchError,
    AnySearchQuotaExhaustedError,
)

# ─── 结果格式化（模块级纯函数）────────────────────────────────────────────────


def _annotate_tag(tag: str) -> str:
    """为必填参数 tag 追加标注，如 'code.doc' → 'code.doc(需 library)'。"""
    reqs = TAG_REQUIRED_PARAMS.get(tag)
    if not reqs:
        return tag
    return f"{tag}(需 {','.join(reqs)})"


def format_search_results(results: list[dict], output_format: str = "json") -> str:
    """将搜索结果列表格式化为文本（按 URL 去重）。

    Args:
        results: 搜索结果列表，每项含 title/url/snippet/content 字段。
        output_format: "markdown" 或 "json"（默认）。

    Returns:
        格式化后的文本；空结果返回友好提示。
    """
    if not results:
        return "未找到相关搜索结果。建议更换关键词或切换搜索区域。"
    # 按 URL 去重
    seen_urls: set[str] = set()
    unique_results: list[dict] = []
    for item in results:
        url = item.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique_results.append(item)
    formatted: list[str] = []
    for i, item in enumerate(unique_results, 1):
        title = item.get("title", "无标题")
        url = item.get("url", "")
        snippet = item.get("snippet", item.get("content", ""))
        if output_format == "markdown":
            entry = f"**{i}. [{title}]({url})**\n{snippet}"
        else:
            entry = f"{i}. {title}\n{snippet}\n{url}"
        formatted.append(entry)
    return "\n\n".join(formatted)


# ─── 指标统计 ───────────────────────────────────────────────────────────────────


class PluginMetrics:
    """轻量级请求指标统计。"""

    def __init__(self) -> None:
        self.total_requests: int = 0
        self.success_count: int = 0
        self.error_count: int = 0
        self.cache_hits: int = 0
        self.retries: int = 0
        self.total_latency_ms: float = 0.0

    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.success_count += 1
        self.total_latency_ms += latency_ms

    def record_error(self) -> None:
        self.total_requests += 1
        self.error_count += 1

    def record_cache_hit(self) -> None:
        self.cache_hits += 1

    def record_retry(self) -> None:
        self.retries += 1

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.success_count if self.success_count else 0.0

    def summary(self) -> str:
        return (
            f"请求={self.total_requests} 成功={self.success_count} "
            f"失败={self.error_count} 缓存命中={self.cache_hits} "
            f"重试={self.retries} 平均延迟={self.avg_latency_ms:.0f}ms"
        )


# ─── 插件主体 ───────────────────────────────────────────────────────────────────


@register(
    "astrbot_plugin_anysearch_x",
    "NoFizz",
    "基于 AnySearch API 的智能搜索插件，支持 40 种垂直搜索能力",
    "2.0.0",
    "https://github.com/NoFizz/astrbot_plugin_anysearch_x",
)
class AnySearchPlugin(Star):
    """AnySearch 搜索插件：向 LLM 暴露三个可调用工具（通用搜索/垂直搜索/网页提取）。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.api_base: str = str(config.get("api_base", DEFAULT_API_BASE)).rstrip("/")
        self.zone: str = str(config.get("zone", "cn")).strip()
        self.language: str = str(config.get("language", "zh-CN")).strip()
        self.output_format: str = str(config.get("format", "json")).strip()
        self.max_results: int = max(1, min(20, int(config.get("max_results", 10))))
        # API Key 原样透传（v1 的 XOR 混淆已废弃，不做解密）
        self.api_key: str = str(config.get("api_key", "")).strip()

        if not self.api_key:
            logger.warning("未配置 API Key，将以匿名模式运行（速率限制较低）")
        logger.info(
            f"已加载，max_results={self.max_results}，输出格式={self.output_format}"
        )

        self._session: aiohttp.ClientSession | None = None
        self._client: AnySearchClient | None = None
        self._session_lock = asyncio.Lock()
        self._closed = False
        self._timeout_sec: int = max(3, int(config.get("timeout", 15)))
        self._extract_max_length: int = int(
            config.get("extract_max_length", DEFAULT_EXTRACT_MAX_LENGTH)
        )
        self._semaphore = asyncio.Semaphore(3)
        self._metrics = PluginMetrics()

        # 缓存：cache_ttl=0 时禁用
        cache_ttl = int(config.get("cache_ttl", 300))
        self.cache: SearchCache | None = (
            SearchCache(ttl=cache_ttl) if cache_ttl > 0 else None
        )

        context.add_llm_tools(*self._build_tools())

    # ─── 工具注册 ───────────────────────────────────────────────────────────────

    def _build_tools(self) -> list[FunctionTool]:
        """构建 LLM 可调用工具列表（handler 签名: handler(event, **kwargs)）。"""
        return [
            FunctionTool(
                name="anysearch_web_search",
                description="搜索网页并返回相关结果。适用于通用信息查询，API 会自动路由到最佳数据源。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "（必填）搜索关键词，将用户问题转换为简洁的搜索词",
                        }
                    },
                    "required": ["query"],
                },
                handler=self._web_search,
            ),
            FunctionTool(
                name="anysearch_advanced_search",
                description="垂直领域精准搜索。当查询明显属于特定垂直领域（漏洞/论文/行情/代码/法规/专利/航班/药品等）时使用，可提升结果精度。tag 参数为可选：省略 tag 即按普通搜索自动路由，搜索照常成功；不确定领域时请改用 anysearch_web_search。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "（必填）搜索关键词",
                        },
                        "tag": {
                            "type": "string",
                            "description": (
                                "（可选）能力标签，格式 类别.子类别，根据查询内容自行判断领域后填写。"
                                "【重要】省略 tag 即为普通搜索，API 自动路由到最佳数据源，搜索照常进行、不会失败；"
                                "不要因为没传 tag 而担心搜索失败，更不要强行编造一个不相关的 tag。"
                                "标注 (需 xxx) 的 tag 必须在 params 中提供对应参数，否则会报错。"
                                "完整 tag 目录（40 个）："
                                + "; ".join(
                                    f"{cat}: {', '.join(_annotate_tag(t) for t in tags)}"
                                    for cat, tags in TAG_DIRECTORY.items()
                                )
                            ),
                        },
                        "params": {
                            "type": "object",
                            "additionalProperties": True,
                            "description": (
                                '（可选）扩展参数对象，如 {"library":"react"} 或 {"symbol":"AAPL"}。'
                                "【重要】仅当所选 tag 明确需要特定参数时才填写；"
                                "不需要参数或不确定时省略，不要硬凑无关参数。"
                            ),
                        },
                    },
                    "required": ["query"],
                },
                handler=self._advanced_search,
            ),
            FunctionTool(
                name="anysearch_extract",
                description="网页正文提取，返回 Markdown 文本。",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "（必填）要提取内容的网页完整 URL，仅支持 http/https",
                        }
                    },
                    "required": ["url"],
                },
                handler=self._extract_tool,
            ),
        ]

    # ─── 会话与客户端管理 ──────────────────────────────────────────────────────

    async def _ensure_client(self) -> AnySearchClient:
        """惰性创建 AnySearchClient（双检锁）。

        Raises:
            AnySearchError: 插件已关闭时拒绝创建新客户端。
        """
        if self._closed:
            raise AnySearchError("插件已关闭，不再接受新请求")
        if self._client is None:
            async with self._session_lock:
                if self._closed:
                    raise AnySearchError("插件已关闭，不再接受新请求")
                if self._client is None:
                    connector = aiohttp.TCPConnector(
                        limit=20,
                        limit_per_host=5,
                        ttl_dns_cache=60,
                        enable_cleanup_closed=True,
                    )
                    timeout = aiohttp.ClientTimeout(total=self._timeout_sec)
                    self._session = aiohttp.ClientSession(
                        timeout=timeout, connector=connector
                    )
                    self._client = AnySearchClient(
                        self._session,
                        api_base=self.api_base,
                        api_key=self.api_key,
                        max_results=self.max_results,
                        zone=self.zone,
                        language=self.language,
                        output_format=self.output_format,
                        timeout_sec=self._timeout_sec,
                        extract_max_length=self._extract_max_length,
                        retry_callback=self._metrics.record_retry,
                        debug_logger=logger,
                    )
        return self._client

    # ─── 错误处理 ───────────────────────────────────────────────────────────────

    def _user_facing_error(self, e: Exception, prefix: str) -> str:
        """将异常转换为用户友好的中文提示。"""
        if isinstance(e, AnySearchAuthError):
            return f"{prefix}：API Key 无效或已过期。请在插件设置中配置正确的 API Key。"
        if isinstance(e, AnySearchQuotaExhaustedError):
            # 额度用尽：明确报错，提示用户配置 Key（无自动注册/自动恢复）
            logger.error(
                f"{prefix}：API 配额已用尽（symbol: {e.symbol}），请在插件设置中配置 API Key 或等待额度重置"
            )
            return f"{prefix}：API 配额已用尽。请在插件设置中配置 API Key，或等待额度重置。"
        if isinstance(e, aiohttp.ClientConnectorError):
            return f"{prefix}：无法连接到 AnySearch 服务器，请检查网络。"
        if isinstance(e, asyncio.TimeoutError):
            return f"{prefix}：请求超时，请稍后重试。"
        if isinstance(e, AnySearchError):
            return f"{prefix}：{e}"
        logger.error(f"未知错误: {e}", exc_info=True)
        return str(e)

    # ─── 搜索核心 ───────────────────────────────────────────────────────────────

    async def _run_search(
        self, query: str, tag: str | None, params: dict | None, cache_key: str
    ) -> str:
        """执行带缓存的搜索，返回格式化结果字符串（不抛异常）。

        Args:
            query: 搜索关键词。
            tag: 能力 tag，None 表示自动路由。
            params: 扩展参数对象，None 表示不发送。
            cache_key: 缓存键；cache 禁用时仍传入但不使用。
        """
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                self._metrics.record_cache_hit()
                logger.info(f"缓存命中: query='{query}'")
                return cached
        try:
            async with self._semaphore:
                client = await self._ensure_client()
                start_ms = time.monotonic() * 1000
                results, metadata = await client.search(query, tag=tag, params=params)
                latency_ms = metadata.get("search_time_ms") or (
                    time.monotonic() * 1000 - start_ms
                )
                self._metrics.record_success(latency_ms)
            result = format_search_results(results, self.output_format)
            if self.cache:
                self.cache.set(cache_key, result)
            return result
        except Exception as e:
            self._metrics.record_error()
            return self._user_facing_error(e, "搜索失败")

    # ─── 工具 handler ──────────────────────────────────────────────────────────

    async def _web_search(self, event: AstrMessageEvent, query: str) -> str:
        """通用搜索工具：API 自动路由到最佳数据源。"""
        query = (query or "").strip()
        if not query:
            return "请提供有效的搜索关键词。"
        if len(query) > MAX_QUERY_LEN:
            return "搜索失败：关键词过长。"
        logger.info(f"搜索: query='{query}'")
        cache_key = SearchCache.make_key(
            "search", query, "", "", self.max_results, self.output_format
        )
        return await self._run_search(query, None, None, cache_key)

    async def _advanced_search(
        self,
        event: AstrMessageEvent,
        query: str,
        tag: str | None = None,
        params: dict | str | None = None,
    ) -> str:
        """垂直搜索工具：按能力标签在特定领域精准搜索。"""
        query = (query or "").strip()
        if not query:
            return "请提供有效的搜索关键词。"
        if len(query) > MAX_QUERY_LEN:
            return "搜索失败：关键词过长。"

        # 降级提示前缀（结果返回给 LLM 时可见，帮助 LLM 自纠）
        degraded_notices: list[str] = []

        # tag 校验：无效 tag 降级为普通搜索（不阻塞搜索，避免 LLM 硬凑参数）
        tag = (tag or "").strip()
        if tag and tag not in ALL_TAGS:
            logger.warning(f"能力标签 '{tag}' 无效，已忽略并按普通搜索处理（自动路由）")
            degraded_notices.append(f"[tag '{tag}' 无效，已按普通搜索处理]")
            tag = ""

        # params 兼容 dict 或 JSON 字符串；解析失败/非对象时降级为不传
        parsed_params: dict | None = None
        params_degraded = False
        if isinstance(params, dict):
            parsed_params = params
        else:
            raw = str(params or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                except (json.JSONDecodeError, ValueError, TypeError):
                    logger.warning(
                        f"params 不是合法的 JSON，已忽略并按普通搜索处理: {raw[:100]}"
                    )
                    degraded_notices.append("[params 无效，已按普通搜索处理]")
                    params_degraded = True
                    parsed = None
                if not isinstance(parsed, dict):
                    logger.warning("params 不是 JSON 对象，已按普通搜索处理")
                    degraded_notices.append("[params 无效，已按普通搜索处理]")
                    params_degraded = True
                    parsed = None
                parsed_params = parsed

        # 必填参数校验：所选 tag 缺少必填 params 时直接友好提示（不发请求，避免 400 循环）。
        # params 已降级（无效）时跳过校验——降级即按普通搜索处理，无需再校验。
        if not params_degraded and tag and tag in TAG_REQUIRED_PARAMS:
            missing = [
                p for p in TAG_REQUIRED_PARAMS[tag] if not (parsed_params or {}).get(p)
            ]
            if missing:
                return (
                    f"搜索失败：tag '{tag}' 需要 params 参数 {', '.join(missing)}。"
                    f"请在 params 中提供，如 {json.dumps({missing[0]: '示例值'}, ensure_ascii=False)}。"
                )

        logger.info(
            f"高级搜索: query='{query}', tag='{tag}', params={parsed_params or None}"
        )
        params_json = (
            json.dumps(parsed_params, sort_keys=True, ensure_ascii=False)
            if parsed_params
            else ""
        )
        cache_key = SearchCache.make_key(
            "search", query, tag, params_json, self.max_results, self.output_format
        )
        result = await self._run_search(query, tag or None, parsed_params, cache_key)
        if degraded_notices:
            return " ".join(degraded_notices) + "\n" + result
        return result

    async def _extract_tool(self, event: AstrMessageEvent, url: str) -> str:
        """网页正文提取工具：返回 Markdown 文本。"""
        url = (url or "").strip()
        if not url:
            return "请输入有效的网页 URL。"
        if len(url) > MAX_URL_LEN:
            return "网页提取失败：URL 过长。"
        logger.info(f"网页提取: url='{url}'")
        try:
            async with self._semaphore:
                client = await self._ensure_client()
                return await client.extract(url)
        except Exception as e:
            if isinstance(e, AnySearchAPIError) and e.status == 415:
                return "网页提取失败：目标页面不是 HTML 内容。"
            if isinstance(e, AnySearchAPIError) and e.status == 502:
                return "网页提取失败：目标页面抓取失败。"
            if isinstance(e, AnySearchAPIError) and e.status == 504:
                return "网页提取失败：提取超时。"
            return self._user_facing_error(e, "网页提取失败")

    # ─── 生命周期 ───────────────────────────────────────────────────────────────

    async def terminate(self) -> None:
        logger.info(f"插件卸载。指标统计: {self._metrics.summary()}")
        self._closed = True
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                    await asyncio.sleep(0.25)
                except Exception as e:
                    logger.warning(f"关闭 Session 时出错: {e}")
