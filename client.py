"""client.py — AnySearchClient：AnySearch API 的异步 HTTP 客户端。

封装 /v1/search 与 /mcp 的请求构造、错误映射与重试策略；session 由外部注入，
客户端不创建/关闭会话，零 astrbot 依赖。仅 import aiohttp + models + 标准库。
"""
from __future__ import annotations

import asyncio
import random
import urllib.parse
from collections.abc import Callable
from typing import Any

import aiohttp
from models import (
    DEFAULT_API_BASE,
    DEFAULT_EXTRACT_MAX_LENGTH,
    EXTRACT_TIMEOUT_SEC,
    MAX_URL_LEN,
    MCP_ENDPOINT,
    RETRYABLE_STATUSES,
    SEARCH_ENDPOINT,
    AnySearchAPIError,
    AnySearchAuthError,
    AnySearchError,
    AnySearchQuotaExhaustedError,
    AnySearchRateLimitError,
)

# 首次尝试之外的额外重试次数（总尝试 = MAX_EXTRA_ATTEMPTS + 1）
MAX_EXTRA_ATTEMPTS = 2

# 客户端透明重试的状态码（429 与 5xx 一致，见 spec 重试循环）：
# 指数退避，有 retry_after 时等待 ≥ retry_after；耗尽后抛最后错误。


