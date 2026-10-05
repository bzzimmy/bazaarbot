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

- **capture**: records network traffic to `captures/*.jsonl`. This is how we learned the Bazaar's menus, and we'll keep using it to learn new ones. Filtered by default, with `/bbmark` labels and `/bbcapture off|filtered|all`.
- **bridge**: a lean local WebSocket. It streams the same filtered events live (screens, slot contents, chat, sidebar, tab list) and accepts a handful of primitive commands: send a command, click a slot, submit a sign, close the screen, select a hotbar slot, use the held item.

### The Python package (`src/bazaarbot`)

All Bazaar knowledge lives here, so iterating never requires rebuilding the mod.

- **Bridge client**: connects to the mod, sends primitives and receives events.
- **Game state**: purse, inventory, sacks, open screen and Booster Cookie status, built from the event stream.
- **Bazaar API**: search and product pages; instant buy and sell; sell inventory and sell sacks; create buy orders and sell offers; list, claim, cancel and flip orders; Bazaar history.
- **Market data**: the public Hypixel Bazaar API (full order books for every product, refreshed about every 20 s), recorded to `data/market/<date>.jsonl.gz`. It's used for prices; the game client is used for actions and our own orders.
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
- Instant buys quote 4% above the price and refund the difference.
- Prices are bounded: buy orders at least 50% of the best order, sell offers at most 1.5× the best offer, and 500M coins maximum per unit.
- Claims fail when the inventory is full.
- Cancelling is blocked while an order has goods waiting to be claimed.
- A sell offer always lists every unit of that product in the inventory.
- Preset amount buttons depend on stack size ("Buy only one!" for unstackable items, "Buy a stack!" otherwise), so the API uses "Custom Amount" with the sign.
- Sell-side tax depends on account upgrades.

## Rate limits

Measured live on 2026-10-05, with no artificial delays between actions. The values live in `src/bazaarbot/constants.py`.

| Action | Observed limit | How it shows up |
|---|---|---|
| Placing orders (buy orders and sell offers) | **3 in any sliding 80 s window**, shared across all products. Failed attempts don't count or extend it. Best case is a burst of 3, or 1 every ~27 s (2.25/min). | `[Bazaar] Placing orders is on cooldown for up to 1 minute!` |
| Flip Order | **Not counted** in the placement budget (it worked with the budget full). About **1 per 3 s**. | Clicks sent sooner are silently ignored |
| Cancelling an order | **About 1 per 3 s** (20 cancels took 59 s) | Clicks sent sooner are silently ignored |
| Instant buy / instant sell | None hit: 10 buys in 5.6 s, alternating buy/sell at about 1 s each | None |
| Claiming | None hit: about 70 claims/min in a manual session | Only blocked by inventory space |
| Any click | A click sent the instant a menu (re)opens can be ignored | No response; re-click every ~0.25 s until the expected screen or reply arrives |
| Public Bazaar API | Data refreshes about every 20 s | None |

**Implications:**
- New orders are the scarce resource: about 2 per minute across everything.
- Repricing is a cancel (about 3 s) plus a placement, so it spends that same budget.
- Flipping a filled buy order into a sell offer is free in budget terms, which makes buy order → flip the efficient cycle.

**Daily limits** exist separately for instant buying, order creation and selling. Their size is undocumented (community reports range from 10B to 15B and higher). Each is reported as an error when hit:
- `[Bazaar] You reached the daily limit of coins you may spend on the Bazaar!` (observed, from an oversized instant buy)
- `[Bazaar] You reached the daily limit of coins you may create orders for on the Bazaar!`
- `[Bazaar] You reached the daily limit in items value that you may sell on the bazaar!`

**Stop conditions** worth recognising later: `You were spawned in Limbo.` and `[Important] This server will restart soon: Scheduled Reboot`.

## Out of scope for now

Multiple accounts, humanisation, robust recovery from disconnects, compactor automation, and backtesting. Market snapshots may be recorded so backtesting is possible later.
