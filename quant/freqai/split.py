"""带 purge/embargo 的时间序列切分 —— 防标签泄漏（freqtrade FreqAI 方法论）。

时序机器学习回测中，标签是"未来 h 根收益"，若训练集与测试集紧邻，
训练样本的标签窗口会伸入测试期 → 泄漏。因此：
- purge:   训练集尾部剔除 horizon 行（标签窗口完整落在训练期内）
- embargo: 训练集与测试集之间再留一段缓冲（降低序列相关性影响）
"""
from __future__ import annotations

from typing import Iterator

import numpy as np


def walk_forward_windows(
    n: int,
    n_windows: int = 5,
    test_size: int | None = None,
    purge: int = 0,
    embargo: int = 0,
    min_train: int = 100,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """生成 (train_idx, test_idx) 的滚动样本外切分。

    参数
    ----
    n:          总样本数
    n_windows:  测试窗口数量
    test_size:  每个测试窗口长度（None = n / (n_windows + 1) 附近）
    purge:      训练集尾部剔除行数（通常 = 标签预测周期 horizon）
    embargo:    训练与测试之间的缓冲行数
    min_train:  训练集最小行数

    生成
    ----
    (train_idx, test_idx) 各一折；测试窗口互不重叠且时间连续。
    """
    if n_windows < 1:
        raise ValueError("n_windows 必须 >= 1")
    if test_size is None:
        test_size = max(20, int(n / (n_windows + 1)))
    test_size = max(5, int(test_size))

    starts = []
    total_test = test_size * n_windows
    if total_test > n * 0.7:
        # 测试总长不超过 70%，收缩窗口
        test_size = max(5, int(n * 0.7 / n_windows))
        total_test = test_size * n_windows
    first_test_start = n - total_test
    for k in range(n_windows):
        te_start = first_test_start + k * test_size
        te_end = te_start + test_size
        tr_end = te_start - purge - embargo
        if tr_end < min_train:
            continue
        yield np.arange(0, tr_end), np.arange(te_start, te_end)