class AnySearchClient:
    """AnySearch API 客户端（session 注入式，零 astrbot 依赖）。

    参数语义见 __init__ 签名与默认值；retry_callback 为重试前无参回调，
    debug_logger 为可选调试日志器（None 时跳过调试日志）。
    """

    def __init__(
        self,
        session,
        api_base: str = DEFAULT_API_BASE,
        *,
        api_key: str = "",
        max_results: int = 10,
        zone: str = "cn",
        language: str = "zh-CN",
        output_format: str = "json",
        timeout_sec: float = 15,
        extract_max_length: int = DEFAULT_EXTRACT_MAX_LENGTH,
        retry_callback: Callable[[], None] | None = None,
        debug_logger=None,
    ) -> None:
        self._session = session
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._max_results = max_results
        self._zone = zone
        self._language = language
        self._output_format = output_format
        self._timeout_sec = timeout_sec
        self._extract_max_length = extract_max_length
        self._retry_callback = retry_callback
        self._debug_logger = debug_logger
        # 402 自动恢复时保存的新 Key（初始为 None，恢复一次后不再触发）
        self._auto_issued_api_key: str | None = None

    @property
    def auto_issued_api_key(self) -> str | None:
        return self._auto_issued_api_key

    # ─── 搜索 ─────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        tag: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[list[dict], dict]:
        """执行搜索，返回 (results, metadata)。

        Args:
            query: 搜索关键词。
            tag: 能力 tag（如 "code.doc"）；仅非空时发送。
            params: 扩展参数对象（如 {"library": "golang"}）；仅非空时发送。

        Returns:
            (结果列表, 元数据字典)。

        Raises:
            AnySearchError: 响应格式无效、业务 code != 0、重试耗尽。
            aiohttp.ClientConnectorError / asyncio.TimeoutError: 网络错误重试耗尽后上抛。
            非 200 错误映射为 _raise_for_status 对应子类（402 自动换 Key 一次）。
        """
        payload: dict[str, Any] = {
            "query": query,
            "max_results": self._max_results,
            "zone": self._zone,
            "language": self._language,
            "format": self._output_format,
        }
        if tag:
            payload["tag"] = tag
        if params:
            payload["params"] = params

        url = f"{self._api_base}{SEARCH_ENDPOINT}"
        headers = self._auth_headers(self._auto_issued_api_key or self._api_key)
        last_error: Exception | None = None

        for attempt in range(MAX_EXTRA_ATTEMPTS + 1):
            try:
                # await 后进入 CM：兼容真实 aiohttp（await 得 ClientResponse，本身是
                # 异步 CM）与测试 FakeSession（await 得 FakeResponse，同样是异步 CM）
                async with await self._session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self._timeout_sec),
                ) as resp:
                    body = await self._parse_json(resp)
                    status = resp.status
                    resp_headers = resp.headers
            except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as exc:
                last_error = exc
                await self._retry(attempt, None)
                continue

            if status == 200:
                if body.get("code") != 0:
                    raise AnySearchError(str(body.get("message") or "请求失败"))
                data = body.get("data") or {}
                return data.get("results", []), data.get("metadata", {})

            # 429/5xx 透明重试：指数退避，有 retry_after 时等待 ≥ retry_after；
            # 耗尽后抛最后错误（429 为保留权威 retry_after 的限流异常）
            if status in RETRYABLE_STATUSES:
                if status == 429 and self._debug_logger is not None:
                    rate_headers = {k: v for k, v in resp_headers.items() if k.lower().startswith("x-ratelimit")}
                    self._debug_logger.debug("rate limit reached", {"headers": rate_headers})
                retry_after = self._parse_retry_after(body, resp_headers)
                try:
                    self._raise_for_status(status, body, resp_headers)
                except AnySearchError as exc:
                    last_error = exc
                await self._retry(attempt, retry_after)
                continue

            # 402 配额耗尽：daily_free 携带自动 Key 时换 Key 重试一次
            if status == 402:
                try:
                    self._raise_for_status(status, body, resp_headers)
                except AnySearchQuotaExhaustedError as exc:
                    if exc.symbol == "daily_free_quota_exhausted" and exc.auto_api_key and self._auto_issued_api_key is None:
                        self._auto_issued_api_key = exc.auto_api_key
                        headers = self._auth_headers(exc.auto_api_key)
                        continue
                    raise

            # 其余非 200（401/403/400/415...）直接映射错误
            self._raise_for_status(status, body, resp_headers)

        if last_error is not None:
            raise last_error
        raise AnySearchError("搜索请求重试耗尽后仍失败")

    # ─── 页面提取（MCP JSON-RPC） ─────────────────────────────────────────

    async def extract(self, url: str) -> str:
        """通过 MCP JSON-RPC 提取页面正文（markdown），截断到 extract_max_length。

        Args:
            url: 目标页面 URL（仅 http/https，长度不超过 MAX_URL_LEN）。

        Returns:
            截断后的 markdown 文本。

        Raises:
            AnySearchError: URL 非法、响应格式无效、MCP 返回 error；非 200 映射为对应子类。
        """
        # 边界校验：非法协议/超长 URL 直接拒绝（不发送请求）
        try:
            scheme = urllib.parse.urlparse(url).scheme
        except ValueError:
            raise AnySearchError("URL 格式非法") from None
        if scheme not in ("http", "https"):
            raise AnySearchError(f"不支持的 URL 协议: {scheme!r}，仅支持 http/https")
        if len(url) > MAX_URL_LEN:
            raise AnySearchError(f"URL 长度超出限制（{len(url)} > {MAX_URL_LEN}）")

        endpoint = f"{self._api_base}{MCP_ENDPOINT}"
        headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._auto_issued_api_key or self._api_key:
            headers["Authorization"] = f"Bearer {self._auto_issued_api_key or self._api_key}"

        call_payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "extract", "arguments": {"url": url}},
        }
        # initialize 载荷（MCP 协议版本固定 2025-03-26）
        initialize_payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "astrbot_plugin_anysearch_x", "version": "2.0.0"},
            },
        }

        body: dict = {}
        for payload in (initialize_payload, call_payload):
            async with await self._session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=EXTRACT_TIMEOUT_SEC),
            ) as resp:
                body = await self._parse_json(resp)
                if resp.status != 200:
                    self._raise_for_status(resp.status, body, resp.headers)
                error = body.get("error")
                if error:
                    raise AnySearchError(str(error.get("message") or "MCP 调用失败"))

        content_items = (body.get("result") or {}).get("content") or []
        text_parts = [item.get("text", "") for item in content_items if item.get("type") == "text"]
        return "".join(text_parts)[: self._extract_max_length]

    # ─── 内部工具 ─────────────────────────────────────────────────────────

    @staticmethod
    def _auth_headers(api_key: str) -> dict[str, str]:
        """构建鉴权请求头；api_key 为空时返回空字典（匿名模式）。"""
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def _parse_json(self, resp) -> dict:
        """解析响应 JSON；解析失败统一抛 AnySearchError。"""
        try:
            body = await resp.json()
        except (aiohttp.ContentTypeError, ValueError):
            raise AnySearchError("服务器返回了无效的响应格式") from None
        return body

    @staticmethod
    def _parse_retry_after(body: dict, headers) -> float | None:
        """解析建议重试秒数：优先 body.data.retry_after，回退 Retry-After 响应头。"""
        data = body.get("data") or {}
        raw = data.get("retry_after")
        if raw is None and headers:
            raw = headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def _retry(self, attempt: int, retry_after: float | None) -> None:
        """指数退避等待：2**attempt + 抖动；有 retry_after 时至少等待其秒数。"""
        if attempt >= MAX_EXTRA_ATTEMPTS:
            return
        if self._retry_callback is not None:
            self._retry_callback()
        await asyncio.sleep(max(2 ** attempt + random.uniform(0, 1), retry_after or 0))

    @staticmethod
    def _raise_for_status(status: int, body: dict, headers=None) -> None:
        """将非 200 响应映射为对应的 AnySearch 异常（总是抛出，不返回）。"""
        message = str(body.get("message") or f"HTTP {status}")
        symbol = body.get("symbol")

        # 认证失败：401 无效 Key；403 附加 symbol 提示（如 tag 受限）
        if status in (401, 403):
            if status == 403 and symbol:
                message = f"{message}（symbol: {symbol}）"
            raise AnySearchAuthError(message)

        # 配额耗尽：daily_free 携带自动 Key（供调用方换 Key 恢复）
        if status == 402:
            data = body.get("data") or {}
            auto_api_key = data.get("api_key") if symbol == "daily_free_quota_exhausted" else None
            raise AnySearchQuotaExhaustedError(message, symbol=symbol, auto_api_key=auto_api_key)

        # 限流：携带权威 retry_after 与配额信息，供调用方决策
        if status == 429:
            data = body.get("data") or {}
            raise AnySearchRateLimitError(
                message,
                retry_after=AnySearchClient._parse_retry_after(body, headers),
                limit=data.get("limit"),
                remaining=data.get("remaining"),
                reset_at=data.get("reset_at"),
            )

        raise AnySearchAPIError(
            status,
            message,
            symbol=symbol,
            retry_after=AnySearchClient._parse_retry_after(body, headers),
        )
