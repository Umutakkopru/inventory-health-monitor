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

from inventory_monitor.config import DEFAULT_THRESHOLDS, Thresholds
from inventory_monitor.detect import assign_status, flag_anomalies
from inventory_monitor.forecast import demand_rates, projection_dates
from inventory_monitor.ingest import load_workbook
from inventory_monitor.metrics import compute_metrics
from inventory_monitor.models import AnalysisResult, PreparedData
from inventory_monitor.quality import check_negative_outflow, quality_score, run_checks
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
