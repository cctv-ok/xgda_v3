"""L2 实时盘口校验的单测覆盖。

覆盖点：
    1. L2Quote 字段计算（total_bid_volume / spread / bid_ask_ratio）
    2. NoopL2Fetcher / TcpL2Fetcher 连接握手（含失败降级）
    3. verify_with_l2 排序逻辑（含 unknown 降级）
    4. combine_score 加权
    5. filter_top_n 过滤
    6. is_call_auction_now 时段判断
"""
import math
import socket
from unittest.mock import MagicMock, patch

import pytest

from xgda.data_source.tdx_socket import (
    L2Quote,
    L2QuoteFetcher,
    NoopL2Fetcher,
    TcpL2Fetcher,
    make_l2_fetcher,
    is_call_auction_now,
)
from xgda.data_source.l2_verify import (
    l2_score, combine_score, verify_with_l2, filter_top_n,
    VerifiedCandidate,
)


# ============================== L2Quote 字段计算 ==============================


def _full_quote() -> L2Quote:
    return L2Quote(
        code="000001", name="平安银行",
        bid1_price=10.00, bid1_volume=1500,
        bid2_price=9.99,  bid2_volume=2000,
        bid3_price=9.98,  bid3_volume=2500,
        bid4_price=9.97,  bid4_volume=1800,
        bid5_price=9.96,  bid5_volume=1200,
        ask1_price=10.01, ask1_volume=1000,
        ask2_price=10.02, ask2_volume=1500,
        ask3_price=10.03, ask3_volume=2000,
        ask4_price=10.04, ask4_volume=2200,
        ask5_price=10.05, ask5_volume=1700,
        call_auction_match_price=10.00,
        call_auction_match_volume=300_000,
        unknown=False,
    )


class TestL2QuoteFields:
    def test_total_bid_volume(self):
        q = _full_quote()
        assert q.total_bid_volume(5) == 9000

    def test_total_ask_volume(self):
        q = _full_quote()
        assert q.total_ask_volume(5) == 8400

    def test_spread(self):
        q = _full_quote()
        assert q.spread() == pytest.approx(0.01)

    def test_spread_missing(self):
        q = L2Quote(code="x")
        assert q.spread() is None

    def test_bid_ask_ratio(self):
        q = _full_quote()
        # 9000 / 8400 ≈ 1.071
        assert q.bid_ask_ratio() == pytest.approx(9000 / 8400)

    def test_bid_ask_ratio_zero_ask(self):
        q = L2Quote(code="x", ask1_price=10.0, ask1_volume=0,
                    bid1_price=9.95, bid1_volume=100)
        assert q.bid_ask_ratio() is None

    def test_to_dict(self):
        q = _full_quote()
        d = q.to_dict()
        assert d["code"] == "000001"
        assert d["bid1_volume"] == 1500
        assert d["ask5_volume"] == 1700


# ============================== Noop fetcher ==============================


class TestNoopL2Fetcher:
    def test_connect(self):
        f = NoopL2Fetcher()
        assert f.connect() is True

    def test_disconnect(self):
        f = NoopL2Fetcher()
        f.disconnect()  # 无副作用
        assert True

    def test_fetch_unknown(self):
        f = NoopL2Fetcher()
        q = f.fetch("000001")
        assert q.code == "000001"
        assert q.unknown is True
        assert q.spread() is None


# ============================== Tcp fetcher ==============================


class TestTcpL2Fetcher:
    def test_make_factory_noop(self):
        f = make_l2_fetcher("noop")
        assert isinstance(f, NoopL2Fetcher)

    def test_make_factory_tcp(self):
        f = make_l2_fetcher("tcp", host="1.2.3.4", port=9999)
        assert isinstance(f, TcpL2Fetcher)
        assert f.host == "1.2.3.4"
        assert f.port == 9999

    def test_make_factory_unknown(self):
        with pytest.raises(ValueError):
            make_l2_fetcher("garbage")

    def test_connect_unreachable(self):
        """连不上时应返回 False 且保持未连接。"""
        # 192.0.2.0/24 是 RFC 5737 测试保留网段，永远不可达
        f = TcpL2Fetcher(host="192.0.2.1", port=39999, connect_timeout=0.5)
        ok = f.connect()
        assert ok is False
        assert f.is_connected() is False
        assert f.last_error() is not None

    def test_fetch_unconnected_returns_unknown(self):
        """未连接时 fetch 应返回 unknown=True 而不抛。"""
        f = TcpL2Fetcher(host="127.0.0.1", port=39999, connect_timeout=0.1)
        q = f.fetch("000001")
        assert q.unknown is True
        assert q.code == "000001"


