"""One name per station.

A station stored twice is a station the planner can never route through: a journey ending
at KALK BAY and one starting at KALKBAAI never join, and the app quietly reports no
service on a line that runs every twenty minutes.

The duplicates come from two places, and only one of them is our fault.

PRASA's own sheets disagree with themselves. The weekday Southern Line prints KALK BAY and
the weekend one prints KALKBAAI; DIEPRIVIER appears as DIEPRIVER elsewhere. Those are
editorial variants and need a stated equivalence - there is no rule that derives one from
the other.

The rest is reading noise: ST.JAMES for ST JAMES, WY NBERG for WYNBERG where sparse-text
mode split a word, RETREAT I) where the marker column bled in. Those differ only in
spacing and punctuation, so they collapse under a key that ignores both.
"""
from __future__ import annotations

import re

# Variants that no amount of normalising will join, because the letters differ. Keyed by
# the spelling to replace, valued by the one to keep.
ALIASES = {
    "KALKBAAI": "KALK BAY",
    "DIEPRIVER": "DIEPRIVIER",
    "MUIZENBURG": "MUIZENBERG",
    "SIMONS TOWN": "SIMON'S TOWN",
    "SIMONSTOWN": "SIMON'S TOWN",
    "HARFIELDROAD": "HARFIELD ROAD",
    "FISHHOEK": "FISH HOEK",
    "SALTRIVER": "SALT RIVER",
    "CAPETOWN": "CAPE TOWN",
    # Read as one word, or with the full stop the sheet does not print. The key already
    # joins these to the right station; what they need is the spelling to store, because
    # whichever variant happened to be read first is the one a rider sees in the list.
    # The weekend outbound sheet is printed in Afrikaans where the inbound one is not:
    # it lists VISHOEK between KALKBAAI and SUNNY COVE, which is exactly where FISH HOEK
    # sits on the inbound sheet. Same station, same line, two languages - and without
    # this, one of them becomes a station the other half of the line cannot reach.
    "VISHOEK": "FISH HOEK",
    "ST.JAMES": "ST JAMES",
    "STJAMES": "ST JAMES",
    "MELTONROSE": "MELTON ROSE",
    "KOEBERGRD": "KOEBERG RD",
    "DALJOSAFAT": "DAL JOSAFAT",
    "EERSTERIVER": "EERSTE RIVER",
    "KUILSRIVER": "KUILS RIVER",
    "SOMERSETWEST": "SOMERSET WEST",
    "VANDERSTEL": "VAN DER STEL",
}

_PUNCT = re.compile(r"[^A-Z0-9]+")


def key(name: str) -> str:
    """
    What two spellings of one station have in common.

    Everything that is not a letter or a digit is dropped, so ST JAMES, ST.JAMES and
    STJAMES share a key, and so do WYNBERG and WY NBERG. Names that genuinely differ -
    KALKBAAI against KALK BAY - do not, which is what the alias table is for.
    """
    return _PUNCT.sub("", (name or "").upper())


def canonical(name: str) -> str:
    """The one spelling this station is stored under."""
    tidy = " ".join((name or "").split()).upper()
    if tidy in ALIASES:
        return ALIASES[tidy]
    # An alias may itself have been read with odd spacing, so match on the key too.
    k = key(tidy)
    for variant, preferred in ALIASES.items():
        if key(variant) == k:
            return preferred
    return tidy
