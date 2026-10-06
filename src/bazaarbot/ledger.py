"""A record of every Bazaar trade, grouped into strategy runs, for profit per strategy and per run.

One SQLite file, data/ledger.db:
    runs     one row per strategy run: strategy, settings, start/end time and purse
    entries  one row per action that moved coins or items: product, amount, coin change, and Hypixel's reply

A run's profit is the sum of its coin changes, taken from Hypixel's receipts. The purse change over the
run is kept alongside as a cross-check: they differ when coins moved outside the bot.
"""

import json
import sqlite3
import time
from pathlib import Path

from bazaarbot.constants import CLAIMED_COINS, SELL_TAX
from bazaarbot.models import Receipt

LEDGER_PATH = Path("data/ledger.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    strategy TEXT NOT NULL,
    settings TEXT NOT NULL,  -- JSON
    started REAL NOT NULL,  -- Unix time
    ended REAL,
    purse_start REAL,
    purse_end REAL
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES runs (id),  -- NULL outside strategy runs
    time REAL NOT NULL,
    action TEXT NOT NULL,  -- the Bazaar method, e.g. create_buy_order
    product TEXT,
    amount INTEGER,
    coins REAL NOT NULL,  -- change to the purse: negative when spent
    message TEXT NOT NULL
);
"""


class Ledger:
    def __init__(self, path: str | Path = LEDGER_PATH) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, autocommit=True)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self.run_id: int | None = None

    def close(self) -> None:
        self._db.close()

    def start_run(self, strategy: str, settings: dict, purse: float | None) -> int:
        self.run_id = self._db.execute(
            "INSERT INTO runs (strategy, settings, started, purse_start) VALUES (?, ?, ?, ?)",
            (strategy, json.dumps(settings, default=str), time.time(), purse),
        ).lastrowid
        return self.run_id

    def end_run(self, purse: float | None) -> None:
        self._db.execute("UPDATE runs SET ended = ?, purse_end = ? WHERE id = ?", (time.time(), purse, self.run_id))

    def record(self, action: str, product: str | None, receipt: Receipt) -> None:
        self._db.execute(
            "INSERT INTO entries (run_id, time, action, product, amount, coins, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.run_id, time.time(), action, product, receipt.amount, _coin_change(action, receipt), receipt.message),
        )

    def summary(self, run_id: int) -> dict:
        """Profit, purse change, trade count and profit per product for one run."""
        run = self._db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        products = self._db.execute(
            "SELECT product, SUM(coins) AS coins FROM entries WHERE run_id = ? GROUP BY product ORDER BY coins DESC", (run_id,)
        ).fetchall()
        purse_change = run["purse_end"] - run["purse_start"] if run["purse_end"] is not None and run["purse_start"] is not None else None
        return {
            "strategy": run["strategy"],
            "minutes": ((run["ended"] or time.time()) - run["started"]) / 60,
            "profit": sum(row["coins"] for row in products),
            "purse_change": purse_change,
            "trades": self._db.execute("SELECT COUNT(*) FROM entries WHERE run_id = ?", (run_id,)).fetchone()[0],
            "products": {row["product"]: row["coins"] for row in products},
        }


def _coin_change(action: str, receipt: Receipt) -> float:
    """What an action did to the purse, from Hypixel's reply."""
    coins = receipt.coins or 0.0
    if action in ("instant_buy", "create_buy_order"):  # paid, or held by Hypixel until the order fills
        return -coins
    if action in ("instant_sell", "sell_inventory", "sell_sacks"):  # Hypixel quotes these before tax
        return coins * (1 - SELL_TAX)
    if action == "claim":  # coins from a sell offer count (after tax); claimed items were paid for when ordering
        return coins if CLAIMED_COINS.search(receipt.message) else 0.0
    if action == "cancel":  # coins refunded from a buy order; refunded items have no coins
        return coins
    return 0.0  # sell offers and flips move items, not coins
