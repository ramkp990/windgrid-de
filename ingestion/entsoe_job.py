"""Download ENTSO-E wind data for a date range into raw Parquet, one file per Berlin day.

Usage:
    uv run python -m ingestion.entsoe_job actual --start 2026-10-01 --end 2026-10-31
    uv run python -m ingestion.entsoe_job forecast --start 2026-10-01 --end 2026-10-31
"""

import argparse
import logging
import os
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from ingestion.entsoe_client import ZONES, EntsoeWindClient

log = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "entsoe"
LOCAL_TZ = "Europe/Berlin"
KEY_COLUMNS = ["timestamp_utc", "zone", "location_type"]

DATASETS = {
    "actual": {"folder": "actual_wind", "document_type": "A75", "method": "actual_wind"},
    "forecast": {"folder": "forecast_wind", "document_type": "A69", "method": "forecast_wind"},
}


def month_chunks(start_date: str, end_date: str) -> Iterator[tuple[pd.Timestamp, pd.Timestamp]]:
    """Berlin-midnight (start, end) pairs covering start_date..end_date inclusive, max one month."""
    cur = pd.Timestamp(start_date)
    stop = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    while cur < stop:
        nxt = min(cur + pd.offsets.MonthBegin(1), stop)
        yield cur.tz_localize(LOCAL_TZ), nxt.tz_localize(LOCAL_TZ)
        cur = nxt


def add_metadata(df: pd.DataFrame, document_type: str) -> pd.DataFrame:
    df = df.copy()
    df["loaded_at_utc"] = pd.Timestamp.now(tz="UTC")
    df["source"] = "entsoe"
    df["document_type"] = document_type
    df["source_version"] = f"entsoe-py {version('entsoe-py')}"
    return df


def split_by_local_day(df: pd.DataFrame) -> dict:
    local_date = df["timestamp_utc"].dt.tz_convert(LOCAL_TZ).dt.date
    return dict(tuple(df.groupby(local_date)))


def write_partition(df: pd.DataFrame, dataset_dir: Path, day) -> Path:
    """Write one day's file atomically: temp file first, then rename over the old one."""
    path = dataset_dir / f"date={day.isoformat()}" / "part.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return path


def run(dataset: str, start_date: str, end_date: str, client=None, out_dir: Path = RAW_DIR) -> int:
    """Fetch all zones month by month, write one partition per Berlin day. Returns days written."""
    cfg = DATASETS[dataset]
    client = client or EntsoeWindClient()
    days_written = 0

    for start, end in month_chunks(start_date, end_date):
        frames = [getattr(client, cfg["method"])(zone, start, end) for zone in ZONES]
        frames = [f for f in frames if not f.empty]
        if not frames:
            log.warning("%s %s to %s: no data for any zone", dataset, start.date(), end.date())
            continue

        chunk = pd.concat(frames, ignore_index=True)
        chunk = chunk[(chunk["timestamp_utc"] >= start) & (chunk["timestamp_utc"] < end)]
        chunk = chunk.drop_duplicates(KEY_COLUMNS, keep="last")
        chunk = add_metadata(chunk, cfg["document_type"])

        for day, part in split_by_local_day(chunk).items():
            write_partition(part.reset_index(drop=True), out_dir / cfg["folder"], day)
            days_written += 1
        log.info("%s %s to %s: %d rows", dataset, start.date(), end.date(), len(chunk))

    log.info("Done: %d day partitions written for %s", days_written, dataset)
    return days_written


def main() -> None:
    parser = argparse.ArgumentParser(description="Download ENTSO-E wind data into raw Parquet")
    parser.add_argument("dataset", choices=DATASETS)
    parser.add_argument("--start", required=True, help="First Berlin day, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Last Berlin day, YYYY-MM-DD (inclusive)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.dataset, args.start, args.end)


if __name__ == "__main__":
    main()
