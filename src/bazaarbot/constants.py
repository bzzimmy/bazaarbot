"""Facts about Hypixel and the Bazaar that the bot relies on.

Durations are in seconds.
"""

import re
from typing import Final

# --- Rate limits ---

# Sustained commands and chat faster than about one per second get the connection kicked for spam;
# short bursts are tolerated, so a few may go at once.
COMMAND_INTERVAL: Final = 1.1
COMMAND_BURST: Final = 5

# Buy orders and sell offers share one global budget: 3 placements in any sliding 80 s window.
ORDER_PLACEMENTS_PER_WINDOW: Final = 3
ORDER_PLACEMENT_WINDOW: Final = 80.0

# Cancel and Flip Order clicks sent sooner than this after the previous one are silently ignored.
ORDER_MANAGE_INTERVAL: Final = 3.0

# A click sent the instant a menu (re)opens can be ignored; re-click at this interval until it lands.
CLICK_RETRY_INTERVAL: Final = 0.25

SCREEN_TIMEOUT: Final = 5.0
COMMAND_TIMEOUT: Final = 15.0  # the first /bz on a freshly joined server takes ~8 s to answer
REPLY_TIMEOUT: Final = 5.0

# --- Session ---

SKYBLOCK_SIDEBAR: Final = "SBScoreboard"  # sidebar objective only shown in SkyBlock
SKYBLOCK_CHECK_TIMEOUT: Final = 6.0  # Hypixel refreshes that sidebar at least every ~5 s
REJOIN_TIMEOUT: Final = 30.0
JOIN_COMMAND_DELAY: Final = 5.0  # commands only work 4 s after the profile loads on a new server
RESTART_TIMEOUT: Final = 120.0  # Hypixel moves players off a restarting server about 60 s after announcing it
PURSE_UPDATE_DELAY: Final = 2.0  # the sidebar purse shows a trade about a second after it happens
AFK_NUDGE_INTERVAL: Final = 300.0  # Hypixel moves players to a lobby after ~15 min without movement

# --- Bazaar limits ---

MAX_ORDERS: Final = 28  # 14 base + 14 from Bazaar Flipper II
MAX_UNIT_PRICE: Final = 500_000_000
BUY_ORDER_MIN_PRICE_RATIO: Final = 0.5  # of the best buy order
SELL_OFFER_MAX_PRICE_RATIO: Final = 1.5  # of the best sell offer
INSTANT_BUY_QUOTE_MARGIN: Final = 0.04  # quoted above price, difference refunded
SELL_TAX: Final = 0.01125  # measured on this account (Bazaar Flipper II); Hypixel's "Sold ..." amounts are before tax

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
CANNOT_AFFORD: Final = re.compile(r"^\[Bazaar\] You cannot afford this")
NO_SPACE: Final = re.compile(r"^\[Bazaar\] You don't have (the|enough inventory) space")
NOTHING_TO_CLAIM: Final = re.compile(r"^\[Bazaar\] There is nothing to claim!")

LIMBO: Final = re.compile(r"^You were spawned in Limbo\.")
PROFILE_LOADED: Final = re.compile(r"^You are playing on profile:")
SERVER_REBOOT: Final = re.compile(r"This server will restart soon")
