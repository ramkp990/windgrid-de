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
| 2026-10-27 | Keep raw ENTSO-E data at 15-min; aggregate to hourly mean in dbt | Target is hourly; raw stays untouched so 15-min forecasting is possible later without re-downloading |
| 2026-10-27 | Store all timestamps in UTC, convert only for display | Berlin time has 23 h and 25 h days at DST changes; UTC has none |
| 2026-10-27 | Main weather source: Open-Meteo Single Runs API, ECMWF IFS HRES 9 km, 00 UTC run of D-1 (from 2024-03-14) | Matches exactly what is available at the 10:00 issue time; previous_day1 leaks later runs, previous_day2 is staler than reality |
| 2026-10-27 | ICON via Previous Runs previous_day2 as optional second model | ICON single runs only from 2026-04; day2 never leaks |
