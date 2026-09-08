"""Exhaustive table-driven tests: every medication string and dose string
actually present in data/data_v3/medications.csv must normalize as expected
(spec Testing Decisions). Regenerate these fixtures from the raw CSV if it
ever changes."""

import pandas as pd
import pytest

from data.ingest import DEFAULT_CSV_DIR
from data.normalize import (
    DOSE_LOOKUP,
    DoseParsed,
    add_canonical_medication_columns,
    canonical_medication_name,
    parse_dose,
)

# The dataset's 16 distinct medication strings, plus None for a blank
# medication (17 total per docs/presentation-notes.md), mapped to their
# expected canonical label.
EXPECTED_CANONICAL_MEDICATION: dict[str | None, str | None] = {
    None: None,
    "CellCept": "mycophenolate mofetil",
    "MMF": "mycophenolate mofetil",
    "mycophenolate mofetil": "mycophenolate mofetil",
    "albuterol": "albuterol",
    "amlodipine": "amlodipine",
    "atorvastatin": "atorvastatin",
    "calcium carbonate": "calcium carbonate",
    "ibuprofen": "ibuprofen",
    "levothyroxine": "levothyroxine",
    "lisinopril": "lisinopril",
    "naproxen": "naproxen",
    "nifedipine": "nifedipine",
    "omeprazole": "omeprazole",
    "rituximab": "rituximab",
    "tocilizumab": "tocilizumab",
    "vitamin D3": "vitamin D3",
}

EXPECTED_PARSED_DOSE: dict[str | None, DoseParsed] = {
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


@pytest.mark.parametrize("raw,expected", sorted(EXPECTED_CANONICAL_MEDICATION.items(), key=str))
def test_canonical_medication_name(raw: str | None, expected: str | None) -> None:
    assert canonical_medication_name(raw) == expected


@pytest.mark.parametrize("raw,expected", sorted(EXPECTED_PARSED_DOSE.items(), key=str))
def test_parse_dose(raw: str | None, expected: DoseParsed) -> None:
    assert parse_dose(raw) == expected


def test_add_canonical_medication_columns_preserves_the_original_string() -> None:
    medications = pd.DataFrame({"medication": ["CellCept", "MMF", "naproxen", None]})
    result = add_canonical_medication_columns(medications)

    assert list(result["medication"])[:3] == [
        "mycophenolate mofetil",
        "mycophenolate mofetil",
        "naproxen",
    ]
    assert list(result["medication_as_recorded"])[:3] == ["CellCept", "MMF", "naproxen"]
    assert pd.isna(result["medication"].iloc[3])
    assert pd.isna(result["medication_as_recorded"].iloc[3])
    # The input frame itself is untouched.
    assert list(medications["medication"])[:3] == ["CellCept", "MMF", "naproxen"]


def test_parse_dose_rejects_unknown_string() -> None:
    with pytest.raises(ValueError, match="no dose lookup entry"):
        parse_dose("2 tablets every fortnight")


def test_medications_csv_values_are_fully_covered_by_the_fixtures() -> None:
    """Guards against the raw data drifting out from under the hand-built
    lookup tables above (and DOSE_LOOKUP itself)."""
    medications = pd.read_csv(DEFAULT_CSV_DIR / "medications.csv")

    actual_medications = {v if pd.notna(v) else None for v in medications["medication"]}
    assert actual_medications == set(EXPECTED_CANONICAL_MEDICATION)

    actual_doses = {v if pd.notna(v) else None for v in medications["dose"]}
    assert actual_doses == set(EXPECTED_PARSED_DOSE)
    assert actual_doses == set(DOSE_LOOKUP)
