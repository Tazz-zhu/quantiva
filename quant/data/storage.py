"""?? SQLite ??????"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from quant.data.fetcher import OHLCV_COLUMNS


class SQLiteStorage:
    """??? K ????? (symbol, timeframe, timestamp) ???"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol    TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL,
                volume    REAL,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
            """
        )
        self.conn.commit()

    def save_ohlcv(self, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        rows = [
            (symbol, timeframe, int(ts.timestamp() * 1000), *row)
            for ts, row in df[OHLCV_COLUMNS].iterrows()
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def load_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        sql = (
            "SELECT timestamp, open, high, low, close, volume "
            "FROM ohlcv WHERE symbol = ? AND timeframe = ?"
        )
        params: list = [symbol, timeframe]
        if start is not None:
            sql += " AND timestamp >= ?"
            params.append(int(pd.Timestamp(start).timestamp() * 1000))
        if end is not None:
            sql += " AND timestamp <= ?"
            params.append(int(pd.Timestamp(end).timestamp() * 1000))
        sql += " ORDER BY timestamp"
        df = pd.read_sql_query(sql, self.conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.set_index("timestamp")[OHLCV_COLUMNS]

    def close(self) -> None:
        self.conn.close()
