"""Strategies: a small base class, a loader for strategy files, and the runner.

A strategy lives in its own file under strategies/ and subclasses Strategy. Class attributes are its
settings, and can be overridden when it's loaded:

    class Example(Strategy):
        amount = 64

        async def tick(self, bz, market):
            ...

    uv run bazaarbot-run strategies/example.py amount=1
"""

import ast
import asyncio
import importlib.util
import logging
import sys
from pathlib import Path

import httpx

from bazaarbot import market as market_api
from bazaarbot.bazaar import Bazaar
from bazaarbot.bridge import BridgeError
from bazaarbot.constants import BAZAAR_API_REFRESH
from bazaarbot.models import BazaarError


class Strategy:
    interval: float = BAZAAR_API_REFRESH  # seconds between ticks

    def __init__(self, **settings: object) -> None:
        for key, value in settings.items():
            if not hasattr(self, key):
                raise TypeError(f"{type(self).__name__} has no setting {key!r}")
            setattr(self, key, value)
        self.log = logging.getLogger(type(self).__name__)

    async def start(self, bz: Bazaar) -> None:
        """Called once before the first tick."""

    async def tick(self, bz: Bazaar, market: dict) -> None:
        """Called every `interval` seconds with a fresh market snapshot (see bazaarbot.market)."""
        raise NotImplementedError

    async def stop(self, bz: Bazaar) -> None:
        """Called once when the run ends, including on Ctrl+C."""


def load(path: str | Path, **settings: object) -> Strategy:
    """Create the Strategy subclass defined in a strategy file."""
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = [obj for obj in vars(module).values() if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy]
    if len(found) != 1:
        raise ValueError(f"{path} should define exactly one Strategy subclass, found {len(found)}")
    return found[0](**settings)


async def run(strategy: Strategy) -> None:
    """Run a strategy until cancelled. A failed tick is logged and the next one runs as normal."""
    log = strategy.log
    async with Bazaar() as bz:
        await strategy.start(bz)
        try:
            while True:
                started = asyncio.get_running_loop().time()
                try:
                    await strategy.tick(bz, await market_api.fetch())
                except (BazaarError, BridgeError, TimeoutError, httpx.HTTPError) as e:
                    log.warning("tick failed: %r", e)
                await asyncio.sleep(max(0.0, strategy.interval - (asyncio.get_running_loop().time() - started)))
        finally:
            await strategy.stop(bz)


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
        asyncio.run(run(load(path, **settings)))
    except KeyboardInterrupt:
        pass
