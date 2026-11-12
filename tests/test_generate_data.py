"""Tests for the synthetic data generator (CLAUDE.md section 5)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from inventory_monitor import generate_data as g
from inventory_monitor.config import (
    DEFAULT_THRESHOLDS,
    SAMPLE_WORKBOOK,
    SCENARIO_MANIFEST,
    SHEET_MATERIALS,
    SHEET_RECEIPTS,
    SHEET_STOCK,
)
from inventory_monitor.models import Status

ID_HEADERS = {"Material": str, "Werk": str, "Lagerort": str, "Bestellnummer": str}


@pytest.fixture(scope="module")
def generated() -> g.Generated:
    return g.generate()


@pytest.fixture(scope="module")
def committed() -> dict[str, pd.DataFrame]:
    return pd.read_excel(SAMPLE_WORKBOOK, sheet_name=None, dtype=ID_HEADERS)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(SCENARIO_MANIFEST.read_text(encoding="utf-8"))


# --- Determinism and the committed files ---------------------------------------------------


def test_two_runs_give_equal_frames(generated: g.Generated) -> None:
    again = g.generate()
    pd.testing.assert_frame_equal(generated.stock, again.stock)
    pd.testing.assert_frame_equal(generated.receipts, again.receipts)
    pd.testing.assert_frame_equal(generated.materials, again.materials)
    pd.testing.assert_frame_equal(generated.simulation.daily, again.simulation.daily)
    assert generated.manifest == again.manifest


def test_committed_files_equal_a_fresh_run(
    generated: g.Generated, committed: dict[str, pd.DataFrame], tmp_path: Path
) -> None:
    # Compare by reading both workbooks back, never by bytes: .xlsx embeds timestamps.
    fresh_xlsx, fresh_json = tmp_path / "fresh.xlsx", tmp_path / "fresh.json"
    g.write_workbook(generated, fresh_xlsx)
    g.write_manifest(generated, fresh_json)
    fresh = pd.read_excel(fresh_xlsx, sheet_name=None, dtype=ID_HEADERS)
    assert list(committed) == [SHEET_STOCK, SHEET_RECEIPTS, SHEET_MATERIALS]
    for sheet in committed:
        pd.testing.assert_frame_equal(committed[sheet], fresh[sheet])
    assert json.loads(fresh_json.read_text(encoding="utf-8")) == json.loads(
        SCENARIO_MANIFEST.read_text(encoding="utf-8")
    )


def test_main_writes_both_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "SAMPLE_WORKBOOK", tmp_path / "w.xlsx")
    monkeypatch.setattr(g, "SCENARIO_MANIFEST", tmp_path / "m.json")
    g.main()
    assert (tmp_path / "w.xlsx").stat().st_size > 0
    assert json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["seed"] == 42


def test_workbook_layout(committed: dict[str, pd.DataFrame]) -> None:
    sheets = committed
    stock = sheets[SHEET_STOCK]
    assert list(stock.columns) == [
        "Datum",
        "Material",
        "Werk",
        "Lagerort",
        "Bestand",
        "Mengeneinheit",
    ]
    assert pd.api.types.is_datetime64_any_dtype(stock["Datum"])
    assert stock["Datum"].min() == pd.Timestamp("2025-11-01")
    assert stock["Datum"].max() == pd.Timestamp("2026-10-31")
    # Leading zeros survive as text in the master data.
    assert sheets[SHEET_MATERIALS]["Material"].str.fullmatch(r"\d{8}").all()
    assert sheets[SHEET_MATERIALS]["Material"].str.startswith("0").any()


# --- Simulation ground truth ---------------------------------------------------------------


def test_stock_identity_holds_before_defects(generated: g.Generated) -> None:
    daily = generated.simulation.daily.sort_values(["material_id", "plant", "date"])
    previous = daily.groupby(["material_id", "plant"])["stock_qty"].shift()
    residual = previous + daily["receipt_qty"] - daily["consumption"] - daily["stock_qty"]
    assert residual.dropna().abs().max() < 1e-6
    assert (daily["stock_qty"] >= 0).all()
    assert (daily["consumption"] <= daily["demand"] + 1e-9).all()


def test_no_consumption_at_weekends(generated: g.Generated) -> None:
    daily = generated.simulation.daily
    weekend = daily["date"].dt.day_of_week >= 5
    assert daily.loc[weekend, "consumption"].sum() == 0


def test_storage_locations_add_up_to_simulated_stock(generated: g.Generated) -> None:
    split = g.split_stock(generated.plans, generated.simulation.daily)
    total = split.groupby(["material_id", "plant", "date"])["stock_qty"].sum()
    truth = generated.simulation.daily.set_index(["material_id", "plant", "date"])["stock_qty"]
    pd.testing.assert_series_equal(
        total.sort_index(), truth.sort_index(), check_names=False, atol=1e-9
    )


def test_receipts_frame_matches_daily_receipts(generated: g.Generated) -> None:
    sim = generated.simulation
    booked = sim.receipts.groupby(["material_id", "plant", "date"])["receipt_qty"].sum()
    daily = sim.daily.set_index(["material_id", "plant", "date"])["receipt_qty"]
    np.testing.assert_allclose(daily[daily > 0].sort_index(), booked.sort_index())


# --- Scenarios and defects -----------------------------------------------------------------


def test_every_scenario_has_at_least_three_materials(manifest: dict) -> None:
    counts = pd.Series([s["scenario"] for s in manifest["scenarios"]]).value_counts()
    assert set(counts.index) == set(g.SCENARIO_EXPECTED)
    assert (counts >= 3).all()
    statuses = {s.value for s in Status}
    assert all(set(s["expected_status"]) <= statuses for s in manifest["scenarios"])


def test_scenario_materials_are_distinct(manifest: dict) -> None:
    keys = [(s["material_id"], s["plant"]) for s in manifest["scenarios"]]
    assert len(keys) == len(set(keys))
    normal = {tuple(k) for k in manifest["normal_material_plants"]}
    assert normal.isdisjoint(keys)
    # 90 material-plants in total: 8 scenarios x 3 = 24, the rest is normal.
    assert len(normal) == 90 - 24


def test_defect_counts(manifest: dict) -> None:
    counts = manifest["defect_counts"]
    assert counts["negative_stock"] == 6
    assert counts["exact_duplicate"] == 5
    assert counts["conflicting_duplicate"] == 5
    assert counts["unknown_material"] == 4
    assert counts["lost_leading_zeros"] == 10  # 6 stock rows + 4 receipts
    assert counts["unrecorded_receipt"] == 3
    assert counts["partial_snapshot"] == 10
    gap_days = sum(1 for d in manifest["defects"] if d["detail"] == "gap")
    assert gap_days == 16  # gaps of 2 + 3 + 4 + 3 + 4 days
    # About 1 % of material-plant-days are missing in total.
    assert 280 <= counts["missing_day"] + counts["partial_snapshot"] <= 360


def test_defects_avoid_protected_and_clean_material_plants(manifest: dict) -> None:
    defects = pd.DataFrame(manifest["defects"])
    keys = list(zip(defects["material_id"], defects["plant"], strict=True))
    scenario = {(s["material_id"], s["plant"]) for s in manifest["scenarios"]}
    clean = {tuple(k) for k in manifest["clean_material_plants"]}
    late = pd.to_datetime(defects["date"]) > pd.Timestamp("2026-10-17")  # 31.10. minus 14 days
    assert not any(k in scenario and is_late for k, is_late in zip(keys, late, strict=True))
    assert clean.isdisjoint(keys)
    assert len(clean) >= 3


def test_defects_are_visible_in_the_workbook(committed: dict[str, pd.DataFrame]) -> None:
    sheets = committed
    stock, receipts = sheets[SHEET_STOCK], sheets[SHEET_RECEIPTS]
    master = set(sheets[SHEET_MATERIALS]["Material"])
    assert (stock["Bestand"] < 0).sum() == 6
    key = ["Datum", "Material", "Werk", "Lagerort"]
    assert stock.duplicated(key).sum() == 10
    assert (stock["Material"].str.len() < 8).sum() == 6
    assert (receipts["Material"].str.len() < 8).sum() == 4
    assert (~receipts["Material"].str.zfill(8).isin(master)).sum() == 4


# --- Building blocks with hand-calculated values -------------------------------------------


def test_round_qty() -> None:
    assert g.round_qty(3.01, "ST") == 4.0  # pieces round up
    assert g.round_qty(3.01, "KG") == 3.1  # one decimal, rounded up


def test_weekly_sigma_steady() -> None:
    # sqrt(5) * 0.15 * 10 = 3.3541
    assert g._weekly_sigma("steady", 10.0) == pytest.approx(3.3541, abs=1e-4)


def test_weekly_sigma_intermittent() -> None:
    # p = 0.08, mu = 10: size mean 125, E[S^2] = 125^2 * 1.25 = 19531.25
    # var(day) = 0.08 * 19531.25 - 100 = 1462.5; weekly sigma = sqrt(5 * 1462.5) = 85.51
    assert g._weekly_sigma("intermittent", 10.0) == pytest.approx(85.51, abs=1e-2)


def test_estimate_abc_crossing_item_belongs_to_higher_class() -> None:
    values = pd.Series([50.0, 30.0, 15.0, 5.0])
    # cumulative share before each item: 0.00, 0.50, 0.80, 0.95
    # 0.80 is not below the A cutoff 0.80 -> B; 0.95 is not below the B cutoff 0.95 -> C
    assert g.estimate_abc(values, DEFAULT_THRESHOLDS).tolist() == ["A", "A", "B", "C"]


def test_plans_respect_order_cap(generated: g.Generated) -> None:
    for plan in generated.plans:
        cap_days = 0.75 * DEFAULT_THRESHOLDS.overstock_days(plan.abc_estimate)
        # +1 unit tolerance for rounding the order quantity up
        assert plan.order_qty <= plan.daily_demand * cap_days + 1
