"""What the player can see outside menus: purse, Booster Cookie, and whether we're in SkyBlock.

Built purely from bridge events, so it's always current and never has to ask the game.
"""

import asyncio
import re

from bazaarbot import parsing
from bazaarbot.bridge import Bridge, Event
from bazaarbot.constants import LIMBO, SKYBLOCK_SIDEBAR

_PURSE = re.compile(r"^(?:Purse|Piggy): ([\d,.]+)")


class GameState:
    def __init__(self, bridge: Bridge) -> None:
        self.cookie_active: bool | None = None  # None until the tab list has shown it
        self.cookie_left: str | None = None  # as Hypixel shows it, e.g. "3 days, 4 hours"
        self.in_limbo = False
        self._teams: dict[str, str] = {}  # sidebar lines are scoreboard teams: name -> prefix + suffix
        self._synced_lines: list[str] = []  # sidebar at connect, until live team updates replace it
        self._skyblock = asyncio.Event()
        bridge.on_event(self._on_event)

    @property
    def in_skyblock(self) -> bool:
        return self._skyblock.is_set()

    @property
    def purse(self) -> float | None:
        """Coins in the purse, from the sidebar."""
        for line in [*self._teams.values(), *self._synced_lines]:
            if match := _PURSE.match(line):
                return parsing.number(match.group(1))
        return None

    def sync(self, snapshot: dict) -> None:
        """Seed the state from a bridge snapshot, so it's known at connect instead of after the next update."""
        sidebar = snapshot.get("sidebar") or {}
        if sidebar.get("objective") == SKYBLOCK_SIDEBAR:
            self._skyblock.set()
        self._synced_lines = [parsing.plain(line).strip() for line in sidebar.get("lines", [])]

    async def wait_for_skyblock(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._skyblock.wait(), timeout)
            return True
        except TimeoutError:
            return False

    def _on_event(self, event: Event) -> None:
        kind, data = event["type"], event.get("data", {})
        if kind.endswith(("respawn", "login")):
            # Changed server: unknown until that server's sidebar arrives.
            self._skyblock.clear()
            self._teams.clear()
            self._synced_lines = []
            self.in_limbo = False
        elif kind.endswith(("set_objective", "set_display_objective")):
            if data.get("objectiveName") == SKYBLOCK_SIDEBAR:
                self._skyblock.set()
        elif kind.endswith("set_player_team"):
            if data["method"] == 1:  # team removed
                self._teams.pop(data["name"], None)
            elif params := data.get("parameters"):
                self._teams[data["name"]] = parsing.plain(params["playerPrefix"]["text"] + params["playerSuffix"]["text"])
        elif kind.endswith("tab_list"):
            lines = [line.strip() for line in parsing.plain(data["footer"]["text"]).split("\n")]
            if "Cookie Buff" in lines:
                left = lines[lines.index("Cookie Buff") + 1]
                self.cookie_active = not left.startswith("Not active")
                self.cookie_left = left if self.cookie_active else None
        elif kind.endswith("system_chat") and LIMBO.search(parsing.plain(data["content"]["text"])):
            self.in_limbo = True
