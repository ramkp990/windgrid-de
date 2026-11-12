select
    cast(date as date) as date,
    zone,
    location_type,
    capacity_mw
from {{ source('raw', 'capacity_daily') }}