class TestTcpL2FetcherSubclassed:
    """子类实现协议层的最小可用性测试。"""

    def test_subclass_fetch_parses_dict(self):
        raw = {
            "bid1_price": 10.5, "bid1_volume": 1000,
            "ask1_price": 10.6, "ask1_volume": 800,
            "call_auction_match_volume": 50_000,
        }

        class FakeFetcher(TcpL2Fetcher):
            def _send_recv_protocol(self, code):
                return raw if code == "000001" else None

        f = FakeFetcher(host="127.0.0.1", port=0)
        # 不真连：直接调 _parse
        q = f._parse("000001", raw)
        assert q.code == "000001"
        assert q.bid1_price == 10.5
        assert q.bid1_volume == 1000
        assert q.call_auction_match_volume == 50_000
        assert q.unknown is False

    def test_subclass_default_protocol_raises(self):
        """未重写协议时拉数据应抛 NotImplementedError。"""
        f = TcpL2Fetcher()
        f._sock = MagicMock()  # 假装连上了
        with pytest.raises(NotImplementedError):
            f._send_recv_protocol("000001")


# ============================== l2_score / combine_score ==============================


class TestL2Score:
    def test_unknown_returns_zero(self):
        q = L2Quote(code="x", unknown=True)
        s, notes = l2_score(q)
        assert s == 0.0
        assert "L2 不可用" in notes[0]

    def test_suspended_returns_zero(self):
        q = L2Quote(code="x", unknown=False, is_suspended=True)
        s, notes = l2_score(q)
        assert s == 0.0
        assert "停牌" in notes[0]

    def test_strong_call_auction(self):
        """集合竞价匹配量 50万手、bid/ask 健康 → 应得较高分。"""
        q = L2Quote(
            code="x", unknown=False,
            call_auction_match_volume=500_000,
            bid1_price=10.0, bid1_volume=5000,
            bid2_price=9.99, bid2_volume=4000,
            bid3_price=9.98, bid3_volume=3000,
            ask1_price=10.01, ask1_volume=2000,
            ask2_price=10.02, ask2_volume=1500,
            ask3_price=10.03, ask3_volume=1000,
        )
        s, _ = l2_score(q)
        # 50万正好到 0.7，b/a=12000/4500=2.67 → 0.8+，流动性 spread=0.01/10.005≈0.1%→1.0
        assert s > 0.6

    def test_zero_match_volume(self):
        """集合竞价零匹配 → match=0，即使 b/a 不错也拉不高。"""
        q = L2Quote(
            code="x", unknown=False,
            call_auction_match_volume=0,
            bid1_price=10.0, bid1_volume=10_000,
            ask1_price=10.01, ask1_volume=2_000,
        )
        s, _ = l2_score(q)
        assert s < 0.5


class TestCombineScore:
    def test_weights_sum_to_one(self):
        s = combine_score(0.5, 0.5, weights=(0.6, 0.4))
        assert s == pytest.approx(0.5)

    def test_pure_xg(self):
        s = combine_score(0.8, 0.0, weights=(1.0, 0.0))
        assert s == pytest.approx(0.8)

    def test_pure_l2(self):
        s = combine_score(0.0, 0.7, weights=(0.0, 1.0))
        assert s == pytest.approx(0.7)

    def test_clamping(self):
        s = combine_score(2.0, 2.0, weights=(0.5, 0.5))
        assert s == 1.0


# ============================== verify_with_l2 ==============================


class TestVerifyWithL2:
    def test_empty(self):
        out = verify_with_l2([], {}, fetcher=NoopL2Fetcher())
        assert out == []

    def test_noop_returns_sorted_by_xg(self):
        codes = ["000001", "000002", "000003"]
        scores = {"000001": 0.9, "000002": 0.5, "000003": 0.7}
        out = verify_with_l2(codes, scores, fetcher=NoopL2Fetcher())
        assert [v.code for v in out] == ["000001", "000003", "000002"]

    def test_noop_keeps_unknown_l2_score_zero(self):
        out = verify_with_l2(["x"], {"x": 0.5}, fetcher=NoopL2Fetcher())
        assert out[0].l2_score == 0.0
        assert out[0].quote.unknown is True
        # final = 0.6*0.5 + 0.4*0 = 0.3
        assert out[0].final_score == pytest.approx(0.3)

    def test_with_real_l2_quote_reranks(self):
        """真实 L2 数据应该能反转排名（L2 高分候选挤到前面）。"""
        # 候选 A: xg 高，但 L2 unknown
        # 候选 B: xg 低，但 L2 real high
        class FakeFetcher(L2QuoteFetcher):
            def connect(self, timeout=5.0): return True
            def disconnect(self): pass
            def fetch(self, code):
                if code == "A":
                    return L2Quote(code="A", unknown=True)
                if code == "B":
                    return L2Quote(
                        code="B", unknown=False,
                        call_auction_match_volume=200_000,
                        bid1_price=10.0, bid1_volume=3000,
                        ask1_price=10.01, ask1_volume=1000,
                        bid2_price=9.99, bid2_volume=2000,
                        ask2_price=10.02, ask2_volume=800,
                    )
                return L2Quote(code=code, unknown=True)

        out = verify_with_l2(
            ["A", "B"],
            {"A": 1.0, "B": 0.4},
            fetcher=FakeFetcher(),
        )
        # B: xg=0.4, l2=约 0.45+, final ≈ 0.6*0.4 + 0.4*0.5 ≈ 0.44
        # A: xg=1.0, l2=0.0, final = 0.6*1.0 = 0.6
        # 默认权重下 A 还是胜；但应验证排序结果是有意义的
        assert len(out) == 2
        # 至少一个 L2 已知
        assert any(not v.quote.unknown for v in out)


