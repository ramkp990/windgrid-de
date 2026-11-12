"""Download archived ECMWF runs for all clusters into raw Parquet, one file per run.

Resumable: skips runs already on disk, stops at a daily call budget, newest runs first.

Usage:
    uv run python -m ingestion.weather_job
    uv run python -m ingestion.weather_job --start 2026-11-01 --end 2026-11-05
    uv run python -m ingestion.weather_job --budget 5000
"""

import argparse
import hashlib
import logging
import os
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from ingestion.openmeteo_client import MODEL, OpenMeteoClient, RunNotAvailableError

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "openmeteo" / MODEL
CLUSTERS_PATH = ROOT / "data" / "processed" / "clusters.parquet"
MISSING_FILE = "_missing_runs.txt"

ARCHIVE_START = "2024-03-14"
RUN_HOUR_UTC = 0
DAILY_BUDGET = 8000
RECENT_DAYS = 2


def clusters_hash(clusters: pd.DataFrame) -> str:
    """Short fingerprint of cluster IDs and positions, stored in every file."""
    key = (
        clusters[["cluster_id", "lat", "lon"]]
        .sort_values("cluster_id")
        .round(5)
        .to_csv(index=False)
    )
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def run_path(out_dir: Path, run: pd.Timestamp) -> Path:
    return out_dir / f"run_date={run.date().isoformat()}" / "part.parquet"


def read_missing(out_dir: Path) -> set[str]:
    path = out_dir / MISSING_FILE
    return set(path.read_text().split()) if path.exists() else set()


def add_missing(out_dir: Path, run: pd.Timestamp) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / MISSING_FILE, "a") as f:
        f.write(run.date().isoformat() + "\n")


def runs_to_fetch(start_date: str, end_date: str, out_dir: Path) -> list[pd.Timestamp]:
    """All daily runs in the range not on disk and not known missing, newest first."""
    missing = read_missing(out_dir)
    runs = [
        d.tz_localize("UTC") + pd.Timedelta(hours=RUN_HOUR_UTC)
        for d in pd.date_range(start_date, end_date, freq="D")
    ]
    todo = [
        r for r in runs if not run_path(out_dir, r).exists() and r.date().isoformat() not in missing
    ]
    return sorted(todo, reverse=True)


def write_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def run(
    start_date: str = ARCHIVE_START,
    end_date: str | None = None,
    budget: int = DAILY_BUDGET,
    client=None,
    clusters: pd.DataFrame | None = None,
    out_dir: Path = RAW_DIR,
    now: pd.Timestamp | None = None,
) -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    end_date = end_date or now.date().isoformat()
    clusters = clusters if clusters is not None else pd.read_parquet(CLUSTERS_PATH)
    client = client or OpenMeteoClient()
    chash = clusters_hash(clusters)

    max_runs = budget // len(clusters)
    todo = runs_to_fetch(start_date, end_date, out_dir)
    batch = todo[:max_runs]
    log.info(
        "%d runs to fetch, budget allows %d now (%d clusters per run)",
        len(todo),
        max_runs,
        len(clusters),
    )

    stats = {"fetched": 0, "not_available": 0, "remaining": 0, "stopped_on_limit": False}
    with logging_redirect_tqdm():
        bar = tqdm(batch, desc="Weather runs", unit="run")
        for r in bar:
            bar.set_postfix(
                run=str(r.date()),
                saved=stats["fetched"],
                missing=stats["not_available"],
            )
            try:
                df = client.fetch_run(r, clusters)
            except RunNotAvailableError:
                stats["not_available"] += 1
                if now - r > pd.Timedelta(days=RECENT_DAYS):
                    add_missing(out_dir, r)
                    log.warning("Run %s not in archive, recorded as missing", r.date())
                else:
                    log.info("Run %s not published yet, will retry next time", r.date())
                continue
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    log.warning(
                        "Open-Meteo limit reached (%s). Stopping; run again tomorrow.",
                        e.response.text[:200],
                    )
                    stats["stopped_on_limit"] = True
                    break
                raise

            df["loaded_at_utc"] = pd.Timestamp.now(tz="UTC")
            df["source"] = "open-meteo single-runs"
            df["model"] = MODEL
            df["clusters_hash"] = chash
            write_atomic(df, run_path(out_dir, r))
            stats["fetched"] += 1
        # log.info("Saved run %s (%d rows), %d/%d", r.date(), len(df), stats["fetched"], len(batch))
    stats["remaining"] = len(todo) - stats["fetched"] - stats["not_available"]
    log.info("Done: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Download archived ECMWF runs for all clusters")
    parser.add_argument("--start", default=ARCHIVE_START, help="First run date, YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Last run date, YYYY-MM-DD (default: today)")
    parser.add_argument("--budget", type=int, default=DAILY_BUDGET, help="Max API calls this time")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.start, args.end, args.budget)


if __name__ == "__main__":
    main()
