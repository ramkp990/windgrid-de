"""Group turbines into weather clusters: k-means onshore, gap-based offshore."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans

log = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
TURBINES_PATH = PROCESSED_DIR / "turbines.parquet"
CLUSTERS_PATH = PROCESSED_DIR / "clusters.parquet"
MEMBERS_PATH = PROCESSED_DIR / "turbine_clusters.parquet"

ACTIVE_SINCE = "2021-01-01"
ONSHORE_K = {"50Hertz": 50, "Amprion": 50, "TenneT": 50, "TransnetBW": 20}
OFFSHORE_GAP_KM = 5.0
MIN_OFFSHORE_CLUSTER_MW = 20.0
HUB_HEIGHT_RANGE_M = (20.0, 200.0)
ONSHORE_LAT0 = 51.0
OFFSHORE_LAT0 = 54.5
SEED = 0


def to_km(df: pd.DataFrame, lat0: float) -> np.ndarray:
    """Convert lon/lat to approximate km, so distances mean the same in every direction."""
    x = df["lon"].to_numpy() * 111.32 * np.cos(np.radians(lat0))
    y = df["lat"].to_numpy() * 110.57
    return np.column_stack([x, y])


def cluster_onshore(df: pd.DataFrame, k_per_zone: dict[str, int] = ONSHORE_K) -> pd.Series:
    """Capacity-weighted k-means per zone. Returns cluster IDs like 'TenneT_on_07'."""
    labels = pd.Series(index=df.index, dtype="object")
    for zone, d in df.groupby("zone"):
        k = min(k_per_zone[zone], len(d))
        km = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(
            to_km(d, ONSHORE_LAT0), sample_weight=d["capacity_kw"].to_numpy()
        )
        labels.loc[d.index] = [f"{zone}_on_{c:02d}" for c in km.labels_]
    return labels


def cluster_offshore(
    df: pd.DataFrame,
    gap_km: float = OFFSHORE_GAP_KM,
    min_mw: float = MIN_OFFSHORE_CLUSTER_MW,
) -> pd.Series:
    """Group offshore turbines that are chained within gap_km of each other.

    Clusters under min_mw are merged into the nearest larger cluster.
    Returns IDs like 'TenneT_off_03', numbered by capacity (00 = largest).
    """
    labels = pd.Series(index=df.index, dtype="object")
    for zone, d in df.groupby("zone"):
        X = to_km(d, OFFSHORE_LAT0)
        if len(d) == 1:
            raw = np.array([0])
        else:
            raw = (
                AgglomerativeClustering(
                    n_clusters=None, distance_threshold=gap_km, linkage="single"
                )
                .fit(X)
                .labels_
            )
        raw = pd.Series(raw, index=d.index)

        mw = d["capacity_kw"].groupby(raw).sum() / 1000
        centres = pd.DataFrame(X, index=d.index).groupby(raw).mean()
        big = mw[mw >= min_mw].index
        if len(big) == 0:
            big = mw.index
        for small in mw.index.difference(big):
            dist = np.linalg.norm(
                centres.loc[big].to_numpy() - centres.loc[small].to_numpy(), axis=1
            )
            raw[raw == small] = big[np.argmin(dist)]
            log.info("%s offshore: merged %.1f MW cluster into nearest", zone, mw[small])

        order = d["capacity_kw"].groupby(raw).sum().sort_values(ascending=False).index
        mapping = {old: f"{zone}_off_{i:02d}" for i, old in enumerate(order)}
        labels.loc[d.index] = raw.map(mapping)
    return labels


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """One row per cluster: capacity-weighted centre, size, capacity today, hub height."""
    lo, hi = HUB_HEIGHT_RANGE_M
    rows = []
    for cid, g in df.groupby("cluster_id"):
        w = g["capacity_kw"].clip(lower=0) + 1e-6
        hub = g["hub_height_m"].between(lo, hi)
        running = g["decommissioned"].isna()
        rows.append(
            {
                "cluster_id": cid,
                "zone": g["zone"].iloc[0],
                "location_type": g["location_type"].iloc[0],
                "lat": np.average(g["lat"], weights=w),
                "lon": np.average(g["lon"], weights=w),
                "n_turbines": len(g),
                "capacity_mw_now": g.loc[running, "capacity_kw"].sum() / 1000,
                "hub_height_m": (
                    np.average(g.loc[hub, "hub_height_m"], weights=w[hub]) if hub.any() else np.nan
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("cluster_id").reset_index(drop=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t = pd.read_parquet(TURBINES_PATH)
    active = t[t["decommissioned"].isna() | (t["decommissioned"] >= ACTIVE_SINCE)].copy()
    log.info("Clustering %d turbines active since %s", len(active), ACTIVE_SINCE)

    onshore = active["location_type"] == "onshore"
    active["cluster_id"] = None
    active.loc[onshore, "cluster_id"] = cluster_onshore(active[onshore])
    active.loc[~onshore, "cluster_id"] = cluster_offshore(active[~onshore])

    clusters = summarize(active)
    overview = clusters.groupby(["zone", "location_type"]).agg(
        clusters=("cluster_id", "count"),
        gw_now=("capacity_mw_now", lambda s: round(s.sum() / 1000, 2)),
        hub_m=("hub_height_m", lambda s: round(s.median())),
    )
    log.info("Clusters:\n%s", overview.to_string())

    clusters.to_parquet(CLUSTERS_PATH, index=False)
    active[["unit_id", "cluster_id"]].to_parquet(MEMBERS_PATH, index=False)
    log.info("Wrote %d clusters to %s", len(clusters), CLUSTERS_PATH)


if __name__ == "__main__":
    main()
