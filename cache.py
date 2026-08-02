"""cache.py — 纯逻辑 LRU + TTL 内存缓存模块。

仅依赖标准库，无任何框架/网络依赖，可独立导入与测试。
"""

import hashlib
import time
from collections import OrderedDict
from typing import Any


class SearchCache:
    """LRU + TTL 内存缓存，仅缓存成功结果。"""

    def __init__(self, ttl: int = 300, max_size: int = 128):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self.ttl = ttl
        self.max_size = max_size

    def get(self, key: str) -> Any | None:
        """读取缓存项；命中且未过期时刷新 LRU 位置并返回值，否则返回 None。"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl:
                self._cache.move_to_end(key)
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """写入缓存项；已存在则刷新 LRU 位置，超容量时驱逐最久未使用项。"""
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
