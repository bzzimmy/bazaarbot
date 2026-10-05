# BazaarBot

## Vision

A fast, programmable interface to the Hypixel SkyBlock Bazaar. It's a Python API that can do everything a player can do in the Bazaar, plus a minimal CLI, so automated trading and flipping strategies can be written and tested as plain Python files.

It's built for one account and kept deliberately small. The Bazaar has a limited set of actions, and the code should stay as lean as that.

## How it fits together

```
 Strategies (one .py each)      CLI (Typer)
            \                      /
             Python API  (src/bazaarbot)
            /            |            \
   Bridge client    Market data     Ledger
        |          (Hypixel API)   (SQLite)
   WebSocket (localhost)
        |
   Fabric mod in a headless 26.2 client (HeadlessMC)
        |
   Hypixel SkyBlock
```

### The mod (`mod/`)

A client-side Fabric mod for Minecraft 26.2, running headless through HeadlessMC. It's a thin remote control: it knows nothing about the Bazaar.

- **capture**: records network traffic to `captures/*.jsonl`. This is how we learned the Bazaar's menus, and we'll keep using it to learn new ones. Filtered by default, with `/bbmark` labels and `/bbcapture all|filtered`.
- **bridge**: a lean local WebSocket. It streams the same filtered events live (screens, slot contents, chat, sidebar, tab list) and accepts a handful of primitive commands: send a command, click a slot, submit a sign, close the screen, select a hotbar slot, use the held item.

### The Python package (`src/bazaarbot`)

All Bazaar knowledge lives here, so iterating never requires rebuilding the mod.

- **Bridge client**: connects to the mod, sends primitives and receives events.
- **Game state**: purse, inventory, sacks, open screen and Booster Cookie status, built from the event stream.
- **Bazaar API**: search and product pages; instant buy and sell; sell inventory and sell sacks; create buy orders and sell offers; list, claim, cancel and flip orders; Bazaar history.
- **Market data**: the public Hypixel Bazaar API (full order books for every product, refreshed about once a minute). It's used for prices; the game client is used for actions and our own orders.
- **Ledger**: a SQLite record of every trade and purse snapshot, giving profit per strategy.
- **Strategies**: one file per strategy, built on a small base class and loaded by a runner.
- **CLI**: a thin Typer layer over the API for manual use and running strategies.

## Principles

- **Thin mod, smart Python.** The mod moves bytes and clicks; Python decides.
- **One action at a time.** There's a single GUI, so every Bazaar action goes through one queue. Strategies ask the API, and they never touch the GUI directly.
- **Trust what the server says.** An action has succeeded when Hypixel's chat reply or the resulting screen confirms it, not when the click was sent.
- **Find buttons by name, not by slot.** Layouts differ between screens (cancel is slot 11 for buy orders but slot 13 for sell offers), and menu titles get cut off.
- **Captures are the reference.** New behaviour is learned by capturing it first.
- **Simple first.** Error recovery, humanisation and extra tooling come later, when they're needed.

## Bazaar constraints to design around

- A Booster Cookie is required to use `/bz` remotely.
- There are 28 order slots with Bazaar Flipper II (14 without it).
- There's a daily coin limit. Its size is unclear, so the API reports it as an error rather than predicting it.
- Instant buys quote 4% above the price and refund the difference.
- Claims fail when the inventory is full.
- Cancelling is blocked while an order has goods waiting to be claimed.
- Sell-side tax depends on account upgrades.

## Out of scope for now

Multiple accounts, humanisation, robust recovery from disconnects, compactor automation, and backtesting. Market snapshots may be recorded so backtesting is possible later.
