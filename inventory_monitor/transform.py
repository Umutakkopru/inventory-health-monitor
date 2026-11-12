"""Run the SQL files in `sql/` on an in-memory DuckDB database.

The cleaned frames are registered as tables, the files run in filename order, and the
result tables come back as DataFrames. The connection is closed before returning and
never leaves this module, so no database state is shared between calls or sessions.
"""

import duckdb
import pandas as pd

from inventory_monitor.config import SQL_DIR
from inventory_monitor.models import CleanData, DailyTables

# Registered input names, as the staging SQL expects them.
INPUT_TABLES = {
    "raw_stock": "stock",
    "raw_receipts": "receipts",
    "raw_materials": "materials",
}
# Result table -> sort order of the returned DataFrame.
OUTPUT_TABLES = {
    "daily_movements": ["material_id", "plant", "date"],
    "weekly_demand": ["material_id", "plant", "week_start"],
    "sloc_daily": ["material_id", "plant", "storage_location", "date"],
}
DATE_COLUMNS = ("date", "week_start")


def sql_files() -> list[str]:
    """The SQL scripts in execution order (their file names start with 01_, 02_, ...)."""
    return [path.read_text(encoding="utf-8") for path in sorted(SQL_DIR.glob("[0-9][0-9]_*.sql"))]


def build_tables(clean: CleanData) -> DailyTables:
    """Build the daily, weekly and per-storage-location tables from the cleaned frames."""
    connection = duckdb.connect(":memory:")
    try:
        for table, field in INPUT_TABLES.items():
            connection.register(table, getattr(clean, field))
        for script in sql_files():
            connection.execute(script)
        results = {
            table: _fetch(connection, table, order) for table, order in OUTPUT_TABLES.items()
        }
    finally:
        connection.close()
    return DailyTables(
        daily=results["daily_movements"],
        weekly=results["weekly_demand"],
        by_sloc=results["sloc_daily"],
    )


def _fetch(connection: duckdb.DuckDBPyConnection, table: str, order: list[str]) -> pd.DataFrame:
    frame = connection.sql(f"SELECT * FROM {table} ORDER BY {', '.join(order)}").df()
    # DuckDB returns microsecond dates; the rest of the code uses nanoseconds throughout.
    types = {c: "datetime64[ns]" for c in DATE_COLUMNS if c in frame.columns}
    return frame.astype(types)
