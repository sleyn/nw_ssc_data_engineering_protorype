"""Pure lookup-table normalizations for medication names and dose strings.

Both lookups are hardcoded (not fuzzy-matched or NLP-parsed) because the raw
`medications.csv` has a fully enumerable space of distinct values: 16 medication
strings (plus blank) and 23 dose strings (plus blank) — see
`docs/presentation-notes.md`. These functions are pure (no I/O) so they can be
exhaustively table-tested and reused by both the QC report (`data/qc.py`) and,
later, the shared data-access layer.
"""

from typing import NamedTuple

import pandas as pd

# CellCept (brand) / mycophenolate mofetil (generic) / MMF (abbreviation) are
# the same drug under three names (docs/presentation-notes.md). Canonicalized
# to the generic name; any medication not listed here passes through unchanged.
MEDICATION_CANONICAL_MAP: dict[str, str] = {
    "CellCept": "mycophenolate mofetil",
    "MMF": "mycophenolate mofetil",
}


def canonical_medication_name(raw: str | None) -> str | None:
    """Map a raw medication string to its canonical label. The original string
    is never discarded by this function — callers preserve it separately in an
    "as recorded" field."""
    if raw is None:
        return None
    return MEDICATION_CANONICAL_MAP.get(raw, raw)


def add_canonical_medication_columns(medications: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `medications` with `medication` replaced by its
    canonical label and the original string preserved in
    `medication_as_recorded` — so prevalence charts reflect the true
    prescribing pattern (e.g. CellCept/MMF/mycophenolate mofetil counted as
    one drug) without discarding what was actually written down."""
    result = medications.copy()
    result["medication_as_recorded"] = result["medication"]
    result["medication"] = result["medication"].map(canonical_medication_name)
    return result


class DoseParsed(NamedTuple):
    """A dose string broken into its structured components. All fields are
    `None` for a dose string that carries no parseable numeric amount (a bare
    "PRN") or for a blank/missing dose."""

    value: float | None
    unit: str | None
    frequency: str | None


# The dataset's 23 distinct non-blank dose strings, plus `None` for a blank
# dose, parsed by hand into value/unit/frequency (docs/presentation-notes.md:
# "Only 24 distinct dose strings exist"). Deliberately a flat lookup table,
# not a general free-text parser (spec Out-of-Scope).
DOSE_LOOKUP: dict[str | None, DoseParsed] = {
    None: DoseParsed(None, None, None),
    "-1 tablet daily": DoseParsed(-1.0, "tablet", "daily"),
    "-25 mg daily": DoseParsed(-25.0, "mg", "daily"),
    "0 mg daily": DoseParsed(0.0, "mg", "daily"),
    "1 g twice daily": DoseParsed(1.0, "g", "twice daily"),
    "10 mg daily": DoseParsed(10.0, "mg", "daily"),
    "1000 mg BID": DoseParsed(1000.0, "mg", "BID"),
    "1000 mg IV x2": DoseParsed(1000.0, "mg", "IV x2"),
    "10000 mg every hour": DoseParsed(10000.0, "mg", "every hour"),
    "1500 mg BID": DoseParsed(1500.0, "mg", "BID"),
    "162 mg SC weekly": DoseParsed(162.0, "mg", "SC weekly"),
    "20 mg daily": DoseParsed(20.0, "mg", "daily"),
    "2000 IU daily": DoseParsed(2000.0, "IU", "daily"),
    "250 g twice daily": DoseParsed(250.0, "g", "twice daily"),
    "30 mg daily": DoseParsed(30.0, "mg", "daily"),
    "400 mg PRN": DoseParsed(400.0, "mg", "PRN"),
    "5 mg daily": DoseParsed(5.0, "mg", "daily"),
    "50 mcg daily": DoseParsed(50.0, "mcg", "daily"),
    "500 mL tablets daily": DoseParsed(500.0, "mL", "daily"),
    "500 mg BID": DoseParsed(500.0, "mg", "BID"),
    "500 mg daily": DoseParsed(500.0, "mg", "daily"),
    "750mg BID": DoseParsed(750.0, "mg", "BID"),
    "999 tablets daily": DoseParsed(999.0, "tablet", "daily"),
    "PRN": DoseParsed(None, None, "PRN"),
}


def parse_dose(raw: str | None) -> DoseParsed:
    """Look up `raw` in the dataset's dose table. Raises `ValueError` for a
    dose string outside the dataset's known 24 — this is a fixed lookup table,
    not a parser, so an unrecognized string means the table needs a new row,
    not a guess."""
    try:
        return DOSE_LOOKUP[raw]
    except KeyError:
        raise ValueError(
            f"no dose lookup entry for {raw!r}; DOSE_LOOKUP only covers the "
            "dataset's known 24 distinct dose strings"
        ) from None
