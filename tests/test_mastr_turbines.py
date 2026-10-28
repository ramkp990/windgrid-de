import pandas as pd

from ingestion.mastr_turbines import filter_built, flag_bad_coords, flag_missing_coords


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
