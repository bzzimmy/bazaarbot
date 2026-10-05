"""Async client for the mod's WebSocket bridge.

The mod streams filtered packet events (dicts with "seq", "dir", "type", "data") and answers
requests ({"id", "op", ...}) with {"id", "ok", "result"|"error"}.
"""

import asyncio
import itertools
import json
from collections.abc import Callable
from typing import Any

import websockets

Event = dict[str, Any]
Predicate = Callable[[Event], bool]

DEFAULT_URL = "ws://127.0.0.1:7777"


class BridgeError(Exception):
    """The mod rejected a request."""


class Bridge:
    def __init__(self, url: str = DEFAULT_URL) -> None:
        self.url = url
        self._ws: websockets.ClientConnection | None = None
        self._reader: asyncio.Task | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._waiters: list[tuple[Predicate, asyncio.Future]] = []
        self._listeners: list[Callable[[Event], None]] = []

    async def connect(self) -> "Bridge":
        self._ws = await websockets.connect(self.url, max_size=None)
        self._reader = asyncio.create_task(self._read_loop())
        return self

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._reader is not None:
            await self._reader

    async def __aenter__(self) -> "Bridge":
        return await self.connect()

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # --- events ---

    def on_event(self, callback: Callable[[Event], None]) -> None:
        """Call `callback` for every event from the mod."""
        self._listeners.append(callback)

    def expect(self, predicate: Predicate) -> asyncio.Future:
        """Future resolving to the next event matching `predicate`.

        Register before triggering the action, or a fast reply can be missed.
        """
        future = asyncio.get_running_loop().create_future()
        self._waiters.append((predicate, future))
        return future

    async def wait_for(self, predicate: Predicate, timeout: float = 5.0) -> Event:
        return await asyncio.wait_for(self.expect(predicate), timeout)

    # --- requests ---

    async def request(self, op: str, **args: Any) -> Any:
        if self._ws is None:
            raise ConnectionError("not connected")
        request_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._ws.send(json.dumps({"id": request_id, "op": op, **args}))
        response = await future
        if not response["ok"]:
            raise BridgeError(response["error"])
        return response.get("result")

    async def command(self, command: str) -> None:
        await self.request("command", command=command)

    async def chat(self, message: str) -> None:
        await self.request("chat", message=message)

    async def click(self, slot: int, button: int = 0, mode: str = "PICKUP", container_id: int | None = None) -> None:
        args: dict[str, Any] = {"slot": slot, "button": button, "mode": mode}
        if container_id is not None:
            args["containerId"] = container_id
        await self.request("click", **args)

    async def sign(self, *lines: str) -> None:
        await self.request("sign", lines=list(lines))

    async def close_screen(self) -> None:
        await self.request("close")

    async def hotbar(self, slot: int) -> None:
        await self.request("hotbar", slot=slot)

    async def use_item(self) -> None:
        await self.request("use")

    async def snapshot(self) -> dict[str, Any]:
        return await self.request("snapshot")

    # --- internals ---

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                if "id" in message:
                    future = self._pending.pop(message["id"], None)
                    if future is not None and not future.done():
                        future.set_result(message)
                else:
                    self._dispatch(message)
        except websockets.ConnectionClosed:
            pass
        finally:
            for future in [*self._pending.values(), *(f for _, f in self._waiters)]:
                if not future.done():
                    future.set_exception(ConnectionError("bridge disconnected"))
            self._pending.clear()
            self._waiters.clear()

    def _dispatch(self, event: Event) -> None:
        for callback in self._listeners:
            callback(event)
        remaining = []
        for predicate, future in self._waiters:
            if future.done():
                continue
            if predicate(event):
                future.set_result(event)
            else:
                remaining.append((predicate, future))
        self._waiters = remaining
