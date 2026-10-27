# Data sources

Last checked: 2026-10-27

## 1. ENTSO-E Transparency Platform

What: actual wind generation and TSO day-ahead wind forecasts per German TSO zone.
Role in project: target (actuals) and benchmark (TSO forecast).

- Access: REST API with personal token, via the `entsoe-py` library. Token is kept in macOS Keychain / `.env`, never in the repo.
- Actuals: document type A75 (actual generation per production type)
- TSO forecast: document type A69 (wind and solar forecast), day-ahead
- Production types: B19 = wind onshore, B18 = wind offshore

| Zone | EIC code | entsoe-py name |
|---|---|---|
| 50Hertz | 10YDE-VE-------2 | DE_50HZ |
| Amprion | 10YDE-RWENET---I | DE_AMPRION |
| TenneT | 10YDE-EON------1 | DE_TENNET |
| TransnetBW | 10YDE-ENBW-----N | DE_TRANSNET |

Quirks:
- Resolution is 15 min for both actuals and forecasts.
- Timestamps come in Europe/Berlin local time; convert to UTC on load.
- Actuals come back with two-level columns ("Actual Aggregated" / "Actual Consumption"); take "Actual Aggregated".
- Amprion and TransnetBW have no offshore wind (NaN columns).
- TSO forecast jumps at midnight, because each day is a separate forecast.
- TSOs may publish or update the day-ahead forecast as late as 18:00 on D-1, after the 12:00 auction (check). If so, they use fresher weather than our 10:00 issue time.
- License / terms of reuse: check ENTSO-E terms of use before publishing results.

## 2. Marktstammdatenregister (MaStR)

What: official register of all power generating units in Germany (Bundesnetzagentur).
Role in project: turbine locations, capacity, hub height, dates, zone.

- Access: bulk XML download via `open-mastr` (`Mastr().download(data=["wind"])`), stored in local SQLite at `~/.open-MaStR/data/sqlite/open-mastr.db`.
- Update: daily.
- Read from table `EinheitenWind`, not the view `wind_extended` (the view misses newly added columns).
- License: Datenlizenz Deutschland Namensnennung 2.0 (check).

Key columns: EinheitMastrNummer (ID), EinheitBetriebsstatus (status), WindAnLandOderAufSee (onshore/offshore), Seelage, VorlaeufigeRegelzonenDerEinheit (control zone), Nettonennleistung (kW), Nabenhoehe, Rotordurchmesser, Hersteller, Typenbezeichnung, Laengengrad, Breitengrad, Bundesland, Landkreis, Postleitzahl, Gemeinde, Inbetriebnahmedatum, DatumEndgueltigeStilllegung, NameWindpark.

Snapshot 2026-10-27:
- 44,333 units total: 32,259 in operation, 8,838 planned, 3,149 permanently shut down, 87 temporarily shut down.
- In operation: 30,442 onshore (71.5 GW), 1,817 offshore (11.6 GW).

Quirks:
- Capacity is in kW.
- Keep shut-down units: needed to rebuild historical capacity from commissioning/decommissioning dates.
- Control zone column is only ~7% filled. Codes worked out from crosstab with Bundesland:
  - 1000001 = 50Hertz
  - 1001564 = TenneT
  - 1000010 = Amprion
  - 1001572 = TransnetBW
- Niedersachsen, NRW, Hessen and Bayern are split between two TSO zones, so Bundesland alone can't assign zones there.
- 1,332 units without coordinates, only 48 MW total (median 5 kW, mostly mini turbines).
- Some coordinates are clearly wrong (e.g. lon -3.62, lon 17.49, lat 60.0). Count: FILL IN from notebook 02.
- Hub height has junk values (min 1 m, max 300 m); needs sensible limits.

## 3. Open-Meteo

What: archived numerical weather forecasts.
Role in project: model input (wind speed at hub height at turbine cluster locations).

Main source: Single Runs API
- Endpoint: https://single-runs-api.open-meteo.com/v1/forecast
- Parameter `run` = model initialisation time in UTC, e.g. `run=2026-10-15T00:00`
- We use ECMWF IFS HRES 9 km (`models=ecmwf_ifs`), 00 UTC run of D-1.
- Available from 2024-03-14 (tested: 2024-03-13 returns error).
- Other models (incl. ICON) only from 2026-04-02 (tested).
- A 00 UTC global run is usually available from about 04-06 UTC, so it is ready before our 10:00 Berlin issue time.

Secondary: Previous Runs API
- Endpoint: https://previous-runs-api.open-meteo.com/v1/forecast
- `_previous_dayN` = value predicted N x 24 h before the valid time (fixed offset, not a fixed run).
- `previous_day1` leaks: for later hours of the target day it comes from runs made after our 10:00 cutoff.
- `previous_day2` never leaks but is staler than what we really have.
- Most models archived from January 2024.

Heights (tested at one location):
- icon_seamless: 10, 80, 100, 120, 180 m
- ecmwf_ifs025: 10, 80, 100, 120 m (no 180 m); 80/120 m may be derived by Open-Meteo (check)

Speed and limits:
- 10 locations in one call: 0.32 s.
- Backfill 2024-03-14 to 2026-10-27: 957 runs. 100 locations = 95,700 location-runs; 200 = 191,400.
- Free tier is non-commercial only, with a daily call limit; large multi-location requests count as several calls (check current numbers on the Open-Meteo pricing/terms page).
- License: CC BY 4.0, attribution "Weather data by Open-Meteo.com" required.
