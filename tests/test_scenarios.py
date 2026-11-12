"""End-to-end test on the sample workbook: every scenario gets its expected status.

If a test here fails, either the detection logic is wrong or the generator scenario is too
weak. Find out which and fix that; never edit the manifest or loosen the assertion.
"""

import json

import pandas as pd
import pytest

from inventory_monitor.config import SAMPLE_WORKBOOK, SCENARIO_MANIFEST
from inventory_monitor.models import AnalysisResult, PreparedData, Status
from inventory_monitor.pipeline import analyse, prepare

MAX_NORMAL_CRITICAL_SHARE = 0.15  # CLAUDE.md section 10


@pytest.fixture(scope="module")
def prepared() -> PreparedData:
    return prepare(SAMPLE_WORKBOOK)


@pytest.fixture(scope="module")
def result(prepared: PreparedData) -> AnalysisResult:
    return analyse(prepared)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(SCENARIO_MANIFEST.read_text(encoding="utf-8"))


def _status(result: AnalysisResult) -> dict[tuple[str, str], str]:
    m = result.metrics
    return dict(zip(zip(m["material_id"], m["plant"], strict=True), m["status"], strict=True))


def test_every_scenario_material_gets_its_expected_status(result, manifest) -> None:
    status = _status(result)
    wrong = [
        (s["scenario"], s["material_id"], s["plant"], status.get((s["material_id"], s["plant"])))
        for s in manifest["scenarios"]
        if status.get((s["material_id"], s["plant"])) not in s["expected_status"]
    ]
    assert wrong == []


def test_few_normal_materials_are_critical(result, manifest) -> None:
    status = _status(result)
    normal = [status[tuple(k)] for k in manifest["normal_material_plants"]]
    critical = sum(s == Status.SHORTAGE_CRITICAL for s in normal)
    assert critical / len(normal) <= MAX_NORMAL_CRITICAL_SHARE


def test_one_row_per_material_plant_with_a_known_status(result) -> None:
    m = result.metrics
    assert len(m) == 90
    assert not m.duplicated(["material_id", "plant"]).any()
    assert set(m["status"]) <= {s.value for s in Status}


def test_default_as_of_is_the_last_date(prepared, result) -> None:
    assert result.as_of == prepared.last_date == pd.Timestamp("2026-10-31")
    assert prepared.first_date == pd.Timestamp("2025-11-01")


def test_prepare_appends_dq08_for_every_unrecorded_receipt(prepared, manifest) -> None:
    found = prepared.issues.query("check_id == 'DQ08'")
    assert len(found) == manifest["defect_counts"]["unrecorded_receipt"]


def test_earlier_as_of_hides_later_data(prepared, manifest) -> None:
    early = analyse(prepared, pd.Timestamp("2026-05-01"))
    # New materials start less than 40 days before 31.10.: they do not exist yet.
    new = {
        (s["material_id"], s["plant"])
        for s in manifest["scenarios"]
        if s["scenario"] == "new_material"
    }
    keys = set(zip(early.metrics["material_id"], early.metrics["plant"], strict=True))
    assert keys.isdisjoint(new)
    assert len(early.metrics) == 90 - len(new)
    assert (early.issues["date"].dropna() <= early.as_of).all()
    assert (early.metrics["last_consumption_date"].dropna() <= early.as_of).all()


def test_as_of_outside_the_data_range_is_rejected(prepared) -> None:
    with pytest.raises(ValueError, match="outside the data range"):
        analyse(prepared, pd.Timestamp("2027-01-01"))


def test_analyse_does_not_change_the_prepared_data(prepared) -> None:
    daily_before = prepared.tables.daily.copy()
    issues_before = prepared.issues.copy()
    analyse(prepared, pd.Timestamp("2026-06-30"))
    pd.testing.assert_frame_equal(prepared.tables.daily, daily_before)
    pd.testing.assert_frame_equal(prepared.issues, issues_before)


def test_quality_score_is_attached(result, manifest) -> None:
    m = result.metrics.set_index(["material_id", "plant"])
    assert m["dq_score"].between(0, 1).all()
    for key in manifest["clean_material_plants"]:
        assert m.loc[tuple(key), "dq_score"] == 1.0  # no defect, no gap, no issue
