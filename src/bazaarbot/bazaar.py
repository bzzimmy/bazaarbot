"""The Bazaar API: every Bazaar action, driven through the game.

    async with Bazaar() as bz:
        page = await bz.product("ENCHANTED_NETHER_STALK")
        await bz.create_buy_order("ENCHANTED_NETHER_STALK", 64, page.best_bid + 0.1)

Products are Hypixel API IDs. Actions run one at a time (there's a single GUI), each leaves no menu open,
and the measured rate limits are respected automatically: placing an order waits for a free slot.
Before each action the player is brought back into SkyBlock if Hypixel moved it (kick, Limbo, AFK).
"""

import asyncio
import functools
import logging
import re
import time
from collections import deque
from collections.abc import Collection
from dataclasses import replace

from bazaarbot import constants as c
from bazaarbot import market, parsing
from bazaarbot.bridge import DEFAULT_URL, Bridge
from bazaarbot.gui import Action, Gui, Screen
from bazaarbot.models import BazaarError, CannotAfford, DailyLimit, NoSpace, Order, OrderCooldown, ProductPage, Receipt
from bazaarbot.state import GameState

_ERRORS = [(c.ORDER_COOLDOWN, OrderCooldown), (c.DAILY_LIMIT, DailyLimit), (c.CANNOT_AFFORD, CannotAfford), (c.NO_SPACE, NoSpace)]
_PLACEMENT_MARGIN = 2.0  # seconds on top of the measured window, since we time replies, not the server

log = logging.getLogger("bazaarbot")


def _action(method):
    """Run one Bazaar action at a time, from inside SkyBlock, and always leave the menu closed."""

    @functools.wraps(method)
    async def run(self: Bazaar, *args, **kwargs):
        async with self._lock:
            await self._ready()
            try:
                return await method(self, *args, **kwargs)
            except TimeoutError as e:
                raise BazaarError(await self._why_no_response(method.__name__)) from e
            finally:
                await self.bridge.close_screen()

    return run


