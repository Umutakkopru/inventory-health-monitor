"""Orchestration: the only analytics API the dashboard calls.

The work is split in two so the dashboard can cache the slow part:

- `prepare(source)` reads the workbook, runs the data-quality checks and the SQL step.
  It depends on nothing but the file, so it runs once per file.
- `analyse(prepared, as_of, thresholds)` computes KPIs, classes, statuses, anomaly flags
  and projection dates. It reruns whenever the user moves a slider or the date.
"""

from pathlib import Path
from typing import BinaryIO

import pandas as pd

from inventory_monitor import detect
from inventory_monitor.config import (
    ABC_CLASSES,
    DEFAULT_THRESHOLDS,
    MASTER_DEVIATION_ALERT,
    XYZ_CLASSES,
    Thresholds,
)
from inventory_monitor.detect import assign_status, flag_anomalies
from inventory_monitor.forecast import demand_rates, project, projection_dates
from inventory_monitor.ingest import load_workbook
from inventory_monitor.metrics import compute_metrics
from inventory_monitor.models import (
    URGENCY_ORDER,
    AnalysisResult,
    MaterialHistory,
    PreparedData,
    Status,
)
from inventory_monitor.quality import CHECKS, check_negative_outflow, quality_score, run_checks
from inventory_monitor.transform import build_tables

KEY = ["material_id", "plant"]
ISSUE_ORDER = ["check_id", "material_id", "plant", "date"]


def prepare(source: str | Path | BinaryIO) -> PreparedData:
    """Read, check and transform a workbook: everything that does not depend on the date.

    DQ08 (negative derived consumption) can only be found after the SQL step, so it is
    appended to the issues from the other checks here.
    """
    clean, issues = run_checks(load_workbook(source))
    tables = build_tables(clean)
    issues = pd.concat([issues, check_negative_outflow(tables.daily)], ignore_index=True)
    return PreparedData(
        clean=clean,
        tables=tables,
        issues=issues.sort_values(ISSUE_ORDER, ignore_index=True),
        first_date=tables.daily["date"].min(),
        last_date=tables.daily["date"].max(),
    )


