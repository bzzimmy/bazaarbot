"""Bazaar market data from Hypixel's public API: live snapshots, recording, and reading recordings back.

A snapshot is the API payload, {"lastUpdated": ms, "products": {product_id: {...}}}. Per product:
    buy_summary   sell offers, cheapest first (what an instant buy pays)
    sell_summary  buy orders, highest first (what an instant sell receives)
    quick_status  totals and weekly volumes
Hypixel names the two summaries after the instant trade, which is easy to mix up, so use best_bid and best_ask.

Run `uv run bazaarbot-market` to record continuously.
"""

import asyncio
import gzip
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx

from bazaarbot.constants import BAZAAR_API_REFRESH, BAZAAR_API_URL, ITEMS_API_URL
from bazaarbot.parsing import derived_name, plain

MARKET_DIR = Path("data/market")

log = logging.getLogger(__name__)


async def fetch() -> dict:
    """The current market snapshot."""
    async with httpx.AsyncClient(timeout=10) as client:
        return await _get(client, BAZAAR_API_URL)


async def product_names() -> dict[str, str]:
    """Bazaar product ID -> display name, as typed into /bz.

    Names come from Hypixel's item list; products it leaves out (enchantments, shards, essences, ...)
    get a name derived from their ID.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        items = (await _get(client, ITEMS_API_URL))["items"]
        products = (await _get(client, BAZAAR_API_URL))["products"]
    names = {item["id"]: plain(item["name"]) for item in items}
    return {product: names.get(product) or derived_name(product) for product in products}


def best_bid(snapshot: dict, product: str) -> float | None:
    """Highest buy order price."""
    orders = snapshot["products"][product]["sell_summary"]
    return orders[0]["pricePerUnit"] if orders else None


def best_ask(snapshot: dict, product: str) -> float | None:
    """Lowest sell offer price."""
    offers = snapshot["products"][product]["buy_summary"]
    return offers[0]["pricePerUnit"] if offers else None


async def record(directory: Path = MARKET_DIR, interval: float = BAZAAR_API_REFRESH) -> None:
    """Append every new snapshot to <directory>/<UTC date>.jsonl.gz, forever."""
    directory.mkdir(parents=True, exist_ok=True)
    last_updated = None
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                snapshot = await _get(client, BAZAAR_API_URL)
            except httpx.HTTPError as e:
                log.warning("fetch failed: %r", e)
            else:
                if snapshot["lastUpdated"] != last_updated:
                    last_updated = snapshot["lastUpdated"]
                    day = datetime.fromtimestamp(last_updated / 1000, UTC).strftime("%Y-%m-%d")
                    # Each append is its own gzip member; gzip.open reads them back as one stream.
                    with gzip.open(directory / f"{day}.jsonl.gz", "at", encoding="utf-8") as f:
                        f.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
                    log.info("recorded snapshot from %s", datetime.fromtimestamp(last_updated / 1000, UTC).isoformat())
            await asyncio.sleep(interval)


def read(path: str | Path = MARKET_DIR) -> Iterator[dict]:
    """Recorded snapshots in time order, from one file or every file in a directory."""
    path = Path(path)
    for file in sorted(path.glob("*.jsonl.gz")) if path.is_dir() else [path]:
        with gzip.open(file, "rt", encoding="utf-8") as f:
            try:
                for line in f:
                    yield json.loads(line)
            except (EOFError, json.JSONDecodeError):
                pass  # last snapshot was cut off mid-write


async def _get(client: httpx.AsyncClient, url: str) -> dict:
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    data.pop("success", None)
    return data


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(record())