class Bazaar:
    def __init__(self, url: str = DEFAULT_URL) -> None:
        self.bridge = Bridge(url)
        self.gui = Gui(self.bridge)
        self.state = GameState(self.bridge)
        self.names: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._placements: deque[float] = deque(maxlen=c.ORDER_PLACEMENTS_PER_WINDOW)
        self._last_manage = 0.0
        self._last_nudge = 0.0
        self._nudge = 2.0  # degrees; alternates direction so the view doesn't drift

    async def __aenter__(self) -> Bazaar:
        self.names = await market.product_names()
        await self.bridge.connect()
        self.state.sync(await self.bridge.snapshot())
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.bridge.close()

    def placements_available(self) -> int:
        """Orders that can be placed right now without waiting."""
        now = time.monotonic()
        recent = sum(now - t < c.ORDER_PLACEMENT_WINDOW + _PLACEMENT_MARGIN for t in self._placements)
        return c.ORDER_PLACEMENTS_PER_WINDOW - recent

    # --- reading ---

    @_action
    async def product(self, product: str) -> ProductPage:
        return replace(parsing.product_page((await self._open_product(product)).items), product=product)

    @_action
    async def orders(self) -> list[Order]:
        return self._orders(await self._open_orders())

    @_action
    async def history(self) -> list[str]:
        """Recent Bazaar activity, newest first, from the Bazaar History button."""
        main = await self._bz()
        text = "\n".join(parsing.lore(main.item("Bazaar History")))
        return [" ".join(entry.split()) for entry in text.split("\n\n") if entry.strip()]

    # --- instant trades ---

    @_action
    async def instant_buy(self, product: str, amount: int) -> Receipt:
        page = await self._open_product(product)
        menu = await self.gui.open(self.gui.click(page, "Buy Instantly"))
        confirm = await self._sign(self.gui.click(menu, "Custom Amount"), amount)
        return await self._confirm(self.gui.click(confirm, "Custom Amount"), c.BOUGHT, reopens=True)

    @_action
    async def instant_sell(self, product: str) -> Receipt:
        """Sell every unit of `product` in the inventory to the best buy orders."""
        page = await self._open_product(product)
        if parsing.product_page(page.items).in_inventory == 0:
            raise BazaarError(f"no {product} in inventory")
        return await self._confirm(self.gui.click(page, "Sell Instantly"), c.SOLD, reopens=True)

    @_action
    async def sell_inventory(self) -> list[Receipt]:
        return await self._sell_all("Sell Inventory Now")

    @_action
    async def sell_sacks(self) -> list[Receipt]:
        return await self._sell_all("Sell Sacks Now")

    # --- orders ---

    @_action
    async def create_buy_order(self, product: str, amount: int, price: float) -> Receipt:
        await self.wait_for_placement()
        page = await self._open_product(product)
        menu = await self.gui.open(self.gui.click(page, "Create Buy Order"))
        menu = await self._sign(self.gui.click(menu, "Custom Amount"), amount)
        confirm = await self._sign(self.gui.click(menu, "Custom Price"), f"{price:.1f}")
        receipt = await self._confirm(self.gui.click(confirm, "Buy Order"), c.BUY_ORDER_SETUP)
        self._placements.append(time.monotonic())
        return receipt

    @_action
    async def create_sell_offer(self, product: str, price: float) -> Receipt:
        """Offer every unit of `product` in the inventory at `price` each."""
        await self.wait_for_placement()
        page = await self._open_product(product)
        if parsing.product_page(page.items).in_inventory == 0:
            raise BazaarError(f"no {product} in inventory")
        menu = await self.gui.open(self.gui.click(page, "Create Sell Offer"))
        confirm = await self._sign(self.gui.click(menu, "Custom Price"), f"{price:.1f}")
        receipt = await self._confirm(self.gui.click(confirm, "Sell Offer"), c.SELL_OFFER_SETUP)
        self._placements.append(time.monotonic())
        return receipt

    @_action
    async def claim(self, order: Order) -> Receipt:
        menu = await self._open_orders()
        current = self._locate(menu, order)
        if not current.claimable:
            raise BazaarError("nothing to claim on this order")
        return await self._confirm(self.gui.click_slot(menu, current.slot), c.CLAIMED_ITEMS, c.CLAIMED_COINS, reopens=True)

    @_action
    async def cancel(self, order: Order) -> Receipt:
        """Cancel an order. Anything waiting to be claimed must be claimed first."""
        menu = await self._open_orders()
        current = self._locate(menu, order)
        if current.claimable:
            raise BazaarError("claim this order before cancelling it")
        options = await self.gui.open(self.gui.click_slot(menu, current.slot, button=1))
        await self._wait_for_manage()
        receipt = await self._confirm(self.gui.click(options, "Cancel Order"), c.CANCELLED, reopens=True)
        self._last_manage = time.monotonic()
        return receipt

    @_action
    async def flip(self, order: Order, price: float) -> Receipt:
        """Turn a filled buy order into a sell offer at `price` each. Doesn't use the placement budget."""
        menu = await self._open_orders()
        current = self._locate(menu, order)
        if current.side != "buy" or not current.is_filled:
            raise BazaarError("only fully filled buy orders can be flipped")
        options = await self.gui.open(self.gui.click_slot(menu, current.slot, button=1))
        await self._wait_for_manage()
        await self.gui.open_sign(self.gui.click(options, "Flip Order"))
        receipt = await self._confirm(lambda: self.bridge.sign(f"{price:.1f}"), c.ORDER_FLIPPED, reopens=True, retry=False)
        self._last_manage = time.monotonic()
        return receipt

    async def clear_orders(self, products: Collection[str] | None = None) -> list[Receipt]:
        """Claim everything claimable and cancel the rest, for all orders or only these products.

        Keeps going past orders Hypixel refuses (logged), so one problem doesn't block the rest.
        """
        receipts: list[Receipt] = []
        while orders := [o for o in await self.orders() if products is None or o.product in products]:
            cleared = 0
            for order in orders:
                try:
                    receipts.append(await (self.claim(order) if order.claimable else self.cancel(order)))
                    cleared += 1
                except BazaarError as e:
                    log.warning("could not clear %s %s order: %s", order.side, order.product, e)
            if not cleared:
                break
        return receipts

    # --- helpers ---

    async def _ready(self) -> None:
        """Be in SkyBlock with a Booster Cookie, and turn the head now and then so Hypixel doesn't see us as AFK."""
        if not await self.state.wait_for_skyblock(c.SKYBLOCK_CHECK_TIMEOUT):
            await self._rejoin()
        if self.state.cookie_active is False:
            raise BazaarError("no Booster Cookie active, so /bz is unavailable")
        if time.monotonic() - self._last_nudge > c.AFK_NUDGE_INTERVAL:
            self._nudge = -self._nudge
            await self.bridge.look(yaw=self._nudge)
            self._last_nudge = time.monotonic()

    async def _why_no_response(self, action: str) -> str:
        """Explain a timed-out action, e.g. Hypixel's warning screen for selling far below the 7-day average."""
        screen = (await self.bridge.snapshot())["screen"]
        warning = next((item for item in (screen or {}).get("items", []) if item and parsing.name(item) == "WARNING"), None)
        if warning:
            reason = next((line for line in parsing.lore(warning) if "this value" in line), "price far from its average")
            return f"{action}: Hypixel asks to confirm a price far from the 7-day average ({reason.strip()})"
        return f"{action}: no response from Hypixel"

    async def _rejoin(self) -> None:
        loaded = self.bridge.expect(
            lambda e: e["type"].endswith("system_chat") and bool(c.PROFILE_LOADED.search(parsing.plain(e["data"]["content"]["text"])))
        )
        for command in ["lobby", "play sb"] if self.state.in_limbo else ["play sb"]:
            changed = self.bridge.expect(lambda e: e["type"].endswith(("respawn", "login")))
            await self.bridge.command(command)
            await asyncio.wait_for(changed, c.REJOIN_TIMEOUT)
        await asyncio.wait_for(loaded, c.REJOIN_TIMEOUT)
        if not self.state.in_skyblock:
            raise BazaarError("could not get back into SkyBlock")
        await asyncio.sleep(c.JOIN_COMMAND_DELAY)

    def name(self, product: str) -> str:
        try:
            return self.names[product]
        except KeyError:
            raise BazaarError(f"no known display name for {product}") from None

    async def _open_product(self, product: str) -> Screen:
        name = self.name(product)
        screen = await self._bz(name)
        if not screen.has("Buy Instantly"):  # search results
            slot = next((i for i, item in enumerate(screen.items) if item and self._is(item, product)), None)
            if slot is None:
                raise BazaarError(f"{product} ({name!r}) not found in Bazaar search")
            screen = await self.gui.open(self.gui.click_slot(screen, slot))
        if not self._is(screen.items[13], product):
            raise BazaarError(f"opened {screen.title!r} instead of {product}")
        return screen

    def _is(self, item: dict, product: str) -> bool:
        """Whether a menu item is `product`: by its ID, or by name for items without one."""
        if found := parsing.item_id(item):
            return found == product
        return parsing.same_name(parsing.name(item), self.name(product))

    def _orders(self, menu: Screen) -> list[Order]:
        """Orders in a Manage Orders menu. Items without an ID (enchantments, shards...) are identified by name."""
        by_name = {parsing.alnum(name): product for product, name in self.names.items()}
        return [o if o.product else replace(o, product=by_name.get(parsing.alnum(o.name))) for o in parsing.orders(menu.items)]

    async def _bz(self, query: str = "") -> Screen:
        """Open the Bazaar, optionally searching. Commands aren't re-sent: Hypixel answers them, just slowly at times."""
        return await self.gui.open(lambda: self.bridge.command(f"bz {query}".strip()), retry=False, timeout=c.COMMAND_TIMEOUT)

    async def _open_orders(self) -> Screen:
        main = await self._bz()
        return await self.gui.open(self.gui.click(main, "Manage Orders"))

    def _locate(self, menu: Screen, order: Order) -> Order:
        """`order` as it is now in a freshly opened Manage Orders menu."""
        for current in self._orders(menu):
            if (current.side, current.product) == (order.side, order.product) and abs(current.unit_price - order.unit_price) < 0.05:
                return current
        raise BazaarError(f"order not found: {order.side} {order.product} at {order.unit_price}")

    async def _sign(self, open_editor: Action, text: object) -> Screen:
        """Open a sign editor, type `text` on its first line, and return the menu that follows."""
        await self.gui.open_sign(open_editor)
        return await self.gui.open(lambda: self.bridge.sign(str(text)), retry=False)

    async def _confirm(self, action: Action, *patterns: re.Pattern, reopens: bool = False, retry: bool = True) -> Receipt:
        """Run the confirming action and turn Hypixel's reply into a Receipt or an error."""
        reopened = self.gui.expect_open() if reopens else None
        try:
            line = await self.gui.act(action, retry=retry)
            for pattern, error in _ERRORS:
                if pattern.search(line):
                    raise error(line)
            match = next((m for p in patterns if (m := p.search(line))), None)
            if not match:
                raise BazaarError(line)
            if reopened:
                # Hypixel reopens a menu after these; wait so it can't be mistaken for the next action's menu.
                await asyncio.wait_for(asyncio.shield(reopened), c.SCREEN_TIMEOUT)
            return parsing.receipt(line, match)
        finally:
            if reopened:
                reopened.cancel()

    async def _sell_all(self, button: str) -> list[Receipt]:
        main = await self._bz()
        if not main.has(button) or any("anything to sell" in line for line in parsing.lore(main.item(button))):
            return []
        confirm = await self.gui.open(self.gui.click(main, button))
        first = await self._confirm(self.gui.click(confirm, "Selling whole inventory"), c.SOLD, reopens=True)
        rest = [parsing.receipt(line, m) for line in self.gui.more_replies() if (m := c.SOLD.search(line))]
        return [first, *rest]

    async def wait_for_placement(self) -> None:
        """Wait until an order can be placed, e.g. to price it right before placing."""
        if self.placements_available() == 0:
            await asyncio.sleep(self._placements[0] + c.ORDER_PLACEMENT_WINDOW + _PLACEMENT_MARGIN - time.monotonic())

    async def _wait_for_manage(self) -> None:
        await asyncio.sleep(max(0.0, self._last_manage + c.ORDER_MANAGE_INTERVAL - time.monotonic()))
