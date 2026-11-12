select
    cluster_id,
    zone,
    location_type,
    lat,
    lon,
    n_turbines,
    capacity_mw_now,
    hub_height_m
from {{ source('raw', 'clusters') }}
