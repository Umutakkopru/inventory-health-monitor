"""Shared types: the status codes, the pipeline's result containers and the format error.

The containers are frozen so that no stage can swap out a frame another stage relies on.
They use `eq=False` because comparing DataFrames with `==` is element-wise and ambiguous;
identity comparison and identity hashing are what caching needs.
"""

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from inventory_monitor.config import Thresholds


class Status(StrEnum):
    """Health status of one material in one plant. Codes are translated only for display."""

    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INACTIVE = "INACTIVE"
    SHORTAGE_CRITICAL = "SHORTAGE_CRITICAL"
    SHORTAGE_WARNING = "SHORTAGE_WARNING"
    DEAD_STOCK = "DEAD_STOCK"
    OVERSTOCK = "OVERSTOCK"
    OK = "OK"


# Display and sort order, most urgent first: shortages, then tied-up capital, then the rest.
URGENCY_ORDER: tuple[Status, ...] = (
    Status.SHORTAGE_CRITICAL,
    Status.SHORTAGE_WARNING,
    Status.DEAD_STOCK,
    Status.OVERSTOCK,
    Status.INACTIVE,
    Status.INSUFFICIENT_DATA,
    Status.OK,
)


class WorkbookFormatError(ValueError):
    """The workbook is structurally unusable: a sheet or a required column is missing."""


@dataclass(frozen=True, eq=False)
class RawData:
    """The three sheets as read from Excel, with canonical column names and types."""

    stock: pd.DataFrame
    receipts: pd.DataFrame
    materials: pd.DataFrame


@dataclass(frozen=True, eq=False)
class CleanData:
    """The three sheets after the data-quality checks have repaired or dropped bad rows."""

    stock: pd.DataFrame
    receipts: pd.DataFrame
    materials: pd.DataFrame


@dataclass(frozen=True, eq=False)
class DailyTables:
    """Result tables of the SQL step.

    `daily` has one row per material, plant and date; `weekly` one row per material,
    plant and ISO week; `by_sloc` keeps the storage-location split for the drill-down chart.
    """

    daily: pd.DataFrame
    weekly: pd.DataFrame
    by_sloc: pd.DataFrame


@dataclass(frozen=True, eq=False)
class PreparedData:
    """Output of the slow, threshold-independent part of the pipeline."""

    clean: CleanData
    tables: DailyTables
    issues: pd.DataFrame
    first_date: pd.Timestamp
    last_date: pd.Timestamp


@dataclass(frozen=True, eq=False)
class AnalysisResult:
    """Per-material KPIs, classes and statuses as of one date under one set of thresholds."""

    metrics: pd.DataFrame
    issues: pd.DataFrame
    as_of: pd.Timestamp
    thresholds: Thresholds


@dataclass(frozen=True, eq=False)
class MaterialHistory:
    """Everything the Material Detail page shows for one material-plant, up to `as_of`.

    `metrics` is the material's row of the analysis; `projection` starts on `as_of`.
    """

    metrics: pd.Series
    daily: pd.DataFrame
    by_sloc: pd.DataFrame
    projection: pd.DataFrame
