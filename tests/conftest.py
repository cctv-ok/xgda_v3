"""pytest fixtures：mock 数据 + 临时目录 + 缓存清理"""
import os
import pytest
import numpy as np
import pandas as pd

from xgda.config import clear_caches
from xgda.data_source import load_mock


@pytest.fixture
def mock_df_small():
    """5 只票 × 60 个交易日（小数据集，速度优先）"""
    return load_mock(n_stocks=5, n_days=60, seed=42)


@pytest.fixture
def mock_df_medium():
    """10 只票 × 100 个交易日（更接近真实 backtrader 时序）"""
    return load_mock(n_stocks=10, n_days=100, seed=123)


@pytest.fixture
def fresh_cache():
    clear_caches()
    yield
    clear_caches()
