"""Golden Arrow's cash fares: reading them, and the reason they cannot be calculated.

The reading is the fiddly part. The fare notice renders its table rotated, so pdfplumber
finds no table at all and its text arrives interleaved a letter at a time - "PKHlElEDDD..."
being the first letter of every route name in a column. The rows are put back together by
character position, which is the sort of code that works until a font changes.

The second half of this file exists for a different reason. Twice now the obvious shortcut
has been proposed - take the five-ride price, divide by five, apply a percentage - and it
is not merely inaccurate, it is impossible, because the operator charges one card price for
journeys whose cash fares differ by 63%. That is a fact about the data rather than an
opinion about the method, so it is asserted here where anyone tempted by the shortcut will
meet it.
"""
from __future__ import annotations

import os

import pytest

from gabs_scraper.cash_fares import EFFECTIVE_FROM, rows_from_pdf, split_route

NOTICE = os.path.join("data", "gabs", "MEDIA RELEASE 2502_Fares increase August 2025.pdf")


def test_a_route_splits_into_two_areas():
    assert split_route("Bellville to Cape Town") == ("Bellville", "Cape Town")
    assert split_route("Cape Town to Wynberg") == ("Cape Town", "Wynberg")


def test_the_awkward_names_are_mapped_rather_than_guessed():
    """
    The notice writes areas its own way and a fuzzy match would be wrong about money.

    "Koeberg Power Station/Melkbos" must not become Koeberg Road, which is a street in
    Cape Town and nowhere near the power station.
    """
    assert split_route("Atlantis to Koeberg Power Station/Melkbos") == (
        "Atlantis", "Koeberg Power Station")
    assert split_route("Elsies River to Century City/Montague Gnds") == (
        "Elsies River", "Century City")
    assert split_route("Cape Town to Mitchell's Plain") == ("Cape Town", "Mitchells Plain")


def test_a_line_that_is_not_a_route_is_refused():
    assert split_route("Pensioner") is None
    assert split_route("") is None


def test_the_fares_are_dated():
    """
    A year-old fare is worth having and is not worth mistaking for today's.

    The card fares moved again in August 2026, so these are one increase behind and the
    app says so on screen.
    """
    assert EFFECTIVE_FROM.year == 2025 and EFFECTIVE_FROM.month == 8


@pytest.mark.skipif(not os.path.exists(NOTICE), reason="the fare notice is not in data/")
def test_the_rotated_table_still_reads():
    """Twenty-one routes, each with a cash fare and a five-ride fare."""
    with open(NOTICE, "rb") as fh:
        rows = rows_from_pdf(fh.read())
    assert len(rows) == 21, f"expected 21 routes, read {len(rows)}"

    by_route = {name: cash for name, cash, _ in rows}
    # Three spot values, read off the page by eye.
    assert by_route["Bellville to Welgemoed"] == 1800
    assert by_route["Cape Town to Wynberg"] == 2550
    assert by_route["Darling to Cape Town"] == 8550


@pytest.mark.skipif(not os.path.exists(NOTICE), reason="the fare notice is not in data/")
def test_cash_cannot_be_calculated_from_the_card_price():
    """
    The reason there is no percentage, stated as the operator's own numbers.

    Atlantis to Cape Town and Darling to Cape Town cost the same on a card and R52.50
    against R85.50 in cash. Any rule that turns one card price into one cash price must
    therefore be wrong about at least one of them.
    """
    with open(NOTICE, "rb") as fh:
        rows = rows_from_pdf(fh.read())

    by_card: dict[int, set[int]] = {}
    for _name, cash, five in rows:
        by_card.setdefault(five, set()).add(cash)

    clashes = {five: cashes for five, cashes in by_card.items() if len(cashes) > 1}
    assert clashes, ("the operator now charges one cash fare per card fare, which would "
                     "make a conversion possible - check before adding one")

    ratios = [cash / (five / 5) for _n, cash, five in rows]
    assert max(ratios) - min(ratios) > 0.5, (
        "the cash-to-card ratio has narrowed; it ran 1.21 to 1.99 when this was written, "
        "which is why no single multiplier works")
