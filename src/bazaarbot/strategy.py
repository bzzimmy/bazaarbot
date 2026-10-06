"""Strategies: a small base class, a loader for strategy files, and the runner.

A strategy lives in its own file under strategies/ and subclasses Strategy. Class attributes are its
settings, and can be overridden when it's loaded:

    class Example(Strategy):
        amount = 64

        async def tick(self, bz, market):
            ...

    uv run bazaarbot-run strategies/example.py amount=1 duration=900
"""

import ast
import asyncio
import importlib.util
import logging
import sys
from contextlib import closing
from pathlib import Path

import httpx

from bazaarbot import market as market_api
from bazaarbot.bazaar import Bazaar
from bazaarbot.bridge import BridgeError
from bazaarbot.constants import BAZAAR_API_REFRESH, PURSE_UPDATE_DELAY
from bazaarbot.ledger import Ledger
from bazaarbot.models import BazaarError


class Strategy:
    interval: float = BAZAAR_API_REFRESH  # seconds between ticks
    duration: float = 0  # seconds to run before stopping on its own; 0 runs until Ctrl+C

    def __init__(self, **settings: object) -> None:
        for key, value in settings.items():
            if not hasattr(self, key):
                raise TypeError(f"{type(self).__name__} has no setting {key!r}")
            setattr(self, key, value)
        self.log = logging.getLogger(type(self).__name__)

    @property
    def settings(self) -> dict[str, object]:
        """Every setting and its value: the class attributes of the strategy and its bases."""
        names = {name for cls in type(self).__mro__ for name, value in vars(cls).items() if not name.startswith("_") and not callable(value)}
        return {name: getattr(self, name) for name in sorted(names - {"settings"})}

    async def start(self, bz: Bazaar) -> None:
        """Called once before the first tick."""

    async def tick(self, bz: Bazaar, market: dict) -> None:
        """Called every `interval` seconds with a fresh market snapshot (see bazaarbot.market)."""
        raise NotImplementedError

    async def stop(self, bz: Bazaar) -> None:
        """Called once when the run ends (duration reached or Ctrl+C): the place to clean up."""


def load(path: str | Path, **settings: object) -> Strategy:
    """Create the Strategy subclass defined in a strategy file."""
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = [obj for obj in vars(module).values() if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy]
    if len(found) != 1:
        raise ValueError(f"{path} should define exactly one Strategy subclass, found {len(found)}")
    return found[0](**settings)


async def run(strategy: Strategy, ledger: Ledger) -> None:
    """Run a strategy for its duration or until cancelled, recording it as a run in the ledger.

    A failed tick is logged and the next one runs as normal.
    """
    log = strategy.log
    loop = asyncio.get_running_loop()
    end = loop.time() + strategy.duration if strategy.duration else float("inf")
    async with Bazaar(ledger=ledger) as bz:
        await strategy.start(bz)
        run_id = ledger.start_run(type(strategy).__name__, strategy.settings, bz.state.purse)
        try:
            while loop.time() < end:
                started = loop.time()
                try:
                    await strategy.tick(bz, await market_api.fetch())
                except (BazaarError, BridgeError, TimeoutError, httpx.HTTPError) as e:
                    log.warning("tick failed: %r", e)
                await asyncio.sleep(max(0.0, min(started + strategy.interval, end) - loop.time()))
            log.info("duration reached, stopping")
        finally:
            try:
                await strategy.stop(bz)
            finally:
                await asyncio.sleep(PURSE_UPDATE_DELAY)
                ledger.end_run(bz.state.purse)
                _log_summary(log, ledger.summary(run_id))


def _log_summary(log: logging.Logger, summary: dict) -> None:
    purse = "unknown" if summary["purse_change"] is None else f"{summary['purse_change']:+,.0f}"
    log.info(
        f"run done: profit {summary['profit']:+,.0f} coins in {summary['minutes']:.1f} min "
        f"over {summary['trades']} trades (purse change {purse})"
    )
    for product, coins in summary["products"].items():
        log.info(f"  {product} {coins:+,.0f}")


def main() -> None:
    """bazaarbot-run <strategy file> [setting=value ...]"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    path, *pairs = sys.argv[1:]
    settings = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        try:
            settings[key] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            settings[key] = value  # plain strings don't need quotes
    try:
        with closing(Ledger()) as ledger:
            asyncio.run(run(load(path, **settings), ledger))
    except KeyboardInterrupt:
        pass
