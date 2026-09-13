from __future__ import annotations

import os

import pandas as pd

from .models import Match


def matches_to_dataframe(matches: list[Match]) -> pd.DataFrame:
    return pd.DataFrame(m.to_flat_dict() for m in matches)


def save_to_excel(matches: list[Match], path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    df = matches_to_dataframe(matches)
    df.to_excel(path, index=False, engine="openpyxl")
