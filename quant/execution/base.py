"""??????????"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Order:
    id: str
    symbol: str
    side: str  # buy / sell
    type: str  # market / limit
    amount: float
    price: float | None
    status: str
    filled: float = 0.0
    avg_price: float | None = None


class Broker(ABC):
    """?????/????????????????"""

    @abstractmethod
    def get_balance(self) -> dict:
        """??????????? {"USDT": 10000.0}?"""

    @abstractmethod
    def get_ticker(self, symbol: str) -> dict:
        """?????? {"last": .., "bid": .., "ask": ..}?"""

    @abstractmethod
    def market_order(self, symbol: str, side: str, amount: float, price: float | None = None) -> Order:
        """????price ???????????????"""

    @abstractmethod
    def get_positions(self) -> list:
        """?????????"""
