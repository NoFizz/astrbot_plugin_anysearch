"""AnySearch 插件的领域模型与常量定义（纯标准库，零外部依赖）。

本模块集中管理三部分内容，供 client/main 统一引用：
- 异常层级：AnySearchError 及其子类，按错误类别（认证/配额/限流/业务）区分；
- 能力 tag 目录：TAG_DIRECTORY / ALL_TAGS / CATEGORY_LABELS，
  供 advanced_search 校验与错误提示使用；
- 请求常量：端点、超时、长度上限、可重试状态码。

约定：仅 import 标准库；禁止 import 插件内其他模块（client/cache/main）。
"""

from __future__ import annotations

# ─── 异常层级 ───────────────────────────────────────────────────────────


class AnySearchError(Exception):
    """AnySearch 插件所有异常的基类。"""


class AnySearchAuthError(AnySearchError):
    """认证失败（HTTP 401/403）：API Key 无效、过期或账户被禁用。"""


class AnySearchQuotaExhaustedError(AnySearchError):
    """配额耗尽（HTTP 402）：免费额度用尽，需要更换 API Key 或等待重置。

    Args:
        message: 错误描述。
        symbol: 触发配额耗尽的 tag（如 "finance.quote"）。
        auto_api_key: 备选 API Key（配置了多 Key 轮换时使用）。
    """

    def __init__(self, message, symbol, auto_api_key=None):
        super().__init__(message)
        self.symbol = symbol
        self.auto_api_key = auto_api_key


class AnySearchRateLimitError(AnySearchError):
    """速率受限（HTTP 429）：请求频率超过配额，应按建议时间退避。

    Args:
        message: 错误描述。
        retry_after: 建议重试等待秒数（解析自 Retry-After 响应头）。
        limit: 周期内配额上限。
        remaining: 周期内剩余配额。
        reset_at: 配额重置时间（ISO 8601 字符串）。
    """

    def __init__(
        self, message, retry_after=None, limit=None, remaining=None, reset_at=None
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at


class AnySearchAPIError(AnySearchError):
    """API 业务错误（如 HTTP 400 非法请求/tag/params）。

    Args:
        status: HTTP 状态码。
        message: 错误描述。
        symbol: 触发错误的 tag，可为 None。
        retry_after: 建议重试等待秒数，可为 None。
    """

    def __init__(self, status, message, symbol=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.symbol = symbol
        self.retry_after = retry_after


# ─── 请求常量 ───────────────────────────────────────────────────────────

MAX_QUERY_LEN = 500  # 查询字符串最大长度
MAX_URL_LEN = 2048  # 提取页面的 URL 最大长度
DEFAULT_API_BASE = "https://api.anysearch.com"  # API 服务基地址
SEARCH_ENDPOINT = "/v1/search"  # 搜索接口路径
MCP_ENDPOINT = "/mcp"  # MCP 端点路径
DEFAULT_EXTRACT_MAX_LENGTH = 8000  # 页面提取内容的截断长度
EXTRACT_TIMEOUT_SEC = 30.0  # 提取接口超时（对齐 API 504 上限）
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})  # 可重试的 HTTP 状态码


# ─── 能力 tag 目录 ──────────────────────────────────────────────────────
# 格式: 类别名 -> 该类别下的能力 tag 列表（共 17 类 40 个，tag 格式为 {domain}.{sub_domain}）

TAG_DIRECTORY: dict[str, list[str]] = {
    "academic": [
        "academic.search",
        "academic.preprint",
        "academic.biomedical",
        "academic.citation",
        "academic.dataset",
    ],
    "agriculture": ["agriculture.fao"],
    "business": [
        "business.company",
        "business.jobs",
        "business.people",
        "business.trade",
    ],
    "code": [
        "code.doc",
        "code.snippet",
    ],
    "energy": [
        "energy.electricity",
        "energy.production",
    ],
    "environment": ["environment.aqi"],
    "film": ["film.torrent"],
    "finance": [
        "finance.quote",
        "finance.news",
        "finance.fundamental",
        "finance.macro",
        "finance.calendar",
        "finance.screen",
    ],
    "gaming": [
        "gaming.esports",
        "gaming.store",
    ],
    "general": ["general.general"],
    "health": [
        "health.drug",
        "health.trial",
        "health.stats",
    ],
    "ip": ["ip.global"],
    "legal": [
        "legal.case",
        "legal.statute",
        "legal.legislation",
    ],
    "resource": ["resource.image"],
    "security": [
        "security.vuln",
        "security.intel",
        "security.scan",
        "security.noise",
    ],
    "social_media": ["social_media.social_media"],
    "travel": [
        "travel.flight",
        "travel.flight_status",
    ],
}

# 类别 -> 中文显示名（用于工具描述与错误提示）
CATEGORY_LABELS: dict[str, str] = {
    "academic": "学术",
    "agriculture": "农业",
    "business": "商业",
    "code": "代码",
    "energy": "能源",
    "environment": "环境",
    "film": "影视",
    "finance": "金融",
    "gaming": "电竞",
    "general": "通用",
    "health": "医疗健康",
    "ip": "专利",
    "legal": "法律",
    "resource": "资源",
    "security": "安全",
    "social_media": "社交媒体",
    "travel": "旅行",
}

# 展平、去重并排序后的全部 tag 列表
ALL_TAGS: list[str] = sorted({tag for tags in TAG_DIRECTORY.values() for tag in tags})
TAG_COUNT = len(ALL_TAGS)
CATEGORY_COUNT = len(TAG_DIRECTORY)


# ─── 旧版域错误提示 ─────────────────────────────────────────────────────
# 从 v1 main.py 平移，仅用于将旧版域参数转换为建议 tag 的用户友好错误提示

LEGACY_DOMAIN_HINTS: dict[str, str] = {
    "finance": "finance.quote / finance.news / finance.fundamental / finance.macro",
    "academic": "academic.search / academic.preprint / academic.biomedical",
    "code": "code.doc / code.snippet",
    "legal": "legal.case / legal.statute / legal.legislation",
    "geo": "environment.aqi / energy.electricity",
    "medical": "health.drug / health.trial / health.stats",
    "cybersecurity": "security.vuln / security.intel / security.scan",
}
