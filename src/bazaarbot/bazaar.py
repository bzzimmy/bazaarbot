"""The Bazaar API: every Bazaar action, driven through the game.

    async with Bazaar() as bz:
        page = await bz.product("ENCHANTED_NETHER_STALK")
        await bz.create_buy_order("ENCHANTED_NETHER_STALK", 64, page.best_bid + 0.1)

Products are Hypixel API IDs. Actions run one at a time (there's a single GUI), each leaves no menu open,
and the measured rate limits are respected automatically: placing an order waits for a free slot.
"""

import asyncio
import functools
import re
import time
from collections import deque
from dataclasses import replace

from bazaarbot import constants as c
from bazaarbot import market, parsing
from bazaarbot.bridge import DEFAULT_URL, Bridge
from bazaarbot.gui import Action, Gui, Screen
from bazaarbot.models import BazaarError, CannotAfford, DailyLimit, NoSpace, Order, OrderCooldown, ProductPage, Receipt

_ERRORS = [(c.ORDER_COOLDOWN, OrderCooldown), (c.DAILY_LIMIT, DailyLimit), (c.CANNOT_AFFORD, CannotAfford), (c.NO_SPACE, NoSpace)]
_PLACEMENT_MARGIN = 2.0  # seconds on top of the measured window, since we time replies, not the server


def _action(method):
    """Run one Bazaar action at a time and always leave the menu closed."""

    @functools.wraps(method)
    async def run(self: Bazaar, *args, **kwargs):
        async with self._lock:
            try:
                return await method(self, *args, **kwargs)
            finally:
                await self.bridge.close_screen()

    return run


class Bazaar:
    def __init__(self, url: str = DEFAULT_URL) -> None:
        self.bridge = Bridge(url)
        self.gui = Gui(self.bridge)
        self.names: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._placements: deque[float] = deque(maxlen=c.ORDER_PLACEMENTS_PER_WINDOW)
        self._last_manage = 0.0

    async def __aenter__(self) -> Bazaar:
        self.names = await market.product_names()
        await self.bridge.connect()
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
        main = await self.gui.open(lambda: self.bridge.command("bz"))
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
        await self._wait_for_placement()
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
        await self._wait_for_placement()
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
        slot = self._locate(menu, order)
        return await self._confirm(self.gui.click_slot(menu, slot), c.CLAIMED_ITEMS, c.CLAIMED_COINS, reopens=True)

    @_action
    async def cancel(self, order: Order) -> Receipt:
        """Cancel an order. Anything waiting to be claimed must be claimed first."""
        menu = await self._open_orders()
        options = await self.gui.open(self.gui.click_slot(menu, self._locate(menu, order), button=1))
        await self._wait_for_manage()
        receipt = await self._confirm(self.gui.click(options, "Cancel Order"), c.CANCELLED, reopens=True)
        self._last_manage = time.monotonic()
        return receipt

    @_action
    async def flip(self, order: Order, price: float) -> Receipt:
        """Turn a filled buy order into a sell offer at `price` each. Doesn't use the placement budget."""
        menu = await self._open_orders()
        options = await self.gui.open(self.gui.click_slot(menu, self._locate(menu, order), button=1))
        await self._wait_for_manage()
        await self.gui.open_sign(self.gui.click(options, "Flip Order"))
        receipt = await self._confirm(lambda: self.bridge.sign(f"{price:.1f}"), c.ORDER_FLIPPED, reopens=True, retry=False)
        self._last_manage = time.monotonic()
        return receipt

    # --- helpers ---

    def name(self, product: str) -> str:
        try:
            return self.names[product]
        except KeyError:
            raise BazaarError(f"no known display name for {product}") from None

    async def _open_product(self, product: str) -> Screen:
        name = self.name(product)
        screen = await self.gui.open(lambda: self.bridge.command(f"bz {name}"))
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

    async def _open_orders(self) -> Screen:
        main = await self.gui.open(lambda: self.bridge.command("bz"))
        return await self.gui.open(self.gui.click(main, "Manage Orders"))

    def _locate(self, menu: Screen, order: Order) -> int:
        """Find `order` in a freshly opened Manage Orders menu."""
        for current in self._orders(menu):
            if (current.side, current.product) == (order.side, order.product) and abs(current.unit_price - order.unit_price) < 0.05:
                return current.slot
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
        main = await self.gui.open(lambda: self.bridge.command("bz"))
        if not main.has(button) or any("anything to sell" in line for line in parsing.lore(main.item(button))):
            return []
        confirm = await self.gui.open(self.gui.click(main, button))
        first = await self._confirm(self.gui.click(confirm, "Selling whole inventory"), c.SOLD, reopens=True)
        rest = [parsing.receipt(line, m) for line in self.gui.more_replies() if (m := c.SOLD.search(line))]
        return [first, *rest]

    async def _wait_for_placement(self) -> None:
        if self.placements_available() == 0:
            await asyncio.sleep(self._placements[0] + c.ORDER_PLACEMENT_WINDOW + _PLACEMENT_MARGIN - time.monotonic())

    async def _wait_for_manage(self) -> None:
        await asyncio.sleep(max(0.0, self._last_manage + c.ORDER_MANAGE_INTERVAL - time.monotonic()))
