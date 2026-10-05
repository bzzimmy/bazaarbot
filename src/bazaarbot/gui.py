"""Generic Hypixel menu handling on top of the bridge: open menus, click buttons by name, read replies.

Hypixel sometimes ignores a click sent the instant a menu (re)opens, so navigation re-sends until something
happens. That is safe because every click carries its menu's container id: once the menu changes, a late
duplicate refers to a stale id and the server drops it.
"""

import asyncio
from collections.abc import Awaitable, Callable

from bazaarbot import parsing
from bazaarbot.bridge import Bridge, Event
from bazaarbot.constants import CLICK_RETRY_INTERVAL, ORDER_FILLED, PENDING, PLAYER_INVENTORY_SLOTS, REPLY_TIMEOUT, SCREEN_TIMEOUT

Action = Callable[[], Awaitable[None]]


class Screen:
    """An open menu. Items exclude the player's inventory and stay up to date as slots change."""

    def __init__(self, gui: Gui, container_id: int, title: str) -> None:
        self._gui = gui
        self.id = container_id
        self.title = title

    @property
    def items(self) -> list[dict | None]:
        return self._gui._contents.get(self.id, [])[:-PLAYER_INVENTORY_SLOTS]

    def find(self, name: str) -> int:
        try:
            return parsing.find(self.items, name)
        except LookupError:
            raise LookupError(f"no {name!r} in {self.title!r}") from None

    def has(self, name: str) -> bool:
        return any(item and parsing.name(item) == name for item in self.items)

    def item(self, name: str) -> dict:
        return self.items[self.find(name)]


class Gui:
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self._contents: dict[int, list] = {}
        self._contents_arrived = asyncio.Event()
        self._replies: asyncio.Queue[str] = asyncio.Queue()
        bridge.on_event(self._on_event)

    def click(self, screen: Screen, name: str, button: int = 0) -> Action:
        """An action clicking the named button of `screen`."""
        slot = screen.find(name)
        return lambda: self.bridge.click(slot, button, container_id=screen.id)

    def click_slot(self, screen: Screen, slot: int, button: int = 0) -> Action:
        return lambda: self.bridge.click(slot, button, container_id=screen.id)

    def expect_open(self) -> asyncio.Future:
        return self.bridge.expect(lambda e: e["type"].endswith("open_screen"))

    async def open(self, action: Action, retry: bool = True, timeout: float = SCREEN_TIMEOUT) -> Screen:
        """Run `action` until a new menu opens, then return it once its items have arrived."""
        event = await self._until(self.expect_open(), action, retry, timeout, "menu did not open")
        container_id = event["data"]["containerId"]
        async with asyncio.timeout(timeout):
            while container_id not in self._contents:
                self._contents_arrived.clear()
                await self._contents_arrived.wait()
        return Screen(self, container_id, parsing.plain(event["data"]["title"]["text"]))

    async def open_sign(self, action: Action) -> None:
        """Run `action` until a sign editor opens."""
        editor = self.bridge.expect(lambda e: e["type"].endswith("open_sign_editor"))
        await self._until(editor, action, True, SCREEN_TIMEOUT, "sign editor did not open")

    async def act(self, action: Action, retry: bool = True) -> str:
        """Run `action` and return Hypixel's [Bazaar] reply, skipping progress lines like "Submitting...".

        Until Hypixel acknowledges with any [Bazaar] line, the click counts as ignored and is re-sent.
        """
        self._replies = asyncio.Queue()
        await action()
        acknowledged = not retry
        async with asyncio.timeout(REPLY_TIMEOUT):
            while True:
                try:
                    line = await asyncio.wait_for(self._replies.get(), None if acknowledged else CLICK_RETRY_INTERVAL)
                except TimeoutError:
                    await action()
                    continue
                if not PENDING.search(line):
                    return line
                acknowledged = True

    def more_replies(self) -> list[str]:
        """[Bazaar] lines that arrived after the reply returned by the last act()."""
        lines = []
        while not self._replies.empty():
            if not PENDING.search(line := self._replies.get_nowait()):
                lines.append(line)
        return lines

    async def _until(self, future: asyncio.Future, action: Action, retry: bool, timeout: float, error: str) -> Event:
        try:
            async with asyncio.timeout(timeout):
                await action()
                while True:
                    try:
                        return await asyncio.wait_for(asyncio.shield(future), CLICK_RETRY_INTERVAL if retry else None)
                    except TimeoutError:
                        await action()
        except TimeoutError:
            raise TimeoutError(error) from None
        finally:
            future.cancel()

    def _on_event(self, event: Event) -> None:
        kind, data = event["type"], event.get("data", {})
        if kind.endswith("open_screen"):
            self._contents.pop(data["containerId"], None)
        elif kind.endswith("container_set_content"):
            self._contents[data["containerId"]] = data["items"]
            self._contents_arrived.set()
        elif kind.endswith("container_set_slot"):
            items = self._contents.get(data["containerId"])
            if items and 0 <= data["slot"] < len(items):
                items[data["slot"]] = data["itemStack"]
        elif kind.endswith("system_chat") and not data["overlay"]:
            line = parsing.plain(data["content"]["text"]).strip()
            if line.startswith("[Bazaar]") and not ORDER_FILLED.search(line):  # fills arrive unprompted
                self._replies.put_nowait(line)
