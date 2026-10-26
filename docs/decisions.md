# Decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-10-26 | Target is hourly capacity factor per TSO zone, onshore and offshore separately | Makes zones comparable and removes the effect of capacity growth |
| 2026-10-26 | Forecast horizon is next day 00:00-23:00, issued around 10:00 | Has to be ready before the 12:00 day-ahead auction |
| 2026-10-26 | Main weather source is the Open-Meteo Previous Runs API | Real archived forecasts from 2024, so no leakage from later model runs |
| 2026-10-26 | Historical Forecast API (2021+) only as an experiment | More data, but needs checking against Previous Runs first |
| 2026-10-26 | Benchmark is the ENTSO-E TSO day-ahead wind forecast | Official forecast, freely available, same zones |
| 2026-10-26 | No GPU | Runs on a cheap VM and a laptop |
| 2026-10-26 | Public repo, MIT license | Results are meant to be public and shown on CV |
| 2026-10-26 | uv for project and dependency management | Fast, lockfile, installs Python itself |
| 2026-10-26 | Python 3.12 | All planned libraries (Dagster, dbt, LightGBM, GPyTorch) support it; 3.13 support is still patchy |
| 2026-10-26 | Ruff rules E, F, I, UP, B, SIM, line length 100 | Catches real bugs without too much noise |
| 2026-10-26 | CI runner pinned to ubuntu-24.04 | Avoids surprise changes when ubuntu-latest moves to 26 |
