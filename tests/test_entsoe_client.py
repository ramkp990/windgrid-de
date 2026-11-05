import pandas as pd
import pytest
import requests

from ingestion.entsoe_client import EntsoeWindClient, is_retryable, to_long


def berlin_index(n=4):
    return pd.date_range("2026-10-12 00:00", periods=n, freq="15min", tz="Europe/Berlin")


def test_to_long_actuals_multiindex_to_utc():
    cols = pd.MultiIndex.from_tuples(
        [
            ("Wind Onshore", "Actual Aggregated"),
            ("Wind Offshore", "Actual Aggregated"),
            ("Solar", "Actual Aggregated"),
        ]
    )
    raw = pd.DataFrame([[100.0, None, 5.0]] * 4, index=berlin_index(), columns=cols)
    out = to_long(raw, "Amprion")

    assert list(out.columns) == ["timestamp_utc", "zone", "location_type", "mw"]
    assert set(out["location_type"]) == {"onshore"}
    assert out["timestamp_utc"].iloc[0] == pd.Timestamp("2026-10-11 22:00", tz="UTC")


def test_to_long_forecast_plain_columns():
    raw = pd.DataFrame(
        {"Solar": [1.0] * 4, "Wind Offshore": [50.0] * 4, "Wind Onshore": [200.0] * 4},
        index=berlin_index(),
    )
    out = to_long(raw, "TenneT")

    assert sorted(out["location_type"].unique()) == ["offshore", "onshore"]
    assert len(out) == 8


def http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(response=resp)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (requests.ConnectionError(), True),
        (requests.Timeout(), True),
        (http_error(429), True),
        (http_error(503), True),
        (http_error(400), False),
        (ValueError(), False),
    ],
)
def test_is_retryable(exc, expected):
    assert is_retryable(exc) is expected


class FlakyClient:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def query_generation(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("boom")
        return "ok"


def make_client(fake):
    client = EntsoeWindClient(api_key="test", min_interval=0, sleep=lambda s: None)
    client._client = fake
    return client


def test_call_retries_then_succeeds():
    fake = FlakyClient(failures=2)
    assert make_client(fake)._call("query_generation") == "ok"
    assert fake.calls == 3


def test_call_gives_up_after_max_attempts():
    fake = FlakyClient(failures=10)
    with pytest.raises(requests.ConnectionError):
        make_client(fake)._call("query_generation")
    assert fake.calls == 5
