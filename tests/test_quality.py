"""Tests for the data-quality checks (CLAUDE.md section 6.1).

Each check gets a small hand-built data set: one material 00000001 in plant 1010 with five
daily snapshots (10, 9, 8, 7, 6) from 01.01. to 05.01.2026 and one receipt on 03.01. The
tests change one thing at a time. DQ08 needs derived consumption and is tested in Phase 3.
"""

import json

import numpy as np
import pandas as pd
import pytest

from inventory_monitor.config import SAMPLE_WORKBOOK, SCENARIO_MANIFEST
from inventory_monitor.ingest import load_workbook
from inventory_monitor.models import RawData
from inventory_monitor.quality import ISSUE_COLUMNS, run_checks

MAT, PLANT = "00000001", "1010"
DAYS = pd.date_range("2026-01-01", "2026-01-05")


def _stock(**changes: list) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": DAYS,
            "material_id": MAT,
            "plant": PLANT,
            "storage_location": "0001",
            "stock_qty": [10.0, 9.0, 8.0, 7.0, 6.0],
            "unit": "ST",
            "material_id_repaired": False,
        }
    )
    return frame.assign(**changes)


def _receipts(rows: list[dict] | None = None) -> pd.DataFrame:
    base = {
        "date": pd.Timestamp("2026-01-03"),
        "material_id": MAT,
        "plant": PLANT,
        "storage_location": "0001",
        "receipt_qty": 5.0,
        "supplier": "Lieferant 01",
        "po_number": "4500000001",
        "material_id_repaired": False,
    }
    return pd.DataFrame([base | row for row in (rows or [{}])])


def _materials(rows: list[dict] | None = None) -> pd.DataFrame:
    base = {
        "material_id": MAT,
        "plant": PLANT,
        "description": "Kugellager 6204",
        "unit_price_eur": 2.0,
        "lead_time_days": 7.0,
        "min_stock": np.nan,
        "max_stock": np.nan,
        "unit": "ST",
        "material_id_repaired": False,
    }
    return pd.DataFrame([base | row for row in (rows or [{}])])


def _raw(stock=None, receipts=None, materials=None) -> RawData:
    return RawData(
        stock=_stock() if stock is None else stock,
        receipts=_receipts() if receipts is None else receipts,
        materials=_materials() if materials is None else materials,
    )


def _issues(raw: RawData, check_id: str) -> pd.DataFrame:
    return run_checks(raw)[1].query("check_id == @check_id").reset_index(drop=True)


# --- Clean input ---------------------------------------------------------------------------


def test_clean_input_has_no_issues_and_keeps_every_row() -> None:
    clean, issues = run_checks(_raw())
    assert issues.empty
    assert list(issues.columns) == ISSUE_COLUMNS
    assert len(clean.stock) == 5 and len(clean.receipts) == 1 and len(clean.materials) == 1
    assert "material_id_repaired" not in clean.stock.columns
    assert clean.materials["lead_time_days"].dtype == "int64"


def test_input_frames_are_not_mutated() -> None:
    raw = _raw(stock=_stock(stock_qty=[10.0, 9.0, -2.0, 7.0, 6.0]))
    before = raw.stock.copy()
    run_checks(raw)
    pd.testing.assert_frame_equal(raw.stock, before)


# --- One test per check --------------------------------------------------------------------


def test_dq01_missing_day_inside_range() -> None:
    raw = _raw(stock=_stock().drop(index=2))  # 03.01. missing
    found = _issues(raw, "DQ01")
    assert found["date"].tolist() == [pd.Timestamp("2026-01-03")]
    assert found["detail"].tolist() == [""]
    assert found["severity"].tolist() == ["warning"]


def test_dq01_partial_snapshot_names_the_missing_location() -> None:
    second = _stock(storage_location="0002", stock_qty=[1.0] * 5).drop(index=2)
    raw = _raw(stock=pd.concat([_stock(), second], ignore_index=True))
    found = _issues(raw, "DQ01")
    assert found["date"].tolist() == [pd.Timestamp("2026-01-03")]
    assert found["detail"].tolist() == ["0002"]


