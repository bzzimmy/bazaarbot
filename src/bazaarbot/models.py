"""Data returned by the Bazaar API, and the errors it raises."""

from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Level:
    """One price level of the order book."""

    price: float
    amount: int
    orders: int


@dataclass(frozen=True)
class ProductPage:
    """A product's Bazaar page, read live from the game (fresher than the public API)."""

    product: str
    name: str
    buy_orders: list[Level]  # highest first; an instant sell fills these
    sell_offers: list[Level]  # lowest first; an instant buy fills these
    in_inventory: int

    @property
    def best_bid(self) -> float | None:
        return self.buy_orders[0].price if self.buy_orders else None

    @property
    def best_ask(self) -> float | None:
        return self.sell_offers[0].price if self.sell_offers else None


@dataclass(frozen=True)
class Order:
    """One of our orders, as listed in Manage Orders."""

    side: Side
    product: str
    name: str
    amount: int
    filled: int  # approximate for large orders, which Hypixel abbreviates ("71.7k")
    unit_price: float
    claimable: bool  # items or coins are waiting to be claimed
    slot: int  # only valid for the menu it was read from

    @property
    def is_filled(self) -> bool:
        return self.filled >= self.amount


@dataclass(frozen=True)
class Receipt:
    """Hypixel's confirmation of an action. Fields Hypixel doesn't mention are None."""

    message: str
    product: str | None = None  # display name, as Hypixel writes it
    amount: int | None = None
    coins: float | None = None  # spent, earned, refunded, or expected profit for a flip


class BazaarError(Exception):
    """Hypixel refused an action or replied with something unexpected."""


class OrderCooldown(BazaarError):
    pass


class DailyLimit(BazaarError):
    pass


class CannotAfford(BazaarError):
    pass


class NoSpace(BazaarError):
    pass


class PriceWarning(BazaarError):
    """Hypixel asks to confirm an instant sale far below the 7-day average."""
