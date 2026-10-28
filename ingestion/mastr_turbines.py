"""Load MaStR wind units, drop never-built units, flag missing coordinates."""

import logging
import os
from pathlib import Path

import pandas as pd
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db_path = Path(os.environ.get("MASTR_DB_PATH", DEFAULT_DB))

    df = load_wind_units(db_path)
    df = filter_built(df)
    df = flag_missing_coords(df)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    log.info("Wrote %d units to %s", len(df), OUT_PATH)


if __name__ == "__main__":
    main()
