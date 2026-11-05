import pandas as pd

from ingestion.entsoe_job import month_chunks, run


class FakeClient:
    """Returns 1 MW onshore for every quarter-hour, including the end timestamp on purpose."""

    def actual_wind(self, zone, start, end):
        ts = pd.date_range(start, end, freq="15min", inclusive="both").tz_convert("UTC")
        return pd.DataFrame(
            {"timestamp_utc": ts, "zone": zone, "location_type": "onshore", "mw": 1.0}
        )


def read_day(root, day):
    return pd.read_parquet(root / "actual_wind" / f"date={day}" / "part.parquet")


def test_month_chunks_split_at_month_start():
    chunks = list(month_chunks("2026-10-15", "2026-11-03"))
    assert [(s.date().isoformat(), e.date().isoformat()) for s, e in chunks] == [
        ("2026-10-15", "2026-11-01"),
        ("2026-11-01", "2026-11-04"),
    ]


def test_run_writes_one_partition_per_berlin_day_including_dst(tmp_path):
    days = run("actual", "2026-10-24", "2026-10-26", client=FakeClient(), out_dir=tmp_path)

    assert days == 3
    assert len(read_day(tmp_path, "2026-10-24")) == 96 * 4
    assert len(read_day(tmp_path, "2026-10-25")) == 100 * 4
    assert len(read_day(tmp_path, "2026-10-26")) == 96 * 4
    assert not (tmp_path / "actual_wind" / "date=2026-10-27").exists()


def test_run_is_idempotent_and_adds_metadata(tmp_path):
    run("actual", "2026-10-24", "2026-10-24", client=FakeClient(), out_dir=tmp_path)
    run("actual", "2026-10-24", "2026-10-24", client=FakeClient(), out_dir=tmp_path)
    df = read_day(tmp_path, "2026-10-24")

    assert len(df) == 96 * 4
    assert not df.duplicated(["timestamp_utc", "zone", "location_type"]).any()
    for col in ["loaded_at_utc", "source", "document_type", "source_version"]:
        assert col in df.columns
