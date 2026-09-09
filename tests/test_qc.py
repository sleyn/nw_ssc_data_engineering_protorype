"""Each check is exercised against a small hand-built fixture engineered to
contain a known instance of what it's supposed to catch, plus a clean fixture
it should pass without any findings (spec Testing Decisions). Checks take
plain DataFrames, not a live store connection."""

import pandas as pd

from data.qc import (
    check_blank_medication_dose_gaps,
    check_constant_value_across_visits,
    check_demographics_weight_vs_vitals,
    check_dose_implausibility,
    check_guideline_range,
    check_key_linkage,
    check_medication_name_merge,
    check_value_spike,
)

# --- key linkage -------------------------------------------------------


def test_key_linkage_flags_an_id_outside_the_confirmed_control_set() -> None:
    subjects = pd.DataFrame(
        {
            "subject_id": ["subject_1", "subject_2", "CTRL_A", "MYSTERY_ID"],
            "cohort": ["ssc_patient", "ssc_patient", "control", "control"],
        }
    )
    findings = check_key_linkage(subjects, confirmed_control_ids=frozenset({"CTRL_A"}))
    assert any("MYSTERY_ID" in f and "needs investigation" in f for f in findings)


def test_key_linkage_is_clean_when_every_control_is_confirmed() -> None:
    subjects = pd.DataFrame(
        {
            "subject_id": ["subject_1", "CTRL_A"],
            "cohort": ["ssc_patient", "control"],
        }
    )
    findings = check_key_linkage(subjects, confirmed_control_ids=frozenset({"CTRL_A"}))
    assert not any("needs investigation" in f for f in findings)
    assert not any("not present" in f for f in findings)


# --- demographics weight vs. vitals -------------------------------------


def test_weight_check_flags_implausible_weight_corroborated_by_vitals() -> None:
    demographics = pd.DataFrame({"subject_id": ["subject_1"], "weight": [22.5]})
    vitals = pd.DataFrame(
        {
            "subject_id": ["subject_1"] * 3,
            "vital_type_name_category": ["WEIGHT IN POUND"] * 3,
            "vital_value": [160.6, 160.6, 160.6],
        }
    )
    findings = check_demographics_weight_vs_vitals(demographics, vitals, min_corroborating=2)
    assert len(findings) == 1
    assert "subject_1" in findings[0]
    assert "22.5" in findings[0]
    assert "not auto-corrected" in findings[0]


def test_weight_check_is_clean_for_plausible_weights() -> None:
    demographics = pd.DataFrame({"subject_id": ["subject_1"], "weight": [160.0]})
    vitals = pd.DataFrame(
        {
            "subject_id": ["subject_1"],
            "vital_type_name_category": ["WEIGHT IN POUND"],
            "vital_value": [160.6],
        }
    )
    assert check_demographics_weight_vs_vitals(demographics, vitals) == []


# --- constant value across visits ---------------------------------------


def _constant_visits(
    subject_id: str, measure: str, value: float | str, n: int = 2
) -> list[dict[str, object]]:
    return [{"subject_id": subject_id, "measure": measure, "value": value} for _ in range(n)]


def test_constant_value_check_flags_a_value_that_dominates_the_others() -> None:
    # 6 patients all personally constant at 160.6; 6 other patients each
    # personally constant at their own distinct value. 160.6 is far more
    # common than the 1-in-7 share it would get if spread evenly.
    rows = []
    for i in range(6):
        rows += _constant_visits(f"dominant_{i}", "WEIGHT", 160.6)
    for i, value in enumerate([100.0, 110.0, 120.0, 130.0, 140.0, 150.0]):
        rows += _constant_visits(f"unique_{i}", "WEIGHT", value)
    observations = pd.DataFrame(rows)

    findings = check_constant_value_across_visits(
        observations,
        subject_col="subject_id",
        measure_col="measure",
        value_col="value",
        table_label="vitals",
        min_subjects=5,
        min_dominance_ratio=2.0,
    )
    assert len(findings) == 1
    assert "WEIGHT" in findings[0]
    assert "160.6" in findings[0]
    assert "6 patients" in findings[0]
    assert "12 total records" in findings[0]


