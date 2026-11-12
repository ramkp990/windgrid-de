select
    timezone('UTC', run_utc) as run_utc,
    cluster_id,
    timezone('UTC', timestamp_utc) as timestamp_utc,
    cast(lead_hours as integer) as lead_hours,
    wind_speed_10m,
    wind_speed_100m,
    wind_speed_120m,
    wind_direction_100m,
    temperature_2m,
    surface_pressure,
    clusters_hash,
    timezone('UTC', loaded_at_utc) as loaded_at_utc
from {{ source('raw', 'openmeteo_ecmwf') }}
