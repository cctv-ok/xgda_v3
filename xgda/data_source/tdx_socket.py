"""TDX L2 实时盘口接入抽象层。

设计原则
--------
1. **不解析加密的 .dat 配置文件**（nbcomte.dat 等），它们由通达信客户端内部
   `TdxAsioComm64.dll` 处理，本模块只走"客户端已通行情"的 API。
2. 提供 `L2QuoteFetcher` 抽象基类 + `NoopL2Fetcher` 默认实现，
   真实接入由 cctv 自己决定是 pytdx / mootdx / eltdx 哪一种。
3. 所有公开方法可被 mock，便于单测覆盖（见 tests/test_l2_verify.py）。

工作链路
--------
通达信客户端启动 → 通过 nbcomte.dat 配置接入通用 L2 站点 → 拉十档 / 逐笔 /
集合竞价数据 → 缓存到客户端进程 → XGDA 通过其提供的接口（默认 7709 TCP）
读取。**XGDA 不直接 dial 通用 L2 站点**，避免绕过客户端的合规问题。
"""
from __future__ import annotations

import abc
import socket
from dataclasses import dataclass, asdict
from datetime import datetime, time
from typing import Iterable, List, Optional


# ===================== 数据结构 =====================


@dataclass
class L2Quote:
    """L2 实时盘口单标的快照。

    字段全部为可选；取值不可用时保持 None，由调用方判定 unknown。
    """

    code: str
    name: str = ""
    # 时间戳
    quote_time: Optional[datetime] = None
    # 十档买卖
    bid1_price: Optional[float] = None
    bid1_volume: Optional[int] = None
    bid2_price: Optional[float] = None
    bid2_volume: Optional[int] = None
    bid3_price: Optional[float] = None
    bid3_volume: Optional[int] = None
    bid4_price: Optional[float] = None
    bid4_volume: Optional[int] = None
    bid5_price: Optional[float] = None
    bid5_volume: Optional[int] = None
    ask1_price: Optional[float] = None
    ask1_volume: Optional[int] = None
    ask2_price: Optional[float] = None
    ask2_volume: Optional[int] = None
    ask3_price: Optional[float] = None
    ask3_volume: Optional[int] = None
    ask4_price: Optional[float] = None
    ask4_volume: Optional[int] = None
    ask5_price: Optional[float] = None
    ask5_volume: Optional[int] = None
    # 集合竞价 (09:15-09:25)
    call_auction_match_price: Optional[float] = None
    call_auction_match_volume: Optional[int] = None
    call_auction_unmatched_volume: Optional[int] = None
    # 状态
    is_call_auction: bool = False
    is_suspended: bool = False
    unknown: bool = True  # 默认未知，真实数据落地后置 False

    def total_bid_volume(self, n: int = 5) -> int:
        vols = [getattr(self, f"bid{i}_volume") for i in range(1, n + 1)]
        return sum(v or 0 for v in vols)

    def total_ask_volume(self, n: int = 5) -> int:
        vols = [getattr(self, f"ask{i}_volume") for i in range(1, n + 1)]
        return sum(v or 0 for v in vols)

    def spread(self) -> Optional[float]:
        if self.ask1_price is None or self.bid1_price is None:
            return None
        return self.ask1_price - self.bid1_price

    def bid_ask_ratio(self, n: int = 5) -> Optional[float]:
        b = self.total_bid_volume(n)
        a = self.total_ask_volume(n)
        if a == 0:
            return None
        return b / a

    def to_dict(self) -> dict:
        return asdict(self)


# ===================== 抽象基类 =====================


class L2QuoteFetcher(abc.ABC):
    """L2 实时盘口抓取器抽象接口。

    实现方负责处理：
        - 与通达信客户端 / 第三方 L2 数据源的会话管理
        - 单标的拉取与批量拉取
        - 不可用时的降级（unknown=True）

    XGDA 默认用 NoopL2Fetcher，不依赖任何外部网络。
    """

    @abc.abstractmethod
    def connect(self, timeout: float = 5.0) -> bool:
        """建立会话。失败返回 False。"""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """关闭会话。"""

    @abc.abstractmethod
    def fetch(self, code: str) -> L2Quote:
        """拉单个标的 L2 快照。"""

    def fetch_many(self, codes: Iterable[str]) -> List[L2Quote]:
        """批量拉取，默认逐个调 fetch。"""
        return [self.fetch(c) for c in codes]


# ===================== 默认实现：Noop =====================


class NoopL2Fetcher(L2QuoteFetcher):
    """什么也不做，返回 unknown=True 的占位 L2Quote。

    适用场景：
        - 通达信客户端未启动
        - 测试环境
        - 用户未配置 L2 站点
    """

    def connect(self, timeout: float = 5.0) -> bool:
        return True

    def disconnect(self) -> None:
        return None

    def fetch(self, code: str) -> L2Quote:
        return L2Quote(code=code, unknown=True)