def test_constant_value_check_is_clean_when_values_vary_within_a_patient() -> None:
    observations = pd.DataFrame(
        {
            "subject_id": ["subject_1", "subject_1", "subject_2", "subject_2"],
            "measure": ["WEIGHT", "WEIGHT", "WEIGHT", "WEIGHT"],
            "value": [150.0, 151.0, 140.0, 142.0],
        }
    )
    assert (
        check_constant_value_across_visits(
            observations,
            subject_col="subject_id",
            measure_col="measure",
            value_col="value",
            table_label="vitals",
        )
        == []
    )


def test_constant_value_check_is_clean_when_personal_constants_are_evenly_spread() -> None:
    # Every patient is personally constant, but each at a different value —
    # no single value dominates, so this is the common (uninteresting) case.
    rows = []
    for i, value in enumerate([100.0, 110.0, 120.0, 130.0, 140.0]):
        rows += _constant_visits(f"subject_{i}", "WEIGHT", value)
    observations = pd.DataFrame(rows)

    findings = check_constant_value_across_visits(
        observations,
        subject_col="subject_id",
        measure_col="measure",
        value_col="value",
        table_label="vitals",
        min_subjects=1,
        min_dominance_ratio=2.0,
    )
    assert findings == []


def test_constant_value_check_is_clean_when_only_one_value_is_ever_observed() -> None:
    rows = []
    for i in range(5):
        rows += _constant_visits(f"subject_{i}", "DIFFERENTIAL TYPE", "Automated")
    observations = pd.DataFrame(rows)

    findings = check_constant_value_across_visits(
        observations,
        subject_col="subject_id",
        measure_col="measure",
        value_col="value",
        table_label="lab_report",
        min_subjects=1,
        min_dominance_ratio=1.0,
    )
    assert findings == []


# --- value spike (population-level record share) -------------------------


def _value_rows(measure: str, value: float, n: int) -> list[dict[str, object]]:
    return [{"measure": measure, "value": value} for _ in range(n)]


def test_value_spike_check_flags_a_needle_on_top_of_a_smooth_background() -> None:
    # 21 distinct values each seen 5 times (a flat local background), except
    # one value in the middle seen 200 times — a needle, not an ordinary
    # bell-curve mode.
    rows = []
    for value in range(70, 91):
        rows += _value_rows("BP DIASTOLIC", float(value), 200 if value == 80 else 5)
    observations = pd.DataFrame(rows)

    findings = check_value_spike(
        observations,
        measure_col="measure",
        value_col="value",
        table_label="vitals",
    )
    assert len(findings) == 1
    assert "BP DIASTOLIC" in findings[0]
    assert "80" in findings[0]


def test_value_spike_check_is_clean_for_a_flat_distribution() -> None:
    # No value stands out from its neighbors at all — an ordinary uniform
    # spread, not a spike.
    rows = []
    for value in range(70, 91):
        rows += _value_rows("BP DIASTOLIC", float(value), 50)
    observations = pd.DataFrame(rows)

    assert (
        check_value_spike(
            observations,
            measure_col="measure",
            value_col="value",
            table_label="vitals",
        )
        == []
    )


def test_value_spike_check_is_clean_when_too_few_distinct_values_to_have_a_background() -> None:
    # Only 3 distinct values observed — not enough to define a local
    # background, regardless of how skewed the counts are.
    rows = (
        _value_rows("DIFFERENTIAL TYPE", 1.0, 500)
        + _value_rows("DIFFERENTIAL TYPE", 2.0, 5)
        + _value_rows("DIFFERENTIAL TYPE", 3.0, 5)
    )
    observations = pd.DataFrame(rows)

    assert (
        check_value_spike(
            observations,
            measure_col="measure",
            value_col="value",
            table_label="lab_report",
        )
        == []
    )


# --- guideline range check ------------------------------------------------


def test_guideline_range_check_flags_out_of_range_values() -> None:
    observations = pd.DataFrame(
        {
            "measure": ["WBC", "WBC", "WBC"],
            "value": [7.0, 8.0, 999.0],
        }
    )
    findings = check_guideline_range(
        observations,
        measure_col="measure",
        value_col="value",
        ranges={"WBC": (4.0, 11.0)},
        table_label="lab_report",
    )
    assert len(findings) == 1
    assert "1 of 3" in findings[0]
    assert "4-11" in findings[0]


