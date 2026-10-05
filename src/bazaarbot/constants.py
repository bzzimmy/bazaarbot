"""Facts about Hypixel and the Bazaar that the bot relies on.

Durations are in seconds.
"""

import re
from typing import Final

# --- Rate limits ---

# Buy orders and sell offers share one global budget: 3 placements in any sliding 80 s window.
ORDER_PLACEMENTS_PER_WINDOW: Final = 3
ORDER_PLACEMENT_WINDOW: Final = 80.0

# Cancel and Flip Order clicks sent sooner than this after the previous one are silently ignored.
ORDER_MANAGE_INTERVAL: Final = 3.0

# A click sent the instant a menu (re)opens can be ignored; re-click at this interval until it lands.
CLICK_RETRY_INTERVAL: Final = 0.25

SCREEN_TIMEOUT: Final = 5.0
REPLY_TIMEOUT: Final = 5.0

# --- Bazaar limits ---

MAX_ORDERS: Final = 28  # 14 base + 14 from Bazaar Flipper II
MAX_UNIT_PRICE: Final = 500_000_000
BUY_ORDER_MIN_PRICE_RATIO: Final = 0.5  # of the best buy order
SELL_OFFER_MAX_PRICE_RATIO: Final = 1.5  # of the best sell offer
INSTANT_BUY_QUOTE_MARGIN: Final = 0.04  # quoted above price, difference refunded

# Every container menu ends with the player's 36 inventory slots.
PLAYER_INVENTORY_SLOTS: Final = 36

# --- Market data ---

BAZAAR_API_URL: Final = "https://api.hypixel.net/v2/skyblock/bazaar"
ITEMS_API_URL: Final = "https://api.hypixel.net/v2/resources/skyblock/items"
BAZAAR_API_REFRESH: Final = 20.0  # data changes about every 20 s

# --- Chat messages (matched against plain text with formatting codes removed) ---

_NUM = r"[\d,]+(?:\.\d+)?"

BOUGHT: Final = re.compile(rf"^\[Bazaar\] Bought (?P<amount>{_NUM})x (?P<product>.+) for (?P<coins>{_NUM}) coins!$")
SOLD: Final = re.compile(rf"^\[Bazaar\] Sold (?P<amount>{_NUM})x (?P<product>.+) for (?P<coins>{_NUM}) coins!$")
BUY_ORDER_SETUP: Final = re.compile(rf"^\[Bazaar\] Buy Order Setup! (?P<amount>{_NUM})x (?P<product>.+) for (?P<coins>{_NUM}) coins\.$")
SELL_OFFER_SETUP: Final = re.compile(rf"^\[Bazaar\] Sell Offer Setup! (?P<amount>{_NUM})x (?P<product>.+) for (?P<coins>{_NUM}) coins\.$")
ORDER_FLIPPED: Final = re.compile(
    rf"^\[Bazaar\] Order Flipped! (?P<amount>{_NUM})x (?P<product>.+) for (?P<profit>{_NUM}) coins of total expected profit\.$"
)
CANCELLED: Final = re.compile(r"^\[Bazaar\] Cancelled! Refunded (?P<refund>.+) from cancelling (?P<side>Buy Order|Sell Offer)!$")
CLAIMED_ITEMS: Final = re.compile(
    rf"^\[Bazaar\] Claimed (?P<amount>{_NUM})x (?P<product>.+) worth (?P<coins>{_NUM}) coins bought for (?P<unit_price>{_NUM}) each!$"
)
CLAIMED_COINS: Final = re.compile(
    rf"^\[Bazaar\] Claimed (?P<coins>{_NUM}) coins from selling (?P<amount>{_NUM})x (?P<product>.+) at (?P<unit_price>{_NUM}) each!$"
)
ORDER_FILLED: Final = re.compile(rf"^\[Bazaar\] Your (?P<side>Buy Order|Sell Offer) for (?P<amount>{_NUM})x (?P<product>.+) was filled!$")

# Progress lines Hypixel sends before the real reply.
PENDING: Final = re.compile(r"^\[Bazaar\] (Putting goods in escrow|Submitting|Executing|Claiming order|Cancelling order)")

ORDER_COOLDOWN: Final = re.compile(r"^\[Bazaar\] Placing orders is on cooldown")
DAILY_LIMIT: Final = re.compile(r"^\[Bazaar\] You reached the daily limit")
CANNOT_AFFORD: Final = re.compile(r"^\[Bazaar\] You cannot afford this!")
NO_SPACE: Final = re.compile(r"^\[Bazaar\] You don't have the space required")
NOTHING_TO_CLAIM: Final = re.compile(r"^\[Bazaar\] There is nothing to claim!")

LIMBO: Final = re.compile(r"^You were spawned in Limbo\.")
SERVER_REBOOT: Final = re.compile(r"This server will restart soon")