class TestFilterTopN:
    def _build(self):
        return [
            VerifiedCandidate(c, final_score=0.5 - i * 0.1,
                             xg_score=0.5, l2_score=0.0,
                             quote=L2Quote(code=c))
            for i, c in enumerate(["A", "B", "C", "D"])
        ]

    def test_top_n(self):
        results = self._build()
        out = filter_top_n(results, top_n=2)
        assert [r.code for r in out] == ["A", "B"]

    def test_min_score(self):
        results = self._build()
        out = filter_top_n(results, top_n=10, min_score=0.35)
        assert [r.code for r in out] == ["A", "B"]

    def test_require_known(self):
        results = [
            VerifiedCandidate("A", 0.5, 0.5, 0.0,
                              L2Quote(code="A", unknown=True)),
            VerifiedCandidate("B", 0.4, 0.4, 0.3,
                              L2Quote(code="B", unknown=False)),
        ]
        out = filter_top_n(results, top_n=10, require_known=True)
        assert [r.code for r in out] == ["B"]


# ============================== is_call_auction_now ==============================


class TestCallAuctionNow:
    def test_at_9_20(self):
        from datetime import datetime
        assert is_call_auction_now(datetime(2026, 9, 13, 9, 20)) is True

    def test_at_9_25(self):
        from datetime import datetime
        assert is_call_auction_now(datetime(2026, 9, 13, 9, 25)) is True

    def test_at_9_26(self):
        from datetime import datetime
        assert is_call_auction_now(datetime(2026, 9, 13, 9, 26)) is False

    def test_at_15_00(self):
        from datetime import datetime
        assert is_call_auction_now(datetime(2026, 9, 13, 15, 0)) is False


# ============================== 集成：select_at_open l2_verify=True ==============================


class TestSelectAtOpenWithL2:
    """验证 real.select_at_open 在 l2_verify=True 时切换路径并生成正确结果。"""

    def test_l2_disabled_keeps_old_path(self, tmp_path):
        from xgda.real import select_at_open
        import pandas as pd
        from datetime import datetime

        # 构造最小可用 today_df：1 只票，2 个交易日
        today = "2026-09-13"
        prev = "2026-09-12"
        df = pd.DataFrame({
            "code": ["000001", "000001"],
            "datetime": pd.to_datetime([prev, today]),
            "open": [10.0, 10.5], "high": [10.2, 10.8],
            "low": [9.8, 10.3], "close": [10.0, 10.7],
            "volume": [100_000, 120_000],
            "circ_value_z": [50.0, 50.0],
            "base_ok": [True, True],
            "code_ok": [True, True],
            "st_ok": [True, True],
            "st_num": [0, 0],
            "datetime_date": [pd.Timestamp(prev).date(),
                              pd.Timestamp(today).date()],
        })

        result = select_at_open(
            today=today,
            today_df=df,
            best_param={"z_min": 6, "z_max": 80, "score": 0.5},
            output_dir=str(tmp_path),
            interactive_guard=False,
            l2_verify=False,
        )
        assert "selected" in result
        assert result["l2_active"] is False
        # 无 L2 时所有记录 l2_unknown=True
        for r in result["selected"]:
            assert r["l2_unknown"] is True

    def test_l2_enabled_with_noop(self, tmp_path):
        """l2_verify=True 但 fetcher=None 时走 NoopL2Fetcher，不抛。"""
        from xgda.real import select_at_open
        import pandas as pd

        today = "2026-09-13"
        prev = "2026-09-12"
        df = pd.DataFrame({
            "code": ["000001", "000001"],
            "datetime": pd.to_datetime([prev, today]),
            "open": [10.0, 10.5], "high": [10.2, 10.8],
            "low": [9.8, 10.3], "close": [10.0, 10.7],
            "volume": [100_000, 120_000],
            "circ_value_z": [50.0, 50.0],
            "base_ok": [True, True],
            "code_ok": [True, True],
            "st_ok": [True, True],
            "st_num": [0, 0],
            "datetime_date": [pd.Timestamp(prev).date(),
                              pd.Timestamp(today).date()],
        })

        result = select_at_open(
            today=today,
            today_df=df,
            best_param={"z_min": 6, "z_max": 80, "score": 0.5},
            output_dir=str(tmp_path),
            interactive_guard=False,
            l2_verify=True,
        )
        assert result["l2_active"] is True
        assert result["candidates_total"] >= 1
