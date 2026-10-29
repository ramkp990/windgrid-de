"""Load MaStR wind units, drop never-built units, flag missing coordinates."""

import logging
import os
from pathlib import Path

import pandas as pd
from sklearn.neighbors import KNeighborsClassifier
from sqlalchemy import create_engine

log = logging.getLogger(__name__)

DEFAULT_DB = Path.home() / ".open-MaStR" / "data" / "sqlite" / "open-mastr.db"
# OUT_PATH = Path("data/interim/turbines_stage1.parquet")
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "interim" / "turbines_stage1.parquet"

COLUMNS = {
    "EinheitMastrNummer": "unit_id",
    "EinheitBetriebsstatus": "status",
    "WindAnLandOderAufSee": "location_type",
    "Seelage": "sea",
    "VorlaeufigeRegelzonenDerEinheit": "control_zone_code",
    "Nettonennleistung": "capacity_kw",
    "Nabenhoehe": "hub_height_m",
    "Rotordurchmesser": "rotor_diameter_m",
    "Hersteller": "manufacturer",
    "Typenbezeichnung": "model",
    "Laengengrad": "lon",
    "Breitengrad": "lat",
    "Bundesland": "state",
    "Landkreis": "district",
    "Postleitzahl": "postcode",
    "Gemeinde": "municipality",
    "Inbetriebnahmedatum": "commissioned",
    "DatumEndgueltigeStilllegung": "decommissioned",
    "NameWindpark": "wind_farm",
}

STATUS_EN = {
    "In Betrieb": "operating",
    "In Planung": "planned",
    "Endgültig stillgelegt": "decommissioned",
    "Vorübergehend stillgelegt": "temporarily_shut_down",
}

LOCATION_EN = {
    "Windenergie an Land": "onshore",
    "Windenergie auf See": "offshore",
}

# (lon_min, lon_max, lat_min, lat_max)
ONSHORE_BOX = (5.8, 15.1, 47.2, 55.1)
NORTH_SEA_BOX = (3.3, 9.0, 53.3, 56.0)
BALTIC_BOX = (10.0, 15.0, 53.9, 55.1)

IMPUTE_LEVELS = [
    ["wind_farm", "district"],
    ["postcode"],
    ["municipality", "state"],
    ["district", "state"],
]

MAX_FARM_SPREAD_DEG = 0.05

CODE_TO_ZONE = {
    1000001: "50Hertz",
    1001564: "TenneT",
    1000010: "Amprion",
    1001572: "TransnetBW",
}

STATE_TO_ZONE = {
    "Berlin": "50Hertz",
    "Brandenburg": "50Hertz",
    "Hamburg": "50Hertz",
    "Mecklenburg-Vorpommern": "50Hertz",
    "Sachsen": "50Hertz",
    "Sachsen-Anhalt": "50Hertz",
    "Thüringen": "50Hertz",
    "Schleswig-Holstein": "TenneT",
    "Bremen": "TenneT",
    "Rheinland-Pfalz": "Amprion",
    "Saarland": "Amprion",
    "Baden-Württemberg": "TransnetBW",
}

SPLIT_STATES = {"Niedersachsen", "Nordrhein-Westfalen", "Hessen", "Bayern"}
SPLIT_ZONES = {"TenneT", "Amprion"}
KNN_NEIGHBOURS = 5


def load_wind_units(db_path: Path = DEFAULT_DB) -> pd.DataFrame:
    """Read wind units from the open-mastr SQLite DB with English column names."""
    engine = create_engine(f"sqlite:///{db_path}")
    cols = ", ".join(f'"{c}"' for c in COLUMNS)
    df = pd.read_sql(f"SELECT {cols} FROM EinheitenWind", con=engine)
    df = df.rename(columns=COLUMNS)

    df["status"] = df["status"].map(STATUS_EN).fillna(df["status"])
    df["location_type"] = df["location_type"].map(LOCATION_EN).fillna(df["location_type"])
    df["commissioned"] = pd.to_datetime(df["commissioned"], errors="coerce")
    df["decommissioned"] = pd.to_datetime(df["decommissioned"], errors="coerce")
    df["control_zone_code"] = pd.to_numeric(df["control_zone_code"], errors="coerce").astype(
        "Int64"
    )
    df["postcode"] = df["postcode"].astype("string")

    log.info("Loaded %d wind units", len(df))
    return df


def filter_built(df: pd.DataFrame) -> pd.DataFrame:
    """Drop planned units and units that never got a commissioning date."""
    planned = df["status"] == "planned"
    no_date = df["commissioned"].isna()

    log.info("Dropping %d planned units", planned.sum())
    log.info("Dropping %d other units without commissioning date", (~planned & no_date).sum())

    return df[~planned & ~no_date].reset_index(drop=True)