def test_dq01_ignores_days_outside_a_locations_range() -> None:
    # 0002 starts on 03.01.: the two days before are outside its range, not missing.
    second = _stock(storage_location="0002", stock_qty=[1.0] * 5).iloc[2:]
    raw = _raw(stock=pd.concat([_stock(), second], ignore_index=True))
    assert _issues(raw, "DQ01").empty


def test_dq02_negative_stock_becomes_a_missing_snapshot() -> None:
    raw = _raw(stock=_stock(stock_qty=[10.0, 9.0, -2.0, 7.0, 6.0]))
    clean, issues = run_checks(raw)
    found = issues.query("check_id == 'DQ02'")
    assert found["detail"].tolist() == ["0001: -2"]
    assert found["action_taken"].tolist() == ["treated_as_missing"]
    assert pd.Timestamp("2026-01-03") not in set(clean.stock["date"])
    assert issues.query("check_id == 'DQ01'").empty  # reported once, as DQ02


def test_dq03_conflicting_duplicate_keeps_the_last_row() -> None:
    wrong = _stock().iloc[[2]].assign(stock_qty=99.0)
    raw = _raw(stock=pd.concat([wrong, _stock()], ignore_index=True))  # 99 first, 8 last
    clean, issues = run_checks(raw)
    assert issues.query("check_id == 'DQ03'")["detail"].tolist() == ["99 | 8"]
    assert clean.stock["stock_qty"].tolist() == [10.0, 9.0, 8.0, 7.0, 6.0]


def test_dq03_exact_duplicate() -> None:
    raw = _raw(stock=pd.concat([_stock(), _stock().iloc[[2]]], ignore_index=True))
    clean, issues = run_checks(raw)
    assert issues.query("check_id == 'DQ03'")["detail"].tolist() == ["8 | 8"]
    assert len(clean.stock) == 5


def test_dq04_receipt_for_unknown_material_is_dropped() -> None:
    raw = _raw(receipts=_receipts([{}, {"material_id": "00000002"}]))
    clean, issues = run_checks(raw)
    found = issues.query("check_id == 'DQ04'")
    assert found["material_id"].tolist() == ["00000002"]
    assert found["detail"].tolist() == ["5"]
    assert clean.receipts["material_id"].tolist() == [MAT]


def test_dq04_known_material_in_another_plant_is_unknown() -> None:
    raw = _raw(receipts=_receipts([{}, {"plant": "1020"}]))
    assert _issues(raw, "DQ04")["plant"].tolist() == ["1020"]


def test_dq05_stock_for_unknown_material_gives_one_issue_per_material_plant() -> None:
    other = _stock(material_id="00000009").iloc[:3]
    raw = _raw(stock=pd.concat([_stock(), other], ignore_index=True))
    clean, issues = run_checks(raw)
    found = issues.query("check_id == 'DQ05'")
    assert found["detail"].tolist() == ["3"]  # three rows dropped
    assert found["date"].tolist() == [pd.Timestamp("2026-01-01")]
    assert set(clean.stock["material_id"]) == {MAT}


def test_dq06_zero_negative_and_empty_receipts_are_dropped() -> None:
    rows = [{}, {"receipt_qty": 0.0}, {"receipt_qty": -1.0}, {"receipt_qty": np.nan}]
    clean, issues = run_checks(_raw(receipts=_receipts(rows)))
    assert sorted(issues.query("check_id == 'DQ06'")["detail"]) == ["-1", "0", "nan"]
    assert clean.receipts["receipt_qty"].tolist() == [5.0]


def test_dq07_repaired_material_numbers_are_reported_per_sheet() -> None:
    stock = _stock(material_id_repaired=[False, True, False, False, False])
    receipts = _receipts([{"material_id_repaired": True}])
    found = _issues(_raw(stock=stock, receipts=receipts), "DQ07")
    assert sorted(found["sheet"]) == ["Bestand", "Wareneingang"]
    assert set(found["severity"]) == {"info"}


