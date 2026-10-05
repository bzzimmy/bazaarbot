"""Pure functions that turn menu items and chat lines into data. No I/O.

Items are the dicts the mod sends: {"name", "lore", "stack": {"id", "count", "components"}}.
"""

import re

from bazaarbot.models import Level, Order, ProductPage, Receipt

_FORMATTING = re.compile("§.")
_LEVEL = re.compile(r"^- ([\d,.]+) coins each \| ([\d,]+)x (?:in|from) ([\d,]+) (?:order|offer)s?$")
_SUFFIXES = {"k": 1e3, "M": 1e6, "B": 1e9}


def plain(text: str) -> str:
    """Text with Minecraft formatting codes removed."""
    return _FORMATTING.sub("", text)


def number(text: str) -> float:
    """Parse numbers as Hypixel prints them: "1,234.5", "71.7k", "2.3M"."""
    text = text.replace(",", "").strip()
    if text and text[-1] in _SUFFIXES:
        return float(text[:-1]) * _SUFFIXES[text[-1]]
    return float(text)


def name(item: dict) -> str:
    return plain(item["name"]).strip()


def lore(item: dict) -> list[str]:
    return [plain(line) for line in item.get("lore", [])]


def item_id(item: dict) -> str | None:
    """The SkyBlock ID Hypixel stores on the item, which matches the Bazaar product ID."""
    data = item["stack"].get("components", {}).get("minecraft:custom_data", {})
    if rabbit := data.get("faction_rabbit_id"):  # stored as id "FACTION_RABBIT" plus the rabbit's name
        return f"FACTION_RABBIT_{rabbit.upper()}"
    return data.get("id")


def find(items: list[dict | None], wanted: str) -> int:
    """Slot of the first item with this name."""
    for slot, item in enumerate(items):
        if item and name(item) == wanted:
            return slot
    raise LookupError(f"no {wanted!r} in menu")


def same_name(a: str, b: str) -> bool:
    """Compare display names ignoring case and punctuation ("Bobbin' Time I" == "Bobbin Time I")."""
    return alnum(a) == alnum(b)


def derived_name(product: str) -> str:
    """Display name for Bazaar products missing from Hypixel's item list, built from the ID.

    ENCHANTMENT_ULTIMATE_CHIMERA_1 -> "Chimera I", ESSENCE_CRIMSON -> "Crimson Essence", SHARD_SALMON -> "Salmon Shard".
    """
    kind, _, rest = product.partition("_")
    if kind == "ENCHANTMENT":
        enchant, _, level = rest.rpartition("_")
        name = _ENCHANT_NAMES.get(enchant) or _words(enchant.removeprefix("ULTIMATE_")).replace("Turbo ", "Turbo-")
        return f"{name} {_roman(int(level))}".strip()
    if kind == "SHARD":
        return f"{_SHARD_NAMES.get(rest) or _words(rest)} Shard"
    if kind == "ESSENCE":
        return f"{_words(rest)} Essence"
    if kind == "FACTION":  # chocolate factory rabbits: FACTION_RABBIT_ALLEY -> "Alley"
        return _words(rest.removeprefix("RABBIT_"))
    return _words(product)


def product_page(items: list[dict | None]) -> ProductPage:
    """Parse a product page (the menu with Buy Instantly / Create Buy Order / ...)."""
    centre = items[13]
    inventory = next((line for line in lore(items[find(items, "Sell Instantly")]) if line.startswith("Inventory:")), "")
    held = re.search(r"([\d,]+) items?", inventory)
    return ProductPage(
        product=item_id(centre),
        name=name(centre),
        buy_orders=_levels(lore(items[find(items, "Create Buy Order")])),
        sell_offers=_levels(lore(items[find(items, "Create Sell Offer")])),
        in_inventory=int(number(held.group(1))) if held else 0,
    )


def orders(items: list[dict | None]) -> list[Order]:
    """Parse the Manage Orders menu."""
    return [order for slot, item in enumerate(items) if item and (order := _order(item, slot))]


def receipt(line: str, match: re.Match) -> Receipt:
    """Build a Receipt from a matched Bazaar reply (see the patterns in constants)."""
    fields = match.groupdict()
    product, amount, coins = fields.get("product"), fields.get("amount"), fields.get("coins") or fields.get("profit")
    if refund := fields.get("refund"):  # "54,050 coins" or "1x Enchanted Lava Bucket"
        if m := re.fullmatch(r"([\d,.]+) coins", refund):
            coins = m.group(1)
        elif m := re.fullmatch(r"([\d,]+)x (.+)", refund):
            amount, product = m.groups()
    return Receipt(
        message=line,
        product=product,
        amount=int(number(amount)) if amount else None,
        coins=number(coins) if coins else None,
    )


# Names that don't follow from the ID, as shown in the game's Bazaar search.
_ENCHANT_NAMES = {
    "ULTIMATE_WISE": "Ultimate Wise",
    "ULTIMATE_JERRY": "Ultimate Jerry",
    "ULTIMATE_BOBBIN_TIME": "Bobbin' Time",
    "TRIPLE_STRIKE": "Triple-Strike",
    "COUNTER_STRIKE": "Counter-Strike",
    "TURBO_CACTUS": "Turbo-Cacti",
    "TURBO_COCO": "Turbo-Cocoa",
}
_SHARD_NAMES = {
    "ABYSSAL_LANTERN": "Abyssal Lanternfish",
    "BRUISER": "Zealot Bruiser",
    "CINDER_BAT": "Cinderbat",
    "ENDSTONE_PROTECTOR": "End Stone Protector",
    "FLIP_FLOPPER": "Flipflopper",
    "LOTUS_FISH": "Lotusfish",
    "SEA_EMPEROR": "Loch Emperor",
    "SEA_SHINE": "Seashine",
    "STRIDER_SURFER": "Stridersurfer",
    "WITHER_SPECTER": "Wither Spectre",
}
_NUMERALS = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def alnum(text: str) -> str:
    """Lowercase letters and digits only, for loose name comparison."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _words(id_part: str) -> str:
    return id_part.replace("_", " ").title()


def _roman(n: int) -> str:
    out = ""
    for value, numeral in _NUMERALS:
        count, n = divmod(n, value)
        out += numeral * count
    return out


def _levels(lines: list[str]) -> list[Level]:
    levels = []
    for line in lines:
        if m := _LEVEL.match(line):
            levels.append(Level(price=number(m.group(1)), amount=int(number(m.group(2))), orders=int(number(m.group(3)))))
    return levels


def _order(item: dict, slot: int) -> Order | None:
    side, _, _ = name(item).partition(" ")
    if side not in ("BUY", "SELL"):
        return None
    text = "\n".join(lore(item))
    amount = re.search(r"(?:Order|Offer) amount: ([\d,]+)x", text)
    price = re.search(r"Price per unit: ([\d,.]+) coins", text)
    if not (amount and price):
        return None
    total = int(number(amount.group(1)))
    filled = re.search(r"Filled: ([\d,.]+[kMB]?)/\S+ (\d+)%", text)
    return Order(
        side="buy" if side == "BUY" else "sell",
        product=item_id(item),
        name=name(item).partition(" ")[2],
        amount=total,
        filled=0 if not filled else total if filled.group(2) == "100" else int(number(filled.group(1))),
        unit_price=number(price.group(1)),
        claimable="to claim!" in text,
        slot=slot,
    )
