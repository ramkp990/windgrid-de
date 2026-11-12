select
    timezone('UTC', timestamp_utc) as timestamp_utc,
    zone,
    location_type,
    cast(mw as double) as mw,
    cast(date as date) as local_date,
    timezone('UTC', loaded_at_utc) as loaded_at_utc
from {{ source('raw', 'entsoe_forecast_wind') }}
