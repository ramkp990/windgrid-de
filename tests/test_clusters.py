import numpy as np
import pandas as pd
import pytest

from ingestion.clusters import cluster_offshore, cluster_onshore, summarize


def test_offshore_merges_small_stray_cluster():
    farm_a = pd.DataFrame({"lon": 6.0 + np.arange(10) * 0.01, "lat": [54.0] * 10})
    farm_b = pd.DataFrame({"lon": 7.0 + np.arange(10) * 0.01, "lat": [54.5] * 10})
    stray = pd.DataFrame({"lon": [6.05], "lat": [54.2]})
    df = pd.concat([farm_a, farm_b, stray], ignore_index=True)
    df["zone"] = "TenneT"
    df["capacity_kw"] = 5000.0

    labels = cluster_offshore(df, gap_km=5, min_mw=20)

    assert labels.nunique() == 2
    assert labels.iloc[-1] == labels.iloc[0]


def test_onshore_respects_k_per_zone():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "lon": rng.uniform(8, 10, 60),
            "lat": rng.uniform(50, 52, 60),
            "capacity_kw": 3000.0,
            "zone": ["TenneT"] * 30 + ["Amprion"] * 30,
        }
    )
    labels = cluster_onshore(df, k_per_zone={"TenneT": 3, "Amprion": 5})

    assert labels[df["zone"] == "TenneT"].nunique() == 3
    assert labels[df["zone"] == "Amprion"].nunique() == 5
    assert all(lab.startswith(z) for lab, z in zip(labels, df["zone"], strict=True))


def test_summarize_weighted_centre_and_hub_filter():
    df = pd.DataFrame(
        {
            "cluster_id": ["c", "c"],
            "zone": ["TenneT"] * 2,
            "location_type": ["onshore"] * 2,
            "lon": [8.0, 9.0],
            "lat": [50.0, 50.0],
            "capacity_kw": [3000.0, 1000.0],
            "hub_height_m": [100.0, 1.0],
            "decommissioned": pd.to_datetime([None, None]),
        }
    )
    out = summarize(df).iloc[0]

    assert out["lon"] == pytest.approx(8.25)
    assert out["hub_height_m"] == pytest.approx(100.0)
    assert out["capacity_mw_now"] == pytest.approx(4.0)
