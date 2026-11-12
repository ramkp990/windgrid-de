import pandas as pd
import requests

from ingestion.openmeteo_client import RunNotAvailableError
from ingestion.weather_job import MISSING_FILE, run

NOW = pd.Timestamp("2026-11-05 12:00", tz="UTC")
CLUSTERS = pd.DataFrame({"cluster_id": [f"c{i}" for i in range(10)], "lat": 50.0, "lon": 8.0})


class FakeClient:
    def __init__(self, unavailable=(), limit_after=None, fail_on=()):
        self.unavailable = {pd.Timestamp(d, tz="UTC") for d in unavailable}
        self.limit_after = limit_after
        self.fail_on = {pd.Timestamp(d, tz="UTC") for d in fail_on}
        self.calls = []

    def fetch_run(self, run, clusters):
        self.calls.append(run.date().isoformat())
        if self.limit_after is not None and len(self.calls) > self.limit_after:
            resp = requests.Response()
            resp.status_code = 429
            resp._content = b'{"reason":"Daily API request limit exceeded"}'
            raise requests.HTTPError(response=resp)
        if run in self.fail_on:
            raise requests.Timeout("read timed out")
        if run in self.unavailable:
            raise RunNotAvailableError("not available")
        return pd.DataFrame(
            {
                "run_utc": run,
                "cluster_id": clusters["cluster_id"],
                "timestamp_utc": run,
                "lead_hours": 0.0,
                "wind_speed_100m": 7.0,
            }
        )


def go(tmp_path, start, end, budget=1000, fake=None):
    fake = fake or FakeClient()
    stats = run(start, end, budget, client=fake, clusters=CLUSTERS, out_dir=tmp_path, now=NOW)
    return stats, fake


def test_newest_first_within_budget(tmp_path):
    stats, fake = go(tmp_path, "2026-10-01", "2026-10-05", budget=30)
    assert stats == {
        "fetched": 3,
        "not_available": 0,
        "failed": 0,
        "remaining": 2,
        "stopped_on_limit": False,
        "stopped_on_errors": False,
    }
    assert fake.calls == ["2026-10-05", "2026-10-04", "2026-10-03"]
    # assert stats == {"fetched": 3, "not_available": 0, "remaining": 2}


def test_resumes_and_skips_existing(tmp_path):
    go(tmp_path, "2026-10-01", "2026-10-05", budget=30)
    _, second = go(tmp_path, "2026-10-01", "2026-10-05", budget=30)
    stats, third = go(tmp_path, "2026-10-01", "2026-10-05", budget=30)

    assert second.calls == ["2026-10-02", "2026-10-01"]
    assert third.calls == []
    assert stats["fetched"] == 0


def test_old_missing_run_recorded_and_skipped(tmp_path):
    go(tmp_path, "2026-10-01", "2026-10-03", fake=FakeClient(unavailable=["2026-10-02"]))
    _, again = go(tmp_path, "2026-10-01", "2026-10-03")

    assert (tmp_path / MISSING_FILE).read_text().split() == ["2026-10-02"]
    assert again.calls == []


def test_recent_unavailable_run_is_retried_later(tmp_path):
    go(tmp_path, "2026-11-04", "2026-11-05", fake=FakeClient(unavailable=["2026-11-05"]))
    _, again = go(tmp_path, "2026-11-04", "2026-11-05")

    assert not (tmp_path / MISSING_FILE).exists()
    assert again.calls == ["2026-11-05"]


def test_stops_cleanly_when_limit_is_reached(tmp_path):
    stats, fake = go(tmp_path, "2026-10-01", "2026-10-05", fake=FakeClient(limit_after=2))

    assert stats["stopped_on_limit"] is True
    assert stats["fetched"] == 2
    assert stats["remaining"] == 3
    assert len(list(tmp_path.glob("run_date=*/part.parquet"))) == 2


def test_skips_failed_run_and_continues(tmp_path):
    stats, fake = go(tmp_path, "2026-10-01", "2026-10-05", fake=FakeClient(fail_on=["2026-10-04"]))

    assert stats["fetched"] == 4
    assert stats["failed"] == 1
    assert stats["remaining"] == 1
    assert not (tmp_path / "run_date=2026-10-04").exists()


def test_stops_after_three_failures_in_a_row(tmp_path):
    days = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"]
    stats, fake = go(tmp_path, "2026-10-01", "2026-10-05", fake=FakeClient(fail_on=days))

    assert stats["stopped_on_errors"] is True
    assert stats["failed"] == 3
    assert len(fake.calls) == 3