# ===================== Tcp L2 fetcher（stub，不实现私有协议） =====================


class TcpL2Fetcher(L2QuoteFetcher):
    """通过 TCP 接入（占位 stub）。

    ⚠️ **本类不实现具体私有协议**——
    TDX 的 L2 协议涉及内部二进制帧解析，cctv 应在此基础上自行接入
    pytdx / mootdx / eltdx 等开源库实现 `fetch()` 内的拼包 / 解包逻辑。

    本类只负责：
        1. TCP 连接管理（含 5xx 重连 try-once）
        2. 心跳/超时控制
        3. 失败降级为 unknown

    示例（在子类中实现 _send_recv_protocol）：

        >>> class MyFetcher(TcpL2Fetcher):
        ...     def _send_recv_protocol(self, code: str) -> dict:
        ...         # 调用 pytdx / mootdx / 自实现协议
        ...         return {"bid1_price": 10.5, "bid1_volume": 1000, ...}
        ...
        >>> f = MyFetcher(host="127.0.0.1", port=7709)
        >>> f.connect()
        >>> q = f.fetch("000001")
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 7709  # TDX 客户端对外暴露的标准端口（cctv 已用通达信客户端进程提供）

    def __init__(self,
                 host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT,
                 connect_timeout: float = 5.0,
                 recv_timeout: float = 3.0):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.recv_timeout = recv_timeout
        self._sock: Optional[socket.socket] = None
        self._last_err: Optional[str] = None

    def connect(self, timeout: float = 5.0) -> bool:
        """建立单次 TCP 连接。"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.host, self.port))
            self._sock = sock
            self._last_err = None
            return True
        except (socket.error, OSError) as e:
            self._last_err = f"{type(e).__name__}: {e}"
            self._sock = None
            return False

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def is_connected(self) -> bool:
        return self._sock is not None

    def last_error(self) -> Optional[str]:
        return self._last_err

    def fetch(self, code: str) -> L2Quote:
        """拉单只标的。失败时降级返回 unknown=True。"""
        if not self.is_connected():
            ok = self.connect(self.connect_timeout)
            if not ok:
                return L2Quote(code=code, unknown=True)
        try:
            raw = self._send_recv_protocol(code)
        except (socket.error, OSError, TimeoutError) as e:
            self._last_err = f"{type(e).__name__}: {e}"
            self.disconnect()
            return L2Quote(code=code, unknown=True)
        if raw is None:
            return L2Quote(code=code, unknown=True)
        return self._parse(code, raw)

    def fetch_many(self, codes: Iterable[str]) -> List[L2Quote]:
        """批量拉取，沿用单连接。子类可重写以实现单次请求多标的。"""
        return super().fetch_many(codes)

    # --------- 子类重写区 ---------

    def _send_recv_protocol(self, code: str):  # pragma: no cover
        """子类须实现：与 L2 服务端进行一次请求-响应，返回原始 dict 或 None。

        默认抛 NotImplementedError，提醒实现方。XGDA 不内置私有协议解析。
        """
        raise NotImplementedError(
            "TcpL2Fetcher._send_recv_protocol 须由子类实现；"
            "请基于 pytdx/mootdx/eltdx 等开源库填充具体协议。"
        )

    def _parse(self, code: str, raw: dict) -> L2Quote:
        """子类可重写协议字段映射；默认按 L2Quote 字段名直接拷。"""
        q = L2Quote(code=code, unknown=False)
        for key, val in raw.items():
            if hasattr(q, key):
                setattr(q, key, val)
        # 时间戳默认填充当前（子类可覆写从协议拿）
        if q.quote_time is None:
            q.quote_time = datetime.now()
        return q


# ===================== 工厂与便捷函数 =====================


def make_l2_fetcher(kind: str = "noop", **kwargs) -> L2QuoteFetcher:
    """按 kind 构造 fetcher。

    Args:
        kind: "noop" / "tcp"
        kwargs: 透传给具体 fetcher
    """
    kind = kind.lower()
    if kind == "noop":
        return NoopL2Fetcher()
    if kind == "tcp":
        return TcpL2Fetcher(**kwargs)
    raise ValueError(
        f"未知 l2 fetcher kind={kind!r}，可选：noop / tcp"
    )


def is_call_auction_now(now: Optional[datetime] = None) -> bool:
    """判断当前是否在集合竞价时段 (09:15:00-09:25:00)。"""
    now = now or datetime.now()
    t = now.time()
    return time(9, 15) <= t <= time(9, 25)


__all__ = [
    "L2Quote",
    "L2QuoteFetcher",
    "NoopL2Fetcher",
    "TcpL2Fetcher",
    "make_l2_fetcher",
    "is_call_auction_now",
]
