"""collection — the owned-cards store + tolerant CSV import (CLAUDE.md §9)."""

import textwrap

import pytest

from manaless.collection import Collection


def test_from_csv_basic_name_quantity():
    col = Collection.from_csv("Name,Quantity\nSol Ring,1\nCounterspell,2\n")
    assert col.quantity("Sol Ring") == 1
    assert col.quantity("Counterspell") == 2
    assert col.distinct == 2
    assert col.total == 3


def test_lookup_is_case_insensitive():
    col = Collection.from_csv("Name,Quantity\nSol Ring,1\n")
    assert col.owns("sol ring") and col.owns("SOL RING")
    assert not col.owns("Mana Crypt")


def test_duplicate_rows_are_summed():
    # Collectr emits one row per printing/condition; they collapse by name.
    csv = "Card Name,Qty\nSol Ring,1\nSol Ring,2\n"
    assert Collection.from_csv(csv).quantity("Sol Ring") == 3


@pytest.mark.parametrize(
    "header",
    ["Name,Qty", "Card Name,Count", "Product Name,Quantity", "Card,Owned"],
)
def test_tolerant_to_header_aliases(header):
    col = Collection.from_csv(f"{header}\nSol Ring,2\n")
    assert col.quantity("Sol Ring") == 2


def test_quantity_column_optional_defaults_to_one():
    col = Collection.from_csv("Name\nSol Ring\nCounterspell\n")
    assert col.quantity("Sol Ring") == 1 and col.total == 2


def test_blank_or_garbage_quantity_defaults_to_one():
    col = Collection.from_csv("Name,Quantity\nSol Ring,\nMox,abc\n")
    assert col.quantity("Sol Ring") == 1 and col.quantity("Mox") == 1


def test_handles_utf8_bom_and_extra_columns():
    # a realistic-ish Collectr row: BOM + set/condition/price columns we ignore
    csv = "﻿Name,Set,Condition,Foil,Quantity,Price\nSol Ring,LTC,NM,No,3,1.50\n"
    col = Collection.from_csv(csv)
    assert col.quantity("Sol Ring") == 3


def test_real_collectr_export_header():
    # The exact header Collectr emits (verified against a real MtG export):
    # "Product Name" -> name, "Quantity" -> qty; all other columns ignored.
    csv = textwrap.dedent(
        """\
        Portfolio Name,Category,Set,Product Name,Card Number,Rarity,Variance,Grade,Card Condition,Average Cost Paid,Quantity,Market Price,Price Override,Watchlist,Date Added,Notes
        MtG,Magic: The Gathering,Aetherdrift,Aether Syphon,38,U,Normal,Ungraded,Near Mint,0.0000,1,0.3,0,false,2025-08-24,
        MtG,Magic: The Gathering,Commander Legends,Sol Ring,472,U,Normal,Ungraded,Near Mint,0.0000,2,1.50,0,false,2025-08-24,
        """
    )
    col = Collection.from_csv(csv)
    assert col.distinct == 2
    assert col.quantity("Sol Ring") == 2
    assert col.owns("aether syphon")


def test_missing_name_column_raises_with_helpful_message():
    with pytest.raises(ValueError, match="No card-name column"):
        Collection.from_csv("Foo,Bar\n1,2\n")


def test_json_roundtrip_through_disk(tmp_path):
    col = Collection.from_csv("Name,Quantity\nSol Ring,2\nMana Crypt,1\n")
    path = tmp_path / "collection.json"
    col.save(path)
    reloaded = Collection.load(path)
    assert reloaded.to_dict() == {"Sol Ring": 2, "Mana Crypt": 1}


def test_load_dispatches_on_suffix(tmp_path):
    csv_path = tmp_path / "c.csv"
    csv_path.write_text("Name,Quantity\nSol Ring,2\n", encoding="utf-8")
    assert Collection.load(csv_path).quantity("Sol Ring") == 2


def test_load_missing_file_is_empty(tmp_path):
    col = Collection.load(tmp_path / "nope.json")
    assert not col and len(col) == 0
