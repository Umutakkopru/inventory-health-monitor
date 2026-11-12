"""Excel export of the alert table, in German or English.

The German and English labels for statuses, alert-table columns and thresholds live here,
because the export needs them and this package must not import the app. The dashboard's
`app/i18n.py` reads them from here, so each label exists exactly once.
"""

import dataclasses
from io import BytesIO

import numpy as np
import pandas as pd

from inventory_monitor.config import Thresholds
from inventory_monitor.models import URGENCY_ORDER, AnalysisResult, Status

LANGUAGES = ("de", "en")

STATUS_LABELS: dict[str, dict[str, str]] = {
    "de": {
        Status.SHORTAGE_CRITICAL: "Engpass (kritisch)",
        Status.SHORTAGE_WARNING: "Meldebestand unterschritten",
        Status.OVERSTOCK: "Überbestand",
        Status.DEAD_STOCK: "Ladenhüter",
        Status.OK: "In Ordnung",
        Status.INACTIVE: "Inaktiv",
        Status.INSUFFICIENT_DATA: "Zu wenig Daten",
    },
    "en": {
        Status.SHORTAGE_CRITICAL: "Shortage (critical)",
        Status.SHORTAGE_WARNING: "Below reorder point",
        Status.OVERSTOCK: "Overstock",
        Status.DEAD_STOCK: "Dead stock",
        Status.OK: "OK",
        Status.INACTIVE: "Inactive",
        Status.INSUFFICIENT_DATA: "Insufficient data",
    },
}

# Alert-table columns in display order, with units in the header.
COLUMN_LABELS: dict[str, dict[str, str]] = {
    "de": {
        "material_id": "Material",
        "plant": "Werk",
        "description": "Materialkurztext",
        "status": "Status",
        "abc": "ABC",
        "xyz": "XYZ",
        "stock": "Bestand",
        "unit": "Mengeneinheit",
        "safety_stock": "Sicherheitsbestand",
        "reorder_point": "Meldebestand",
        "max_target": "Maximalbestand (Ziel)",
        "coverage_days": "Reichweite (Tage)",
        "projected_below_safety_date": "Unter Sicherheitsbestand ab (Projektion)",
        "projected_stockout_date": "Bestand null ab (Projektion)",
        "value_at_risk": "Wert im Risiko (EUR)",
        "stock_value": "Bestandswert (EUR)",
        "demand_anomaly": "Bedarfsanomalie",
        "receipt_anomaly": "Wareneingangsanomalie",
    },
    "en": {
        "material_id": "Material",
        "plant": "Plant",
        "description": "Description",
        "status": "Status",
        "abc": "ABC",
        "xyz": "XYZ",
        "stock": "Stock",
        "unit": "Unit",
        "safety_stock": "Safety stock",
        "reorder_point": "Reorder point",
        "max_target": "Maximum (target)",
        "coverage_days": "Coverage (days)",
        "projected_below_safety_date": "Below safety stock from (projection)",
        "projected_stockout_date": "Stock-out from (projection)",
        "value_at_risk": "Value at risk (EUR)",
        "stock_value": "Stock value (EUR)",
        "demand_anomaly": "Demand anomaly",
        "receipt_anomaly": "Receipt anomaly",
    },
}

THRESHOLD_LABELS: dict[str, dict[str, str]] = {
    "de": {
        "demand_window_days": "Bedarfsfenster (Tage)",
        "variability_window_weeks": "Schwankungsfenster (Wochen)",
        "min_history_days": "Mindesthistorie (Tage)",
        "service_level_a": "Servicegrad A",
        "service_level_b": "Servicegrad B",
        "service_level_c": "Servicegrad C",
        "abc_cutoff_a": "ABC-Grenze A (Wertanteil)",
        "abc_cutoff_b": "ABC-Grenze B (Wertanteil)",
        "xyz_cutoff_x": "XYZ-Grenze X (Variationskoeffizient)",
        "xyz_cutoff_y": "XYZ-Grenze Y (Variationskoeffizient)",
        "overstock_days_a": "Überbestand ab Reichweite A (Tage)",
        "overstock_days_b": "Überbestand ab Reichweite B (Tage)",
        "overstock_days_c": "Überbestand ab Reichweite C (Tage)",
        "dead_stock_days": "Ladenhüter ab (Tage ohne Verbrauch)",
        "anomaly_iqr_factor": "Anomalie-Faktor (IQR)",
        "ewma_alpha": "Glättungsfaktor Projektion",
        "projection_horizon_days": "Projektionshorizont (Tage)",
    },
    "en": {
        "demand_window_days": "Demand window (days)",
        "variability_window_weeks": "Variability window (weeks)",
        "min_history_days": "Minimum history (days)",
        "service_level_a": "Service level A",
        "service_level_b": "Service level B",
        "service_level_c": "Service level C",
        "abc_cutoff_a": "ABC cutoff A (value share)",
        "abc_cutoff_b": "ABC cutoff B (value share)",
        "xyz_cutoff_x": "XYZ cutoff X (coefficient of variation)",
        "xyz_cutoff_y": "XYZ cutoff Y (coefficient of variation)",
        "overstock_days_a": "Overstock from coverage A (days)",
        "overstock_days_b": "Overstock from coverage B (days)",
        "overstock_days_c": "Overstock from coverage C (days)",
        "dead_stock_days": "Dead stock after (days without use)",
        "anomaly_iqr_factor": "Anomaly factor (IQR)",
        "ewma_alpha": "Projection smoothing factor",
        "projection_horizon_days": "Projection horizon (days)",
    },
}