def flag_missing_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Add has_coords column. Units without coordinates are kept, not dropped."""
    df = df.copy()
    df["has_coords"] = df["lon"].notna() & df["lat"].notna()

    missing = ~df["has_coords"]
    log.info(
        "%d units without coordinates (%.0f MW)",
        missing.sum(),
        df.loc[missing, "capacity_kw"].sum() / 1000,
    )
    return df


def _in_box(df: pd.DataFrame, box: tuple[float, float, float, float]) -> pd.Series:
    lon_min, lon_max, lat_min, lat_max = box
    return df["lon"].between(lon_min, lon_max) & df["lat"].between(lat_min, lat_max)


def flag_bad_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Add coords_ok column: True if coordinates exist and lie in the expected area."""
    df = df.copy()
    offshore = df["location_type"] == "offshore"
    in_land = _in_box(df, ONSHORE_BOX)
    in_sea = _in_box(df, NORTH_SEA_BOX) | _in_box(df, BALTIC_BOX)

    df["coords_ok"] = df["has_coords"] & ((~offshore & in_land) | (offshore & in_sea))

    bad = df["has_coords"] & ~df["coords_ok"]
    log.info(
        "%d units with coordinates outside expected area (%.0f MW)",
        bad.sum(),
        df.loc[bad, "capacity_kw"].sum() / 1000,
    )
    cols = ["unit_id", "status", "location_type", "state", "lon", "lat", "capacity_kw"]
    log.info(
        "Largest of them:\n%s",
        df.loc[bad, cols].nlargest(10, "capacity_kw").to_string(index=False),
    )
    return df


def impute_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing or bad coordinates with the centroid of good units at the same place.

    Tries wind farm, postcode, municipality, district in that order.
    Offshore units are only imputed from their wind farm.
    Adds coord_source: 'mastr', the level used, or None if no match.
    """
    df = df.copy()
    df["coord_source"] = df["coords_ok"].map({True: "mastr", False: None})
    good = df[df["coords_ok"]]
    offshore = df["location_type"] == "offshore"

    for keys in IMPUTE_LEVELS:
        level = "_".join(keys)
        # centroids = good.groupby(keys)[["lon", "lat"]].mean().add_suffix("_c").reset_index()
        grouped = good.groupby(keys)[["lon", "lat"]]
        centroids = grouped.median().add_suffix("_c")
        if keys[0] == "wind_farm":
            spread = grouped.std().fillna(0).max(axis=1)
            centroids = centroids[spread < MAX_FARM_SPREAD_DEG]
        centroids = centroids.reset_index()

        todo = df["coord_source"].isna()
        if keys[0] != "wind_farm":
            todo &= ~offshore

        cand = (
            df.loc[todo, keys]
            .reset_index()
            .merge(centroids, on=keys, how="left")
            .set_index("index")
            .dropna(subset=["lon_c"])
        )
        df.loc[cand.index, "lon"] = cand["lon_c"]
        df.loc[cand.index, "lat"] = cand["lat_c"]
        df.loc[cand.index, "coord_source"] = level
        log.info("Imputed %d units from %s centroid", len(cand), level)

    left = df["coord_source"].isna()
    log.info(
        "%d units still without usable coordinates (%.0f MW)",
        left.sum(),
        df.loc[left, "capacity_kw"].sum() / 1000,
    )
    return df


def assign_zone(df: pd.DataFrame, k: int = KNN_NEIGHBOURS) -> pd.DataFrame:
    """Assign each unit to a TSO zone. Adds zone and zone_source columns.

    Order: MaStR zone code, offshore by sea, onshore by federal state,
    onshore in split states by k nearest TenneT/Amprion neighbours.
    """
    df = df.copy()
    df["zone"] = df["control_zone_code"].map(CODE_TO_ZONE)
    df["zone_source"] = df["zone"].notna().map({True: "mastr_code", False: None})

    offshore = df["location_type"] == "offshore"
    has_xy = df["coord_source"].notna()

    todo = df["zone"].isna() & offshore
    baltic = df["sea"].astype("string").str.contains("Ost", na=False) | (
        df["sea"].isna() & (df["lon"] > 10)
    )
    df.loc[todo, "zone"] = baltic[todo].map({True: "50Hertz", False: "TenneT"})
    df.loc[todo, "zone_source"] = "offshore_sea"

    todo = df["zone"].isna() & ~offshore
    by_state = df.loc[todo, "state"].map(STATE_TO_ZONE).dropna()
    df.loc[by_state.index, "zone"] = by_state
    df.loc[by_state.index, "zone_source"] = "state"

    train = df[df["zone"].isin(SPLIT_ZONES) & ~offshore & has_xy]
    todo = df["zone"].isna() & df["state"].isin(SPLIT_STATES) & has_xy
    if todo.any():
        knn = KNeighborsClassifier(n_neighbors=k).fit(train[["lon", "lat"]], train["zone"])
        df.loc[todo, "zone"] = knn.predict(df.loc[todo, ["lon", "lat"]])
        df.loc[todo, "zone_source"] = "knn"

    log.info("Zone sources:\n%s", df["zone_source"].value_counts(dropna=False).to_string())
    left = df["zone"].isna()
    log.info(
        "%d units without zone (%.0f MW)", left.sum(), df.loc[left, "capacity_kw"].sum() / 1000
    )

    op = df[df["status"] == "operating"]
    gw = op.groupby(["zone", "location_type"])["capacity_kw"].sum().unstack() / 1e6
    log.info("Operating capacity per zone (GW):\n%s", gw.round(2).to_string())
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db_path = Path(os.environ.get("MASTR_DB_PATH", DEFAULT_DB))

    df = load_wind_units(db_path)
    df = filter_built(df)
    df = flag_missing_coords(df)
    df = flag_bad_coords(df)
    df = impute_coords(df)
    df = assign_zone(df)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    log.info("Wrote %d units to %s", len(df), OUT_PATH)


if __name__ == "__main__":
    main()
