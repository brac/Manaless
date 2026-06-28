"""Owned-cards store — a thin local file of what you already have (CLAUDE.md §9).

Kept deliberately dumb: a map of ``name -> quantity``. Populated by importing a
CSV exported from the **Collectr** app (or any CSV with a name + quantity column),
or hand-maintained as JSON. Used to mark owned cards in the builder and, later,
for the deck-diff buy (step 6: buy only what you don't own).

The CSV reader is **column-tolerant**: collection apps disagree on header names,
so we sniff the name and quantity columns from a set of known aliases rather than
hard-coding one schema. Multiple rows for the same card (different printings /
conditions, which Collectr emits) are summed.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

# Header aliases, matched case-insensitively after stripping. Order within a set
# does not matter; we pick the first column in the file that matches.
_NAME_HEADERS = {
    "name", "card name", "cardname", "card", "title", "card title",
    "product name", "productname", "product",
}
_QTY_HEADERS = {
    "quantity", "qty", "count", "amount", "owned", "# owned", "number",
    "copies", "holdings", "holding", "quantity owned", "quantityowned",
}


def _norm(header: str) -> str:
    return header.strip().lstrip("﻿").casefold()


def _parse_qty(raw: str) -> int:
    """Best-effort int from a CSV cell. Blank/garbage -> 1 (a listed card is owned)."""
    s = (raw or "").strip().replace(",", "")
    if not s:
        return 1
    try:
        return int(float(s))
    except ValueError:
        return 1


@dataclass
class Collection:
    """Owned cards as ``{name: quantity}``, looked up case-insensitively.

    ``counts`` is keyed by the casefolded name (so deck lookups match regardless
    of capitalisation); ``display`` keeps the first-seen pretty spelling for UI.
    """

    counts: dict[str, int] = field(default_factory=dict)
    display: dict[str, str] = field(default_factory=dict)

    # --- queries ---------------------------------------------------------
    def quantity(self, name: str) -> int:
        return self.counts.get(name.casefold(), 0)

    def owns(self, name: str) -> bool:
        return self.quantity(name) > 0

    @property
    def total(self) -> int:
        """Total copies owned (counting duplicates)."""
        return sum(self.counts.values())

    @property
    def distinct(self) -> int:
        """Number of distinct card names owned."""
        return len(self.counts)

    def __len__(self) -> int:
        return len(self.counts)

    def __bool__(self) -> bool:
        return bool(self.counts)

    # --- mutation --------------------------------------------------------
    def add(self, name: str, quantity: int = 1) -> None:
        name = name.strip()
        if not name:
            return
        key = name.casefold()
        self.counts[key] = self.counts.get(key, 0) + quantity
        self.display.setdefault(key, name)

    # --- (de)serialisation ----------------------------------------------
    def to_dict(self) -> dict[str, int]:
        """``{display name: quantity}`` — the dumb on-disk JSON shape (§9)."""
        return {self.display[key]: qty for key, qty in self.counts.items()}

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Collection":
        """Load from disk, dispatching on suffix (.json or .csv)."""
        path = Path(path)
        if not path.exists():
            return cls()
        if path.suffix.casefold() == ".json":
            return cls.from_json(json.loads(path.read_text(encoding="utf-8")))
        return cls.from_csv(path.read_text(encoding="utf-8-sig"))

    @classmethod
    def from_json(cls, obj: dict[str, int]) -> "Collection":
        col = cls()
        for name, qty in obj.items():
            col.add(str(name), int(qty))
        return col

    @classmethod
    def from_csv(cls, text: str) -> "Collection":
        """Parse a collection CSV (e.g. a Collectr export). Column-tolerant.

        Raises ``ValueError`` if no name-like column is found, naming the headers
        seen so the mismatch is obvious.
        """
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        name_col = _pick_column(headers, _NAME_HEADERS)
        if name_col is None:
            raise ValueError(
                f"No card-name column found. Headers seen: {headers!r}. "
                f"Expected one of: {sorted(_NAME_HEADERS)}."
            )
        qty_col = _pick_column(headers, _QTY_HEADERS)

        col = cls()
        for row in reader:
            name = (row.get(name_col) or "").strip()
            if not name:
                continue
            qty = _parse_qty(row.get(qty_col, "")) if qty_col else 1
            col.add(name, qty)
        return col


def _pick_column(headers: list[str], aliases: set[str]) -> str | None:
    """First header whose normalised form is a known alias, else None."""
    for header in headers:
        if _norm(header) in aliases:
            return header
    return None