EXPORT_TEXT: dict[str, dict[str, str]] = {
    "de": {
        "sheet_alerts": "Warnungen",
        "sheet_info": "Parameter",
        "info_key": "Parameter",
        "info_value": "Wert",
        "as_of": "Stichtag",
        "data_note": "Datenbasis",
        "data_note_value": "Synthetische Beispieldaten",
        "yes": "Ja",
        "no": "Nein",
        "coverage_unlimited": "> 365",
    },
    "en": {
        "sheet_alerts": "Alerts",
        "sheet_info": "Parameters",
        "info_key": "Parameter",
        "info_value": "Value",
        "as_of": "As-of date",
        "data_note": "Data",
        "data_note_value": "Synthetic sample data",
        "yes": "Yes",
        "no": "No",
        "coverage_unlimited": "> 365",
    },
}

DATE_FORMATS = {"de": "DD.MM.YYYY", "en": "YYYY-MM-DD"}
QTY_FORMAT = "#,##0.0"
EUR_FORMAT = "#,##0.00"
QTY_COLUMNS = ("stock", "safety_stock", "reorder_point", "max_target", "coverage_days")
EUR_COLUMNS = ("value_at_risk", "stock_value")
DATE_COLUMNS = ("projected_below_safety_date", "projected_stockout_date")
MAX_COLUMN_WIDTH = 45


def build_alert_workbook(
    result: AnalysisResult, lang: str, rows: pd.DataFrame | None = None
) -> bytes:
    """The alert table and the parameters used, as an .xlsx file in memory.

    `rows` is the subset of `result.metrics` to export (the filtered table in the
    dashboard); by default every material. Rows are sorted by urgency, then priority.
    """
    if lang not in LANGUAGES:
        raise ValueError(f"Unknown language {lang!r}; expected one of {LANGUAGES}.")
    text = EXPORT_TEXT[lang]
    alerts = alert_table(result.metrics if rows is None else rows, lang)
    info = _info_table(result.as_of, result.thresholds, lang)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        alerts.to_excel(writer, sheet_name=text["sheet_alerts"], index=False)
        info.to_excel(writer, sheet_name=text["sheet_info"], index=False)
        _format_alerts(writer.sheets[text["sheet_alerts"]], alerts, lang)
        _format_info(writer.sheets[text["sheet_info"]], info, lang)
    return buffer.getvalue()


def alert_table(rows: pd.DataFrame, lang: str) -> pd.DataFrame:
    """The alert columns with translated headers, status and flags, most urgent first."""
    labels, text = COLUMN_LABELS[lang], EXPORT_TEXT[lang]
    urgency = rows["status"].map({s.value: i for i, s in enumerate(URGENCY_ORDER)})
    ordered = rows.assign(_urgency=urgency).sort_values(
        ["_urgency", "priority_score"], ascending=[True, False], kind="stable"
    )
    table = ordered[list(labels)].assign(
        status=ordered["status"].map(STATUS_LABELS[lang]),
        coverage_days=ordered["coverage_days"]
        .astype(object)
        .mask(np.isinf(ordered["coverage_days"].astype(float)), text["coverage_unlimited"]),
        demand_anomaly=np.where(ordered["demand_anomaly"], text["yes"], text["no"]),
        receipt_anomaly=np.where(ordered["receipt_anomaly"], text["yes"], text["no"]),
    )
    return table.rename(columns=labels).reset_index(drop=True)


def _info_table(as_of: pd.Timestamp, thresholds: Thresholds, lang: str) -> pd.DataFrame:
    text = EXPORT_TEXT[lang]
    names = THRESHOLD_LABELS[lang]
    values = dataclasses.asdict(thresholds)
    keys = [text["as_of"], text["data_note"], *(names[f] for f in values)]
    cells = [as_of, text["data_note_value"], *values.values()]
    return pd.DataFrame({text["info_key"]: keys, text["info_value"]: cells})


def _format_alerts(sheet, table: pd.DataFrame, lang: str) -> None:
    labels = COLUMN_LABELS[lang]
    formats = (
        {labels[c]: QTY_FORMAT for c in QTY_COLUMNS}
        | {labels[c]: EUR_FORMAT for c in EUR_COLUMNS}
        | {labels[c]: DATE_FORMATS[lang] for c in DATE_COLUMNS}
    )
    _format_sheet(sheet, table, formats)


def _format_info(sheet, table: pd.DataFrame, lang: str) -> None:
    _format_sheet(sheet, table, {})
    sheet.cell(row=2, column=2).number_format = DATE_FORMATS[lang]  # the as-of date


def _format_sheet(sheet, table: pd.DataFrame, formats: dict[str, str]) -> None:
    """Frozen header, number and date formats per column, readable column widths."""
    sheet.freeze_panes = "A2"
    for position, column in enumerate(table.columns, start=1):
        letter = sheet.cell(row=1, column=position).column_letter
        if column in formats:
            for (cell,) in sheet.iter_rows(min_row=2, min_col=position, max_col=position):
                cell.number_format = formats[column]
        longest = table[column].astype(str).str.len().max() if len(table) else 0
        sheet.column_dimensions[letter].width = min(max(len(column), longest) + 2, MAX_COLUMN_WIDTH)