def analyse(
    prepared: PreparedData,
    as_of: pd.Timestamp | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> AnalysisResult:
    """KPIs, classes, status, anomaly flags and projection dates as of a date.

    `as_of` defaults to the last date in the data and must lie inside the data range.
    Issues dated after `as_of` are left out of the result, so moving the date back never
    shows anything from after it.
    """
    as_of = prepared.last_date if as_of is None else pd.Timestamp(as_of).normalize()
    if not prepared.first_date <= as_of <= prepared.last_date:
        raise ValueError(
            f"as_of {as_of.date()} is outside the data range "
            f"{prepared.first_date.date()} to {prepared.last_date.date()}."
        )
    tables = prepared.tables
    metrics = assign_status(
        compute_metrics(tables, prepared.clean.materials, as_of, thresholds), thresholds
    )
    flags = flag_anomalies(metrics, tables.weekly, prepared.clean.receipts, as_of, thresholds)
    metrics = metrics.merge(flags, on=KEY).merge(
        demand_rates(tables.weekly, metrics, thresholds), on=KEY, how="left"
    )
    metrics = metrics.merge(projection_dates(metrics, as_of, thresholds), on=KEY)

    issues = prepared.issues[~(prepared.issues["date"] > as_of)].reset_index(drop=True)
    past = tables.daily[tables.daily["date"] <= as_of]
    scores = quality_score(past, issues)[[*KEY, "score"]].rename(columns={"score": "dq_score"})
    metrics = metrics.merge(scores, on=KEY, how="left")
    return AnalysisResult(metrics=metrics, issues=issues, as_of=as_of, thresholds=thresholds)


# --- Summaries for the dashboard -----------------------------------------------------------

EXCESS_STATUSES = (Status.OVERSTOCK.value, Status.DEAD_STOCK.value)
# Statuses that need someone to act; INACTIVE, INSUFFICIENT_DATA and OK do not.
ALERT_STATUSES = tuple(s.value for s in URGENCY_ORDER[:4])


def sort_by_urgency(metrics: pd.DataFrame) -> pd.DataFrame:
    """Most urgent first: by status (URGENCY_ORDER), then by priority score."""
    return detect.sort_by_urgency(metrics)


def status_counts(metrics: pd.DataFrame) -> pd.Series:
    """Number of materials per status, every status listed in urgency order (zeros kept)."""
    order = [s.value for s in URGENCY_ORDER]
    return metrics["status"].value_counts().reindex(order, fill_value=0)


def kpis(metrics: pd.DataFrame) -> dict[str, float]:
    """Headline figures: counts per alert status, total stock value and tied-up excess value.

    Excess value is the value above the overstock limit for OVERSTOCK and the whole stock
    value for DEAD_STOCK, i.e. the value at risk of those two statuses.
    """
    counts = status_counts(metrics)
    excess = metrics.loc[metrics["status"].isin(EXCESS_STATUSES), "value_at_risk"].sum()
    return {
        "critical": int(counts[Status.SHORTAGE_CRITICAL]),
        "warning": int(counts[Status.SHORTAGE_WARNING]),
        "overstock": int(counts[Status.OVERSTOCK]),
        "dead_stock": int(counts[Status.DEAD_STOCK]),
        "stock_value": float(metrics["stock_value"].sum()),
        "excess_value": float(excess),
    }


def stock_value_history(
    prepared: PreparedData, as_of: pd.Timestamp, plants: list[str]
) -> pd.DataFrame:
    """Total stock value per day up to `as_of` for the given plants.

    Uses the last observed stock carried forward, so a missing day does not show as a dip.
    """
    daily = prepared.tables.daily
    daily = daily[(daily["date"] <= pd.Timestamp(as_of)) & daily["plant"].isin(plants)]
    prices = prepared.clean.materials[[*KEY, "unit_price_eur"]]
    valued = daily.merge(prices, on=KEY)
    value = valued["stock_filled"] * valued["unit_price_eur"]
    return valued.assign(stock_value=value).groupby("date", as_index=False)["stock_value"].sum()


def material_history(
    prepared: PreparedData, result: AnalysisResult, material_id: str, plant: str
) -> MaterialHistory:
    """Daily history, storage-location split and projection of one material-plant.

    Raises KeyError when the material-plant is not part of the analysis (for example
    because it has no data before `as_of`).
    """
    metrics = result.metrics.set_index(KEY).loc[(material_id, plant)]
    tables = prepared.tables

    def _mine(frame: pd.DataFrame) -> pd.DataFrame:
        keep = (
            (frame["material_id"] == material_id)
            & (frame["plant"] == plant)
            & (frame["date"] <= result.as_of)
        )
        return frame[keep].reset_index(drop=True)

    daily = _mine(tables.daily)
    return MaterialHistory(
        metrics=metrics,
        daily=daily,
        by_sloc=_mine(tables.by_sloc),
        projection=project(daily, metrics, result.thresholds),
    )


def abc_xyz_matrix(metrics: pd.DataFrame) -> pd.DataFrame:
    """Count and stock value per ABC/XYZ cell; all nine cells, empty ones with zeros."""
    cells = pd.MultiIndex.from_product([ABC_CLASSES, XYZ_CLASSES], names=["abc", "xyz"])
    grouped = metrics.groupby(["abc", "xyz"]).agg(
        count=("material_id", "size"), stock_value=("stock_value", "sum")
    )
    return grouped.reindex(cells, fill_value=0).reset_index()


def pareto(metrics: pd.DataFrame, plant: str) -> pd.DataFrame:
    """Materials of one plant by consumption value, descending, with the cumulative share.

    The cumulative share includes the material itself, as on a Pareto chart; the ABC
    class comes from `classify` and is not recomputed here.
    """
    rows = metrics[metrics["plant"] == plant].sort_values(
        ["annual_consumption_value", "material_id"], ascending=[False, True]
    )
    value = rows["annual_consumption_value"]
    total = value.sum()
    share = value.cumsum() / total if total > 0 else value * 0.0
    return (
        rows[[*KEY, "description", "abc", "annual_consumption_value"]]
        .assign(cumulative_share=share.to_numpy())
        .reset_index(drop=True)
    )


def master_data_deviations(metrics: pd.DataFrame) -> pd.DataFrame:
    """Materials whose master-data minimum stock deviates strongly from the calculation.

    Strongly means by at least MASTER_DEVIATION_ALERT (50 %) in either direction. Sorted by
    the size of the deviation, largest first.
    """
    deviation = metrics["min_stock_deviation_pct"] / 100
    flagged = metrics[deviation.abs() >= MASTER_DEVIATION_ALERT]
    order = flagged["min_stock_deviation_pct"].abs().sort_values(ascending=False).index
    return flagged.loc[order].reset_index(drop=True)


def issue_counts(issues: pd.DataFrame) -> pd.DataFrame:
    """Number of issues per check, every check listed (zeros kept), with its severity."""
    counts = issues["check_id"].value_counts()
    return pd.DataFrame(
        {
            "check_id": list(CHECKS),
            "severity": [check.severity for check in CHECKS.values()],
            "count": [int(counts.get(check_id, 0)) for check_id in CHECKS],
        }
    )
