import asyncio
import base64
import hashlib
import json
import random
import time
from collections import OrderedDict
from typing import Any, Callable, Coroutine, Optional
from urllib.parse import urlparse  # noqa: F401 — 待 extract 启用后使用

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

MAX_QUERY_LEN = 500
MAX_URL_LEN = 2048

# 旧 domain 值到 API v3 tag 的兼容提示（仅用于错误提示，不做自动转换）
LEGACY_DOMAIN_HINTS = {
    "finance": "finance.quote / finance.news / finance.fundamental / finance.macro",
    "academic": "academic.search / academic.preprint / academic.biomedical",
    "code": "code.doc / code.snippet",
    "legal": "legal.case / legal.statute / legal.legislation",
    "geo": "environment.aqi / energy.electricity",
    "medical": "health.drug / health.trial / health.stats",
    "cybersecurity": "security.vuln / security.intel / security.scan",
}


# ─── 异常层次 ───────────────────────────────────────────────────────────────────

class AnySearchError(Exception):
    pass


class AnySearchAuthError(AnySearchError):
    pass


class AnySearchAPIError(AnySearchError):
    def __init__(self, status: int, message: str, retry_after: Optional[float] = None):
        self.status = status
        self.retry_after = retry_after
        super().__init__(message)


# ─── 缓存 ──────────────────────────────────────────────────────────────────────

class SearchCache:
    """LRU + TTL 内存缓存，仅缓存成功结果。"""

    def __init__(self, ttl: int = 300, max_size: int = 128):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self.ttl = ttl
        self.max_size = max_size

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl:
                self._cache.move_to_end(key)
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, time.time())
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    @staticmethod
    def make_key(*args: Any) -> str:
        """生成 MD5 哈希 key。使用长度前缀防止分隔符碰撞。"""
        parts = [f"{len(s)}:{s}" for s in (str(a) for a in args)]
        raw = "|".join(parts)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()


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


# ─── API Key 工具 ───────────────────────────────────────────────────────────────

def _decrypt_api_key(encoded: str, secret: str = "astrbot_anysearch") -> str:
    """解密 XOR 混淆的 API Key。"""
    if not encoded:
        return ""
    try:
        xor_bytes = base64.urlsafe_b64decode(encoded.encode("utf-8"))
        secret_bytes = secret.encode("utf-8")
        key_bytes = bytes(a ^ secret_bytes[i % len(secret_bytes)] for i, a in enumerate(xor_bytes))
        return key_bytes.decode("utf-8")
    except Exception:
        return encoded


# ─── 插件主体 ───────────────────────────────────────────────────────────────────

# 免费版限制（AnySearch 官方当前仅提供 Free 版：1000次/天、20QPS、不支持 extract）


