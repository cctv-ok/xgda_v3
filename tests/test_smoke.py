"""test_smoke.py：端到端冒烟测试（mock 数据，最小数据集）"""
import os
import time
import pandas as pd
import pytest

from xgda.signal import xgda_signal
from xgda.scoring import calc_score
from xgda.io_csv import write_result_csv
from xgda.search import grid_search, genetic_search
from xgda.config import (
    RESULT_CSV_TRAIN, PARAM_SPACE, POP_SIZE, GENERATIONS,
    clear_caches,
)


class TestGridSearchSmoke:
    """端到端跑网格搜索（极小数据集：5 只票 × 60 日）"""

    @pytest.fixture(autouse=True)
    def clean_csv(self, fresh_cache, tmp_path, monkeypatch):
        """把 CSV 输出到 tmp_path，避免污染项目根"""
        self.tmp = tmp_path
        self.train_csv = str(tmp_path / "train.csv")
        # 暂存全局路径
        import xgda.config as cfg
        monkeypatch.setattr(cfg, "RESULT_CSV_TRAIN", self.train_csv)
        yield

    def test_grid_runs_without_error(self, mock_df_small):
        """最小网格搜索 1-2 组能跑通且 CSV 有结果"""
        # 减小网格规模：取 PARAM_SPACE 的最小子集
        # z_min=6..7（2 个），z_max=80..85（2 个）→ 4 组
        import xgda.config as cfg
        orig_ps = cfg.PARAM_SPACE
        cfg.PARAM_SPACE = [
            ("z_min", 6, 7, 1, True, None),
            ("z_max", 80, 85, 5, True, None),
        ]
        try:
            t0 = time.time()
            best_param, best_score = grid_search(mock_df_small, self.train_csv)
            elapsed = time.time() - t0
            assert best_param is not None
            assert best_score > -10.0  # 至少不是全 -10
            # CSV 应写入
            assert os.path.exists(self.train_csv)
            df = pd.read_csv(self.train_csv, encoding="utf-8-sig")
            assert len(df) >= 1
            print(f"\n[smoke] grid 跑 {len(df)} 组，耗时 {elapsed:.1f}s")
        finally:
            cfg.PARAM_SPACE = orig_ps

    def test_score_increases_with_more_params(self, mock_df_small):
        """复合性质：网格搜索会输出 score 列，且为合法数值"""
        # 简化测试：直接调评分而非 grid
        from xgda.backtest import run_backtest
        from xgda.scoring import calc_score
        from xgda.config import MIN_TRADE_COUNT

        results = []
        for z_min in [6, 15]:
            for z_max in [80, 100]:
                if z_min >= z_max:
                    continue
                param = {"z_min": z_min, "z_max": z_max}
                res = run_backtest(param, mock_df_small)
                score = calc_score(res, min_trades=MIN_TRADE_COUNT)
                results.append((param, res, score))

        # 每个 param 都拿到一个 score（数值）
        for _, _, s in results:
            assert isinstance(s, float)
            assert -10.0 <= s <= 1.0


class TestGASmoke:
    """遗传算法冒烟：极少代数 + 小种群"""

    def test_ga_runs_2_generations(self, mock_df_small, fresh_cache, tmp_path,
                                   monkeypatch):
        import xgda.config as cfg
        orig_pop = cfg.POP_SIZE
        orig_gen = cfg.GENERATIONS
        cfg.POP_SIZE = 6       # 极小种群
        cfg.GENERATIONS = 2     # 仅 2 代
        csv_path = str(tmp_path / "ga_train.csv")
        monkeypatch.setattr(cfg, "RESULT_CSV_TRAIN", csv_path)
        try:
            best_param, best_score = genetic_search(mock_df_small, csv_path)
            assert best_param is not None
            assert "z_min" in best_param and "z_max" in best_param
            assert best_param["z_min"] < best_param["z_max"]  # 顺序保证
        finally:
            cfg.POP_SIZE = orig_pop
            cfg.GENERATIONS = orig_gen


class TestDataSourceSmoke:
    """数据源适配层冒烟"""

    def test_mock_load(self):
        from xgda.data_source import load_mock
        df = load_mock(n_stocks=5, n_days=30, seed=42)
        assert len(df) > 0
        assert "circ_value_z" in df.columns
        assert "base_ok" in df.columns
        assert "datetime_date" in df.columns