def test_guideline_range_check_reports_a_clean_pass_as_a_finding() -> None:
    observations = pd.DataFrame({"measure": ["WBC", "WBC"], "value": [7.0, 8.0]})
    findings = check_guideline_range(
        observations,
        measure_col="measure",
        value_col="value",
        ranges={"WBC": (4.0, 11.0)},
        table_label="lab_report",
    )
    assert len(findings) == 1
    assert "0 of 2" in findings[0]


def test_guideline_range_check_flags_measures_sharing_an_identical_observed_range() -> None:
    observations = pd.DataFrame(
        {
            "measure": ["FVC", "FVC", "FEV1", "FEV1"],
            "value": [40.0, 130.0, 40.0, 130.0],
        }
    )
    findings = check_guideline_range(
        observations,
        measure_col="measure",
        value_col="value",
        ranges={"FVC": (30.0, 150.0), "FEV1": (30.0, 150.0)},
        table_label="pft",
    )
    assert any("identical observed" in f and "FEV1" in f and "FVC" in f for f in findings)


def test_guideline_range_check_reports_measure_with_no_defined_range() -> None:
    observations = pd.DataFrame({"measure": ["MYSTERY"], "value": [1.0]})
    findings = check_guideline_range(
        observations, measure_col="measure", value_col="value", ranges={}, table_label="lab_report"
    )
    assert any("no guideline range defined" in f for f in findings)


def test_guideline_range_check_reports_non_numeric_measure_as_skipped() -> None:
    observations = pd.DataFrame({"measure": ["DIFFERENTIAL TYPE"], "value": ["Automated"]})
    findings = check_guideline_range(
        observations,
        measure_col="measure",
        value_col="value",
        ranges={"DIFFERENTIAL TYPE": (0.0, 1.0)},
        table_label="lab_report",
    )
    assert any("no numeric readings" in f for f in findings)


# --- medication name merge -------------------------------------------------


def test_medication_merge_reports_fragmented_names_for_the_same_drug() -> None:
    medications = pd.DataFrame(
        {"medication": ["CellCept", "MMF", "mycophenolate mofetil", "naproxen"]}
    )
    findings = check_medication_name_merge(medications)
    assert len(findings) == 1
    assert "CellCept" in findings[0]
    assert "MMF" in findings[0]
    assert "mycophenolate mofetil" in findings[0]
    assert "naproxen" not in findings[0]


def test_medication_merge_is_clean_when_no_names_collapse() -> None:
    medications = pd.DataFrame({"medication": ["naproxen", "ibuprofen"]})
    assert check_medication_name_merge(medications) == []


# --- dose implausibility ----------------------------------------------------


def test_dose_implausibility_flags_negative_zero_magnitude_and_unit_mismatch() -> None:
    medications = pd.DataFrame(
        {
            "dose": [
                "-25 mg daily",
                "0 mg daily",
                "250 g twice daily",
                "500 mL tablets daily",
                "20 mg daily",
            ]
        }
    )
    findings = check_dose_implausibility(medications)
    assert len(findings) == 4
    joined = " ".join(findings)
    assert "non-positive dose" in joined
    assert "magnitude outlier" in joined
    assert "unit-type mismatch" in joined
    assert "20 mg daily" not in joined


def test_dose_implausibility_is_clean_for_plausible_doses() -> None:
    medications = pd.DataFrame({"dose": ["20 mg daily", "500 mg BID", "1 g twice daily"]})
    assert check_dose_implausibility(medications) == []


# --- blank medication/dose gaps ---------------------------------------------


def test_blank_medication_dose_gaps_are_reported_as_two_distinct_counts() -> None:
    medications = pd.DataFrame(
        {
            "medication": [None, "naproxen", "ibuprofen", None],
            "dose": ["20 mg daily", None, "500 mg BID", None],
        }
    )
    findings = check_blank_medication_dose_gaps(medications)
    assert findings == [
        "1 row(s) have a dose but no medication name.",
        "1 row(s) have a medication name but no dose.",
    ]


def test_blank_medication_dose_gaps_reports_zero_counts_when_clean() -> None:
    medications = pd.DataFrame({"medication": ["naproxen"], "dose": ["20 mg daily"]})
    findings = check_blank_medication_dose_gaps(medications)
    assert findings == [
        "0 row(s) have a dose but no medication name.",
        "0 row(s) have a medication name but no dose.",
    ]
