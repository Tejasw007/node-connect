from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from .config import VALID_RSSI_RANGE


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned.columns = [str(col).strip().lower().replace(" ", "_") for col in cleaned.columns]
    return cleaned


def normalize_bssid(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = text.replace("-", ":").replace(".", ":")
    text = re.sub(r"[^0-9a-f:]", "", text)
    parts = [part for part in text.split(":") if part]
    normalized = ":".join(part.zfill(2) for part in parts)
    return normalized if len(parts) == 6 else None


def clean_observations(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = normalize_column_names(df)

    rssi_col = "rssi_dbm" if "rssi_dbm" in cleaned.columns else "rssi"
    cleaned["rssi_original"] = cleaned[rssi_col].copy() if rssi_col in cleaned.columns else None

    original_values = cleaned["rssi_original"].copy()
    cleaned["rssi_dbm"] = pd.to_numeric(cleaned["rssi_original"], errors="coerce")

    cleaned["missing_rssi"] = original_values.isna() | original_values.astype(str).str.strip().eq("")
    cleaned["invalid_numeric_rssi"] = cleaned["rssi_original"].notna() & cleaned["rssi_dbm"].isna() & ~cleaned["missing_rssi"]
    cleaned["rssi_outside_guardrail"] = cleaned["rssi_dbm"].notna() & ~cleaned["rssi_dbm"].between(*VALID_RSSI_RANGE)

    if "bssid" in cleaned.columns:
        cleaned["bssid_normalized"] = cleaned["bssid"].map(normalize_bssid)
        cleaned["bssid_missing"] = cleaned["bssid_normalized"].isna()
    else:
        cleaned["bssid_missing"] = False
        cleaned["bssid_normalized"] = None

    cleaned["quality_status"] = np.select(
        [
            cleaned["missing_rssi"],
            cleaned["invalid_numeric_rssi"],
            cleaned["rssi_outside_guardrail"],
            cleaned.get("bssid_missing", False),
        ],
        [
            "needs_review_missing_rssi",
            "needs_review_invalid_rssi",
            "needs_review_rssi_range",
            "needs_review_invalid_bssid",
        ],
        default="candidate_valid",
    )

    cleaned["review_status"] = np.where(
        cleaned["quality_status"].eq("candidate_valid"),
        "accepted",
        "needs_review",
    )

    if "timestamp" in cleaned.columns:
        cleaned["timestamp_present"] = cleaned["timestamp"].notna()
    else:
        cleaned["timestamp_present"] = False

    if {"x_m", "y_m"}.issubset(cleaned.columns):
        cleaned["position_verified"] = cleaned["x_m"].notna() & cleaned["y_m"].notna()
    else:
        cleaned["position_verified"] = False

    return cleaned


def build_quality_summary(df: pd.DataFrame) -> dict[str, int | float]:
    cleaned = clean_observations(df)
    summary = {
        "rows": int(len(cleaned)),
        "accepted": int(cleaned["review_status"].eq("accepted").sum()),
        "needs_review": int(cleaned["review_status"].eq("needs_review").sum()),
        "missing_rssi": int(cleaned["missing_rssi"].sum()),
        "invalid_rssi": int(cleaned["invalid_numeric_rssi"].sum()),
        "outside_guardrail": int(cleaned["rssi_outside_guardrail"].sum()),
        "invalid_bssid": int(cleaned.get("bssid_missing", pd.Series(False, index=cleaned.index)).sum()),
    }
    if "rssi_dbm" in cleaned.columns:
        non_missing = cleaned["rssi_dbm"].dropna()
        if not non_missing.empty:
            summary["median_rssi_dbm"] = float(non_missing.median())
    return summary


def import_csv(path: str | Iterable[str]) -> pd.DataFrame:
    if isinstance(path, str):
        return pd.read_csv(path)
    return pd.concat([pd.read_csv(item) for item in path], ignore_index=True)
