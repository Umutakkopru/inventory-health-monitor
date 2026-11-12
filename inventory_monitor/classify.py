"""ABC classification by consumption value and XYZ classification by demand regularity.

Both run within each plant (Methodology, "ABC/XYZ"). ABC answers "how much money moves
through this material", XYZ "how predictable is its demand". Together they set the
service level and the overstock limit per material.
"""

import numpy as np
import pandas as pd

from inventory_monitor.config import Thresholds

# Shares are rounded before comparing with a cutoff, so that 0.8000000000000002 (a sum of
# floats that should be exactly 0.8) does not push an item into the lower class.
SHARE_DECIMALS = 9


def assign_abc(frame: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    """Add column `abc` from `annual_consumption_value`, ranked within each plant.

    Items are sorted by value, descending; ties are broken by material number so the
    result is reproducible. An item is A while the cumulative share *before* it is below
    the A cutoff, so the item that crosses a boundary belongs to the higher class. An item
    with zero value is always C, and so is every item of a plant without any consumption.
    """
    order = frame.sort_values(
        ["plant", "annual_consumption_value", "material_id"],
        ascending=[True, False, True],
        kind="stable",
    )
    value = order["annual_consumption_value"].fillna(0.0)
    total = value.groupby(order["plant"]).transform("sum")
    before = value.groupby(order["plant"]).cumsum() - value
    share_before = (before / total.where(total > 0)).round(SHARE_DECIMALS)
    abc = np.select(
        [
            (value > 0) & (share_before < thresholds.abc_cutoff_a),
            (value > 0) & (share_before < thresholds.abc_cutoff_b),
        ],
        ["A", "B"],
        default="C",
    )
    return frame.assign(abc=pd.Series(abc, index=order.index).reindex(frame.index))


def assign_xyz(frame: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    """Add column `xyz` from `cv_weekly`: X below the X cutoff, Y up to and including the
    Y cutoff, Z above it. A missing CV (no demand, or too little history) counts as Z,
    because nothing about the demand can be relied on.
    """
    cv = frame["cv_weekly"]
    xyz = np.select(
        [cv < thresholds.xyz_cutoff_x, cv <= thresholds.xyz_cutoff_y],
        ["X", "Y"],
        default="Z",
    )
    return frame.assign(xyz=xyz)
