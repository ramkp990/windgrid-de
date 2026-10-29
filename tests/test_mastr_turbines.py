import pandas as pd

from ingestion.mastr_turbines import (
    assign_zone,
    filter_built,
    flag_bad_coords,
    flag_missing_coords,
    impute_coords,
)


def make_units():
    return pd.DataFrame(
        {
            "unit_id": ["A", "B", "C", "D"],
            "status": ["operating", "planned", "decommissioned", "decommissioned"],
            "commissioned": pd.to_datetime(["2015-01-01", None, "2005-06-01", None]),
            "capacity_kw": [3000.0, 5000.0, 600.0, 800.0],
            "lon": [9.0, 10.0, None, 8.0],
            "lat": [53.0, 54.0, None, 52.0],
        }
    )


def test_filter_built_drops_planned_and_undated():
    out = filter_built(make_units())
    assert list(out["unit_id"]) == ["A", "C"]


def test_filter_built_keeps_decommissioned():
    out = filter_built(make_units())
    assert "decommissioned" in set(out["status"])


def test_flag_missing_coords():
    out = flag_missing_coords(make_units())
    assert list(out["has_coords"]) == [True, True, False, True]


def test_flag_bad_coords():
    df = pd.DataFrame(
        {
            "unit_id": ["land_ok", "land_norway", "sea_ok", "sea_on_land", "no_coords"],
            "status": ["operating"] * 5,
            "location_type": ["onshore", "onshore", "offshore", "offshore", "onshore"],
            "state": [None] * 5,
            "lon": [10.0, 10.0, 6.5, 10.0, None],
            "lat": [53.5, 60.0, 54.2, 51.0, None],
            "capacity_kw": [3000.0] * 5,
            "has_coords": [True, True, True, True, False],
        }
    )
    out = flag_bad_coords(df)
    assert list(out["coords_ok"]) == [True, False, True, False, False]


def test_impute_coords():
    df = pd.DataFrame(
        {
            "unit_id": ["good1", "good2", "missing_land", "missing_sea", "no_match"],
            "location_type": ["onshore", "onshore", "onshore", "offshore", "onshore"],
            "wind_farm": [None, None, None, None, None],
            "state": ["SH", "SH", "SH", "SH", "BY"],
            "postcode": ["24000", "24000", "24000", "24000", "80000"],
            "municipality": [None] * 5,
            "district": [None] * 5,
            "lon": [10.0, 10.2, None, None, None],
            "lat": [54.0, 54.2, None, None, None],
            "capacity_kw": [3000.0] * 5,
            "coords_ok": [True, True, False, False, False],
        }
    )
    out = impute_coords(df).set_index("unit_id")

    assert out.loc["missing_land", "coord_source"] == "postcode"
    assert round(out.loc["missing_land", "lon"], 2) == 10.1
    assert pd.isna(out.loc["missing_sea", "coord_source"])
    assert pd.isna(out.loc["no_match", "coord_source"])


def test_impute_skips_spread_out_wind_farm_names():
    df = pd.DataFrame(
        {
            "unit_id": ["a", "b", "missing"],
            "location_type": ["onshore"] * 3,
            "wind_farm": ["Windrad"] * 3,
            "state": ["NRW"] * 3,
            "district": ["X"] * 3,
            "postcode": ["1", "2", "3"],
            "municipality": [None] * 3,
            "lon": [6.0, 9.0, None],
            "lat": [51.0, 52.0, None],
            "capacity_kw": [10.0] * 3,
            "coords_ok": [True, True, False],
        }
    )
    out = impute_coords(df).set_index("unit_id")
    assert out.loc["missing", "coord_source"] == "district_state"


def test_assign_zone():
    df = pd.DataFrame(
        {
            "unit_id": ["coded", "baltic", "north_sea", "sh", "nrw_new", "a1", "a2"],
            "status": ["operating"] * 7,
            "location_type": [
                "onshore",
                "offshore",
                "offshore",
                "onshore",
                "onshore",
                "onshore",
                "onshore",
            ],
            "sea": [None, "Ostsee", "Nordsee", None, None, None, None],
            "control_zone_code": pd.array(
                [1001572, None, None, None, None, 1000010, 1000010], dtype="Int64"
            ),
            "state": [
                "Baden-Württemberg",
                None,
                None,
                "Schleswig-Holstein",
                "Nordrhein-Westfalen",
                "Nordrhein-Westfalen",
                "Nordrhein-Westfalen",
            ],
            "lon": [9.0, 13.0, 6.5, 9.5, 7.0, 7.1, 6.9],
            "lat": [48.5, 54.6, 54.2, 54.3, 51.5, 51.5, 51.4],
            "coord_source": ["mastr"] * 7,
            "capacity_kw": [3000.0] * 7,
        }
    )
    out = assign_zone(df, k=1).set_index("unit_id")

    assert out.loc["coded", "zone"] == "TransnetBW"
    assert out.loc["baltic", "zone"] == "50Hertz"
    assert out.loc["north_sea", "zone"] == "TenneT"
    assert out.loc["sh", "zone"] == "TenneT"
    assert out.loc["nrw_new", "zone"] == "Amprion"
    assert out.loc["nrw_new", "zone_source"] == "knn"
