import pandas as pd
import pytest
import requests

from ingestion.openmeteo_client import VARIABLES, OpenMeteoClient, RunNotAvailableError

RUN = pd.Timestamp("2026-10-15 00:00", tz="UTC")


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def fake_payload(params, hours=3):
    lats = params["latitude"].split(",")
    lons = params["longitude"].split(",")
    times = pd.date_range("2026-10-15", periods=hours, freq="h").strftime("%Y-%m-%dT%H:%M")
    items = [
        {
            "latitude": float(la),
            "longitude": float(lo),
            "hourly": {"time": list(times), **{v: [5.0] * hours for v in VARIABLES}},
        }
        for la, lo in zip(lats, lons, strict=True)
    ]
    return items if len(items) > 1 else items[0]


class FakeSession:
    """Answers with the scripted status codes first, then 200."""

    def __init__(self, statuses=()):
        self.statuses = list(statuses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        status = self.statuses.pop(0) if self.statuses else 200
        if status == 400:
            return FakeResponse(400, text='{"reason":"The requested model run is not available."}')
        if status == "empty":
            return FakeResponse(200, payload=None, text="")
        if status != 200:
            return FakeResponse(status)
        return FakeResponse(200, fake_payload(params))


def locations(n):
    return pd.DataFrame(
        {
            "cluster_id": [f"c{i:03d}" for i in range(n)],
            "lat": [50 + i * 0.01 for i in range(n)],
            "lon": [8 + i * 0.01 for i in range(n)],
        }
    )


def make_client(session, sleeps=None):
    record = sleeps.append if sleeps is not None else (lambda s: None)
    return OpenMeteoClient(session=session, batch_size=100, seconds_per_location=0.5, sleep=record)


def test_batches_locations_and_keeps_cluster_order():
    session = FakeSession()
    out = make_client(session).fetch_run(RUN, locations(250))

    assert len(session.calls) == 3
    assert len(out) == 250 * 3
    assert out["cluster_id"].unique().tolist() == locations(250)["cluster_id"].tolist()
    assert out["lead_hours"].tolist()[:3] == [0.0, 1.0, 2.0]


def test_single_location_answer_is_a_dict():
    out = make_client(FakeSession()).fetch_run(RUN, locations(1))
    assert len(out) == 3
    assert out["cluster_id"].unique().tolist() == ["c000"]


def test_retries_server_error_then_succeeds():
    session = FakeSession(statuses=[503])
    out = make_client(session).fetch_run(RUN, locations(5))
    assert len(session.calls) == 2
    assert len(out) == 15


def test_missing_run_raises_without_retry():
    session = FakeSession(statuses=[400])
    with pytest.raises(RunNotAvailableError):
        make_client(session).fetch_run(RUN, locations(5))
    assert len(session.calls) == 1


def test_throttle_waits_per_location():
    sleeps = []
    make_client(FakeSession(), sleeps).fetch_run(RUN, locations(10))
    assert sleeps == [5.0]


def test_retries_empty_body_then_succeeds():
    session = FakeSession(statuses=["empty"])
    out = make_client(session).fetch_run(RUN, locations(5))
    assert len(session.calls) == 2
    assert len(out) == 15