@register("astrbot_plugin_anysearch_x", "NoFizz", "基于 AnySearch API 的智能搜索插件，支持42种垂直搜索能力", "1.0.0", "https://github.com/NoFizz/astrbot_plugin_anysearch_x")
class AnySearchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.api_base: str = str(config.get("api_base", "https://api.anysearch.com")).rstrip("/")
        self.zone: str = str(config.get("zone", "cn")).strip()
        self.language: str = str(config.get("language", "zh-CN")).strip()
        self.output_format: str = str(config.get("format", "json")).strip()

        # max_results（用户自定义，API 支持 1-20）
        self.max_results: int = max(1, min(20, int(config.get("max_results", 10))))

        # 解密 API Key
        raw_key = str(config.get("api_key", "")).strip()
        if raw_key.startswith("enc:"):
            self.api_key = _decrypt_api_key(raw_key[4:])
        elif raw_key:
            self.api_key = raw_key
        else:
            self.api_key = ""

        if not self.api_key:
            logger.warning("[AnySearch] 未配置 API Key，将以匿名模式运行（速率限制较低）")

        logger.info(f"[AnySearch] 已加载（免费版，max_results={self.max_results}，extract 不可用）")

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self._closed = False
        self._timeout_sec: int = max(3, int(config.get("timeout", 15)))
        self._semaphore = asyncio.Semaphore(3)
        self._metrics = PluginMetrics()

        # 初始化缓存
        cache_ttl = int(config.get("cache_ttl", 300))
        self.cache: Optional[SearchCache] = SearchCache(ttl=cache_ttl) if cache_ttl > 0 else None

    # ─── 会话管理 ───────────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise AnySearchError("插件已关闭，不再接受新请求")
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._closed:
                    raise AnySearchError("插件已关闭，不再接受新请求")
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(
                        limit=20,
                        limit_per_host=5,
                        ttl_dns_cache=60,
                        enable_cleanup_closed=True,
                    )
                    timeout = aiohttp.ClientTimeout(total=self._timeout_sec)
                    self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session

    # ─── 通用重试 ───────────────────────────────────────────────────────────────

    async def _request_with_retry(self, coro_factory: Callable[[], Coroutine], max_retries: int = 2) -> Any:
        """通用重试包装器。coro_factory 每次调用返回新协程。"""
        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                async with self._semaphore:
                    return await coro_factory()
            except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < max_retries:
                    self._metrics.record_retry()
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"[AnySearch] 重试 {attempt + 1}/{max_retries}，等待 {wait_time:.1f}s: {e}")
                    await asyncio.sleep(wait_time)
            except AnySearchAPIError as e:
                if (e.status >= 500 or e.status == 429) and attempt < max_retries:
                    last_error = e
                    self._metrics.record_retry()
                    retry_after = e.retry_after or 0
                    wait_time = max(retry_after, 2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"[AnySearch] 重试 {attempt + 1}/{max_retries}，等待 {wait_time:.1f}s: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except AnySearchError:
                raise
        logger.error(f"[AnySearch] 所有重试已耗尽: {last_error}", exc_info=last_error)
        if last_error:
            raise last_error
        raise AnySearchError("未知失败")

    # ─── 错误处理 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _handle_error(e: Exception, prefix: str) -> str:
        """统一错误处理，返回用户友好的中文提示。"""
        if isinstance(e, AnySearchAuthError):
            return f"{prefix}：{e}。请在插件设置中配置正确的 API Key。"
        if isinstance(e, (AnySearchAPIError, AnySearchError)):
            return f"{prefix}：{e}"
        if isinstance(e, aiohttp.ClientConnectorError):
            return f"{prefix}：无法连接到 AnySearch 服务器，请检查网络。"
        if isinstance(e, asyncio.TimeoutError):
            return f"{prefix}：请求超时，请稍后重试。"
        logger.error(f"[AnySearch] 未知错误: {e}", exc_info=True)
        return f"{prefix}：发生未知错误，请稍后重试。"

    # ─── 搜索核心 ───────────────────────────────────────────────────────────────

    async def _do_search(self, query: str, tag: Optional[str] = None, params: Optional[dict] = None) -> str:
        """执行搜索请求。成功返回格式化结果字符串，失败抛出异常。"""
        session = await self._get_session()

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "query": query,
            "max_results": self.max_results,
            "zone": self.zone,
            "language": self.language,
            "format": self.output_format,
        }
        if tag:
            payload["tag"] = tag
        if params:
            payload["params"] = params

        start_ms = time.time() * 1000

        async with session.post(
            f"{self.api_base}/v1/search",
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status == 401:
                raise AnySearchAuthError("API Key 无效或未配置")
            if resp.status == 402:
                raise AnySearchError("API 配额已用尽，请配置 API Key 或等待重置")
            if resp.status == 429:
                retry_after = self._parse_retry_after(resp)
                raise AnySearchAPIError(429, "API 调用频率超限，请稍后重试", retry_after=retry_after)
            if resp.status >= 500:
                raise AnySearchAPIError(resp.status, f"服务器错误 (HTTP {resp.status})")
            if resp.status != 200:
                raise AnySearchAPIError(resp.status, f"请求失败 (HTTP {resp.status})")

            try:
                data = await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                text = await resp.text()
                logger.error(f"[AnySearch] 无效的 JSON 响应: {text[:500]}")
                raise AnySearchError("服务器返回了无效的响应格式")

        if data.get("code") != 0:
            raise AnySearchError(data.get("message", "未知错误"))

        # 记录指标
        latency_ms = time.time() * 1000 - start_ms
        api_time = data.get("data", {}).get("metadata", {}).get("search_time_ms")
        self._metrics.record_success(api_time or latency_ms)

        results = data.get("data", {}).get("results", [])
        return self._format_results(results)

    async def _do_search_with_retry(self, query: str, tag: Optional[str] = None, params: Optional[dict] = None) -> str:
        """带重试和缓存的搜索。仅成功结果写入缓存。"""
        cache_key: Optional[str] = None
        if self.cache:
            params_str = json.dumps(params, sort_keys=True, ensure_ascii=False) if params else ""
            cache_key = SearchCache.make_key("search", query, tag or "", params_str, self.max_results, self.output_format)
            cached = self.cache.get(cache_key)
            if cached is not None:
                self._metrics.record_cache_hit()
                logger.info(f"[AnySearch] 缓存命中: query='{query}'")
                return cached

        result = await self._request_with_retry(
            lambda: self._do_search(query, tag=tag, params=params),
        )

        if self.cache and cache_key:
            self.cache.set(cache_key, result)
        return result

    # ─── 格式化 ─────────────────────────────────────────────────────────────────

    def _format_results(self, results: list) -> str:
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
            if self.output_format == "markdown":
                entry = f"**{i}. [{title}]({url})**\n{snippet}"
            else:
                entry = f"{i}. {title}\n{snippet}\n{url}"
            formatted.append(entry)
        return "\n\n".join(formatted)

    # ─── 工具方法 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_retry_after(resp: aiohttp.ClientResponse) -> Optional[float]:
        """从响应头解析 Retry-After 值（秒）。"""
        ra_header = resp.headers.get("Retry-After")
        if ra_header:
            try:
                return float(ra_header)
            except (ValueError, TypeError):
                pass
        return None

    # ─── LLM 工具 ──────────────────────────────────────────────────────────────

    @filter.llm_tool(name="anysearch_web_search")
    async def search(self, event: AstrMessageEvent, query: str) -> str:
        """搜索网页并返回相关结果。适用于通用信息查询，API会自动路由到最佳数据源。如需多个查询可多次调用此工具。

        Args:
            query(string): 搜索关键词，将用户问题转换为简洁的搜索词
        """
        if not query or not query.strip():
            return "请提供有效的搜索关键词。"
        if len(query) > MAX_QUERY_LEN:
            return "搜索失败：关键词过长。"
        if not self.api_base:
            return "AnySearch API 地址未配置，请在插件设置中填写。"

        logger.info(f"[AnySearch] 搜索: query='{query}'")

        try:
            return await self._do_search_with_retry(query)
        except Exception as e:
            self._metrics.record_error()
            return self._handle_error(e, "搜索失败")

    @filter.llm_tool(name="anysearch_advanced_search")
    async def advanced_search(self, event: AstrMessageEvent, query: str, tag: str, params: str) -> str:
        """在特定垂直领域进行精准搜索，支持42种专业能力标签。当需要金融行情、学术论文、代码文档、法律法规、漏洞情报、药品信息等精确数据时使用。

        Args:
            query(string): 搜索关键词
            tag(string): 能力标签，格式"类别.子类别"，留空则自动路由。按类别: [code] code.doc(需params.library) code.snippet | [finance] finance.quote(需params.symbol+type) finance.news(需params.type) finance.fundamental finance.macro finance.calendar finance.screen | [academic] academic.search academic.preprint academic.biomedical academic.citation(需params.id) academic.dataset | [legal] legal.case legal.statute legal.legislation | [security] security.vuln(需params.type+value) security.intel(需params.ioc) security.scan security.noise(需params.ip) | [health] health.drug(需params.type) health.trial health.stats | [business] business.company business.jobs business.people business.trade | [travel] travel.flight(需params.departure+arrival+date) travel.flight_status | [其他] social_media.social_media gaming.esports(需params.type) gaming.store energy.electricity energy.production environment.aqi agriculture.fao ip.global resource.image film.torrent general.general
            params(string): JSON格式扩展参数，如{"library":"react"}或{"symbol":"AAPL","type":"stock"}。不需要时留空。
        """
        if not query or not query.strip():
            return "请提供有效的搜索关键词。"
        if len(query) > MAX_QUERY_LEN:
            return "搜索失败：关键词过长。"
        if not self.api_base:
            return "AnySearch API 地址未配置，请在插件设置中填写。"

        # 解析 tag
        tag = (tag or "").strip()

        # 旧版 domain 兼容提示
        if tag and "." not in tag and tag.lower() in LEGACY_DOMAIN_HINTS:
            return f"搜索失败：'{tag}' 不是有效的能力标签。该领域可用的标签: {LEGACY_DOMAIN_HINTS[tag.lower()]}。请使用 '类别.子类别' 格式，如 'finance.quote'。"

        # 解析 params（LLM 可能传入 JSON 字符串或直接传入 dict 对象）
        parsed_params: Optional[dict] = None
        if isinstance(params, dict):
            parsed_params = params
        else:
            params = str(params or "").strip()
            if params:
                try:
                    parsed_params = json.loads(params)
                    if not isinstance(parsed_params, dict):
                        return "搜索失败：params 必须是 JSON 对象格式，如 {\"library\":\"react\"}。"
                except (json.JSONDecodeError, ValueError, TypeError):
                    return f"搜索失败：params 不是合法的 JSON。收到: '{str(params)[:100]}'。请使用如 {{\"library\":\"react\"}} 的格式。"

        logger.info(f"[AnySearch] 高级搜索: query='{query}', tag='{tag}', params={params or 'None'}")

        try:
            return await self._do_search_with_retry(query, tag=tag or None, params=parsed_params)
        except Exception as e:
            self._metrics.record_error()
            return self._handle_error(e, "搜索失败")

    @filter.llm_tool(name="anysearch_extract")
    async def extract_page(self, event: AstrMessageEvent, url: str) -> str:
        """【当前不可用】网页正文提取功能（免费版不支持，待专业版启用）。请勿调用此工具，直接使用搜索结果中的摘要信息。

        Args:
            url(string): 要提取内容的网页完整 URL
        """
        # 网页提取功能当前不可用（AnySearch 官方免费版不支持 extract，待 Pro 版发布后启用）
        return "网页提取功能当前不可用。AnySearch 官方免费版不支持网页提取，待专业版发布后将自动启用。请直接使用搜索结果中的摘要信息。"

    # ─── 生命周期 ───────────────────────────────────────────────────────────────

    async def terminate(self) -> None:
        logger.info(f"[AnySearch] 插件卸载。指标统计: {self._metrics.summary()}")
        self._closed = True
        async with self._session_lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                    await asyncio.sleep(0.25)
                except Exception as e:
                    logger.warning(f"[AnySearch] 关闭 Session 时出错: {e}")