def test_dq09_other_unit_keeps_the_master_unit() -> None:
    stock = _stock(unit=["ST", "ST", "KG", "ST", "ST"])
    clean, issues = run_checks(_raw(stock=stock))
    assert issues.query("check_id == 'DQ09'")["detail"].tolist() == ["KG -> ST"]
    assert set(clean.stock["unit"]) == {"ST"}


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"unit_price_eur": 0.0}, "unit_price_eur"),
        ({"lead_time_days": np.nan}, "lead_time_days"),
        ({"unit_price_eur": -1.0, "lead_time_days": 0.0}, "unit_price_eur,lead_time_days"),
    ],
)
def test_dq10_invalid_master_excludes_the_material(change: dict, detail: str) -> None:
    clean, issues = run_checks(_raw(materials=_materials([change])))
    assert issues.query("check_id == 'DQ10'")["detail"].tolist() == [detail]
    assert clean.materials.empty and clean.stock.empty and clean.receipts.empty
    # Its stock and receipts are not reported a second time as unknown material.
    assert issues.query("check_id in ['DQ04', 'DQ05']").empty


def test_dq11_receipt_outside_the_snapshot_range_is_ignored() -> None:
    rows = [{}, {"date": pd.Timestamp("2025-12-31")}, {"date": pd.Timestamp("2026-01-06")}]
    clean, issues = run_checks(_raw(receipts=_receipts(rows)))
    found = issues.query("check_id == 'DQ11'")
    assert found["date"].tolist() == [pd.Timestamp("2025-12-31"), pd.Timestamp("2026-01-06")]
    assert clean.receipts["date"].tolist() == [pd.Timestamp("2026-01-03")]


def test_dq11_receipt_for_material_without_any_snapshot() -> None:
    materials = _materials([{}, {"material_id": "00000002"}])
    raw = _raw(receipts=_receipts([{}, {"material_id": "00000002"}]), materials=materials)
    assert _issues(raw, "DQ11")["material_id"].tolist() == ["00000002"]


def test_empty_quantity_cell_is_a_missing_day() -> None:
    raw = _raw(stock=_stock(stock_qty=[10.0, 9.0, np.nan, 7.0, 6.0]))
    assert _issues(raw, "DQ01")["date"].tolist() == [pd.Timestamp("2026-01-03")]


# --- Sample workbook against the manifest --------------------------------------------------


@pytest.fixture(scope="module")
def sample() -> tuple[pd.DataFrame, dict]:
    _, issues = run_checks(load_workbook(SAMPLE_WORKBOOK))
    return issues, json.loads(SCENARIO_MANIFEST.read_text(encoding="utf-8"))


def _manifest_keys(manifest: dict, *kinds: str) -> set[tuple]:
    return {
        (d["material_id"], d["plant"], pd.Timestamp(d["date"]))
        for d in manifest["defects"]
        if d["defect"] in kinds
    }


def _issue_keys(issues: pd.DataFrame, check_id: str) -> set[tuple]:
    found = issues.query("check_id == @check_id")
    return set(zip(found["material_id"], found["plant"], found["date"], strict=True))


def test_sample_counts_match_the_manifest(sample) -> None:
    issues, manifest = sample
    counts = issues["check_id"].value_counts()
    injected = manifest["defect_counts"]
    assert counts["DQ01"] == injected["missing_day"] + injected["partial_snapshot"]
    assert counts["DQ02"] == injected["negative_stock"]
    assert counts["DQ03"] == injected["exact_duplicate"] + injected["conflicting_duplicate"]
    assert counts["DQ04"] == injected["unknown_material"]
    assert counts["DQ07"] == injected["lost_leading_zeros"]
    # Nothing of these kinds was injected, so nothing may be found.
    assert not set(counts.index) & {"DQ05", "DQ06", "DQ09", "DQ10", "DQ11"}


def test_sample_findings_are_exactly_the_injected_rows(sample) -> None:
    issues, manifest = sample
    assert _issue_keys(issues, "DQ01") == _manifest_keys(
        manifest, "missing_day", "partial_snapshot"
    )
    assert _issue_keys(issues, "DQ02") == _manifest_keys(manifest, "negative_stock")
    assert _issue_keys(issues, "DQ03") == _manifest_keys(
        manifest, "exact_duplicate", "conflicting_duplicate"
    )
    assert _issue_keys(issues, "DQ07") == _manifest_keys(manifest, "lost_leading_zeros")
