"""quant.pairlist —— 动态交易标的列表（freqtrade pairlist 移植）。

- 静态列表（StaticPairList）：使用固定配置的币种
- 成交量排序（VolumePairList）：按 24h 成交额取 Top N，实现币种轮动
- 价格过滤（PriceFilter）：剔除过贵/过便宜、流动性差的币
- 上新过滤（AgeFilter）：剔除刚上市、历史过短的币
"""
from quant.pairlist.manager import PairListManager

__all__ = ["PairListManager"]
