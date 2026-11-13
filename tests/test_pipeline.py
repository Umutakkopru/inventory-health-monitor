"""Tests for the dashboard summaries in pipeline.py (KPIs, matrix, Pareto, history)."""

import numpy as np
import pandas as pd
import pytest

from inventory_monitor import pipeline
from inventory_monitor.config import SAMPLE_WORKBOOK
from inventory_monitor.models import AnalysisResult, PreparedData, Status


def _metrics(rows: list[dict]) -> pd.DataFrame:
    base = {
        "plant": "1010",
        "description": "Teil",
        "abc": "A",
        "xyz": "X",
        "status": Status.OK.value,
        "stock_value": 0.0,
        "value_at_risk": 0.0,
        "priority_score": 0.0,
        "annual_consumption_value": 0.0,
        "min_stock_deviation_pct": np.nan,
    }
    return pd.DataFrame([base | {"material_id": f"{i:08d}"} | r for i, r in enumerate(rows)])


def test_kpis_count_statuses_and_sum_values() -> None:
    m = _metrics(
        [
            {"status": "SHORTAGE_CRITICAL", "stock_value": 100.0, "value_at_risk": 50.0},
            {"status": "SHORTAGE_WARNING", "stock_value": 200.0, "value_at_risk": 20.0},
            {"status": "OVERSTOCK", "stock_value": 300.0, "value_at_risk": 120.0},
            {"status": "DEAD_STOCK", "stock_value": 400.0, "value_at_risk": 400.0},
            {"status": "OK", "stock_value": 1000.0},
        ]
    )
    assert pipeline.kpis(m) == {
        "critical": 1,
        "warning": 1,
        "overstock": 1,
        "dead_stock": 1,
        "stock_value": 2000.0,  # 100 + 200 + 300 + 400 + 1000
        "excess_value": 520.0,  # overstock 120 + dead stock 400; shortages do not count
    }


def test_status_counts_list_every_status_in_urgency_order() -> None:
    counts = pipeline.status_counts(_metrics([{"status": "OK"}, {"status": "OK"}]))
    assert list(counts.index) == [
        "SHORTAGE_CRITICAL",
        "SHORTAGE_WARNING",
        "DEAD_STOCK",
        "OVERSTOCK",
        "INACTIVE",
        "INSUFFICIENT_DATA",
        "OK",
    ]
    assert counts.tolist() == [0, 0, 0, 0, 0, 0, 2]


def test_sort_by_urgency() -> None:
    m = _metrics(
        [
            {"status": "OK", "priority_score": 999.0},
            {"status": "SHORTAGE_WARNING", "priority_score": 5.0},
            {"status": "SHORTAGE_CRITICAL", "priority_score": 1.0},
            {"status": "SHORTAGE_CRITICAL", "priority_score": 7.0},
        ]
    )
    assert pipeline.sort_by_urgency(m)["material_id"].tolist() == [
        "00000003",  # critical, priority 7
        "00000002",  # critical, priority 1
        "00000001",  # warning
        "00000000",  # OK, whatever its score
    ]


def test_abc_xyz_matrix_has_all_nine_cells() -> None:
    m = _metrics(
        [
            {"abc": "A", "xyz": "X", "stock_value": 10.0},
            {"abc": "A", "xyz": "X", "stock_value": 5.0},
            {"abc": "C", "xyz": "Z", "stock_value": 1.0},
        ]
    )
    cells = pipeline.abc_xyz_matrix(m).set_index(["abc", "xyz"])
    assert len(cells) == 9
    assert cells.loc[("A", "X")].tolist() == [2, 15.0]
    assert cells.loc[("C", "Z")].tolist() == [1, 1.0]
    assert cells.loc[("B", "Y")].tolist() == [0, 0.0]


def test_pareto_cumulative_share() -> None:
    m = _metrics(
        [
            {"annual_consumption_value": 20.0},
            {"annual_consumption_value": 50.0},
            {"annual_consumption_value": 30.0},
            {"annual_consumption_value": 999.0, "plant": "1020"},  # other plant: left out
        ]
    )
    rows = pipeline.pareto(m, "1010")
    assert rows["annual_consumption_value"].tolist() == [50.0, 30.0, 20.0]
    assert rows["cumulative_share"].tolist() == pytest.approx([0.5, 0.8, 1.0])  # 50, 80, 100 %


def test_pareto_without_consumption_has_zero_shares() -> None:
    rows = pipeline.pareto(_metrics([{}, {}]), "1010")
    assert rows["cumulative_share"].tolist() == [0.0, 0.0]


def test_master_data_deviations_keep_large_ones_largest_first() -> None:
    m = _metrics(
        [
            {"min_stock_deviation_pct": 30.0},  # below 50 %: left out
            {"min_stock_deviation_pct": -80.0},
            {"min_stock_deviation_pct": 50.0},  # exactly 50 %: kept
            {"min_stock_deviation_pct": np.nan},  # no master value: left out
        ]
    )
    rows = pipeline.master_data_deviations(m)
    assert rows["material_id"].tolist() == ["00000001", "00000002"]


def test_issue_counts_list_every_check() -> None:
    issues = pd.DataFrame({"check_id": ["DQ01", "DQ01", "DQ08"]})
    counts = pipeline.issue_counts(issues).set_index("check_id")
    assert len(counts) == 11
    assert counts.loc["DQ01", "count"] == 2
    assert counts.loc["DQ08", "count"] == 1
    assert counts.loc["DQ05", "count"] == 0
    assert counts.loc["DQ02", "severity"] == "error"


# --- On the sample data --------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample() -> tuple[PreparedData, AnalysisResult]:
    prepared = pipeline.prepare(SAMPLE_WORKBOOK)
    return prepared, pipeline.analyse(prepared)


def test_stock_value_history_ends_at_the_kpi_value(sample) -> None:
    prepared, result = sample
    history = pipeline.stock_value_history(prepared, result.as_of, ["1010", "1020"])
    assert history["date"].max() == result.as_of
    assert history["date"].is_unique
    # On the as-of date the sum equals the stock value of the metrics.
    last = history.set_index("date").loc[result.as_of, "stock_value"]
    assert last == pytest.approx(result.metrics["stock_value"].sum())


def test_stock_value_history_respects_plants_and_date(sample) -> None:
    prepared, result = sample
    early = pd.Timestamp("2026-03-31")
    one_plant = pipeline.stock_value_history(prepared, early, ["1020"])
    both = pipeline.stock_value_history(prepared, early, ["1010", "1020"])
    assert one_plant["date"].max() == early
    assert (one_plant["stock_value"].to_numpy() < both["stock_value"].to_numpy()).all()


def test_material_history(sample) -> None:
    prepared, result = sample
    history = pipeline.material_history(prepared, result, "00505343", "1010")
    assert history.metrics["status"] == Status.SHORTAGE_CRITICAL
    assert history.daily["date"].max() == result.as_of
    assert set(history.by_sloc["material_id"]) == {"00505343"}
    assert history.projection["date"].min() == result.as_of
    with pytest.raises(KeyError):
        pipeline.material_history(prepared, result, "99999999", "1010")
