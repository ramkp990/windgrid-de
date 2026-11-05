"""ENTSO-E client for German wind data: retries, throttling, UTC long format."""

import logging
import os
import subprocess
import time
from collections.abc import Callable

import pandas as pd
import requests
from dotenv import load_dotenv
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError

log = logging.getLogger(__name__)

ZONES = {
    "50Hertz": "DE_50HZ",
    "Amprion": "DE_AMPRION",
    "TenneT": "DE_TENNET",
    "TransnetBW": "DE_TRANSNET",
}
WIND_COLUMNS = {"Wind Onshore": "onshore", "Wind Offshore": "offshore"}
OUTPUT_COLUMNS = ["timestamp_utc", "zone", "location_type", "mw"]

MIN_SECONDS_BETWEEN_CALLS = 0.25
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0
KEYCHAIN_SERVICE = "wind_de"


def get_api_key() -> str:
    """API key from ENTSOE_API_KEY (env or .env), else from the macOS Keychain."""
    load_dotenv()
    key = os.environ.get("ENTSOE_API_KEY")
    if key:
        return key
    try:
        return subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                os.environ["USER"],
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (FileNotFoundError, KeyError, subprocess.CalledProcessError) as e:
        raise RuntimeError(
            "No ENTSO-E API key: set ENTSOE_API_KEY or store it in the macOS Keychain"
        ) from e


def is_retryable(exc: Exception) -> bool:
    """Temporary failures worth retrying: connection problems, timeouts, 429 and 5xx."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


def to_long(raw: pd.DataFrame, zone: str) -> pd.DataFrame:
    """Normalise entsoe-py output to timestamp_utc, zone, location_type, mw (wind only)."""
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs("Actual Aggregated", axis=1, level=1)
    wind = raw.reindex(columns=list(WIND_COLUMNS)).rename(columns=WIND_COLUMNS)
    wind.index = wind.index.tz_convert("UTC")
    wind.index.name = "timestamp_utc"

    out = wind.reset_index().melt(
        id_vars="timestamp_utc", var_name="location_type", value_name="mw"
    )
    out = out.dropna(subset=["mw"])
    out.insert(1, "zone", zone)
    return out.sort_values(["location_type", "timestamp_utc"]).reset_index(drop=True)[
        OUTPUT_COLUMNS
    ]


class EntsoeWindClient:
    """Wind actuals and TSO day-ahead forecasts per German TSO zone."""

    def __init__(
        self,
        api_key: str | None = None,
        min_interval: float = MIN_SECONDS_BETWEEN_CALLS,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = EntsoePandasClient(api_key=api_key or get_api_key())
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._last_call = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()

    def _call(self, method: str, *args, **kwargs):
        for attempt in range(1, self._max_attempts + 1):
            self._throttle()
            try:
                return getattr(self._client, method)(*args, **kwargs)
            except Exception as exc:
                if not is_retryable(exc) or attempt == self._max_attempts:
                    raise
                wait = min(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1), BACKOFF_MAX_SECONDS)
                log.warning(
                    "%s failed (%s), retry %d/%d in %.0f s",
                    method,
                    exc,
                    attempt,
                    self._max_attempts - 1,
                    wait,
                )
                self._sleep(wait)

    def _fetch(self, method: str, zone: str, start: pd.Timestamp, end: pd.Timestamp):
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        try:
            raw = self._call(method, ZONES[zone], start=start, end=end)
        except NoMatchingDataError:
            log.warning("No data: %s %s %s to %s", method, zone, start, end)
            return pd.DataFrame(columns=OUTPUT_COLUMNS)
        return to_long(raw, zone)

    def actual_wind(self, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Actual wind generation (A75), MW per 15 min, onshore and offshore."""
        return self._fetch("query_generation", zone, start, end)

    def forecast_wind(self, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """TSO day-ahead wind forecast (A69), MW per 15 min, onshore and offshore."""
        return self._fetch("query_wind_and_solar_forecast", zone, start, end)
