"""Open-Meteo Single Runs client: archived ECMWF runs for many locations.

Batches locations, throttles by call weight (each location counts as one call),
retries temporary errors, and returns one row per cluster and hour.
"""

import logging
import time
from collections.abc import Callable

import pandas as pd
import requests

from ingestion.entsoe_client import is_retryable

log = logging.getLogger(__name__)

SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs"
VARIABLES = [
    "wind_speed_10m",
    "wind_speed_100m",
    "wind_speed_120m",
    "wind_direction_100m",
    "temperature_2m",
    "surface_pressure",
]
OUTPUT_COLUMNS = [
    "run_utc",
    "cluster_id",
    "timestamp_utc",
    "lead_hours",
    *VARIABLES,
    "grid_lat",
    "grid_lon",
]
FORECAST_HOURS = 48
BATCH_SIZE = 50
TIMEOUT_SECONDS = 180
SECONDS_PER_LOCATION = 0.75
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 120.0


class RunNotAvailableError(Exception):
    """The requested model run is not in the Open-Meteo archive."""


class BadResponseError(Exception):
    """Status 200, but the body isn't valid JSON (empty or cut off). Usually temporary."""


def parse_response(payload, locations: pd.DataFrame, run: pd.Timestamp) -> pd.DataFrame:
    """Turn the JSON answer (dict for one location, list for several) into one table.

    Open-Meteo returns locations in the order they were requested, so cluster IDs
    are matched by position. grid_lat/grid_lon are the model grid cell actually used.
    """
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(locations):
        raise ValueError(f"Asked for {len(locations)} locations, got {len(items)}")

    frames = []
    for item, cluster_id in zip(items, locations["cluster_id"], strict=True):
        h = pd.DataFrame(item["hourly"])
        h["timestamp_utc"] = pd.to_datetime(h.pop("time"), utc=True)
        h["cluster_id"] = cluster_id
        h["grid_lat"] = item["latitude"]
        h["grid_lon"] = item["longitude"]
        frames.append(h)

    out = pd.concat(frames, ignore_index=True)
    out["run_utc"] = run
    out["lead_hours"] = (out["timestamp_utc"] - run) / pd.Timedelta(hours=1)
    return out.reindex(columns=OUTPUT_COLUMNS)


class OpenMeteoClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        batch_size: int = BATCH_SIZE,
        seconds_per_location: float = SECONDS_PER_LOCATION,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._batch_size = batch_size
        self._seconds_per_location = seconds_per_location
        self._max_attempts = max_attempts
        self._sleep = sleep

    def _get(self, params: dict, weight: int):
        for attempt in range(1, self._max_attempts + 1):
            try:
                r = self._session.get(SINGLE_RUNS_URL, params=params, timeout=TIMEOUT_SECONDS)
                if r.status_code == 400 and "not available" in r.text:
                    raise RunNotAvailableError(r.text[:200])
                r.raise_for_status()
                try:
                    payload = r.json()
                except ValueError as e:
                    raise BadResponseError(
                        f"status {r.status_code}, body starts {r.text[:200]!r}"
                    ) from e
                break
            except Exception as exc:
                retryable = is_retryable(exc) or isinstance(exc, BadResponseError)
                if not retryable or attempt == self._max_attempts:
                    raise
                wait = min(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1), BACKOFF_MAX_SECONDS)
                log.warning(
                    "Open-Meteo failed (%s), retry %d/%d in %.0f s",
                    exc,
                    attempt,
                    self._max_attempts - 1,
                    wait,
                )
                self._sleep(wait)

        self._sleep(weight * self._seconds_per_location)
        return payload

    def fetch_run(self, run: pd.Timestamp, locations: pd.DataFrame) -> pd.DataFrame:
        """One model run for all locations (columns cluster_id, lat, lon)."""
        if run.tzinfo is None:
            raise ValueError("run must be timezone-aware (UTC)")
        run = run.tz_convert("UTC")

        frames = []
        for i in range(0, len(locations), self._batch_size):
            batch = locations.iloc[i : i + self._batch_size]
            params = {
                "latitude": ",".join(f"{x:.4f}" for x in batch["lat"]),
                "longitude": ",".join(f"{x:.4f}" for x in batch["lon"]),
                "run": run.strftime("%Y-%m-%dT%H:%M"),
                "models": MODEL,
                "hourly": ",".join(VARIABLES),
                "forecast_hours": FORECAST_HOURS,
                "wind_speed_unit": "ms",
                "timezone": "UTC",
            }
            payload = self._get(params, weight=len(batch))
            frames.append(parse_response(payload, batch, run))

        return pd.concat(frames, ignore_index=True)
