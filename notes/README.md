# Notes

## stations.json

Station metadata keyed by `<lake_id>_<station_id>` (ASCII; unique across all sources), with `source` naming the entry in `sources.json`. `lake_name` and `station_name` must match the `LAKE` and
`STATION` columns of the Level0 DiMark export exactly.

The Level2 profile depth grid is derived from the data: every depth that occurs is a nominal depth unless it lies within
±0.25 m of a depth sampled on more dates, in which case readings are snapped to that depth. Optional keys:
- `exclude_depths`: depths whose readings stay in Level1 only (e.g. `[0.0]` for the single 0.0 m reading at Bled)
- `profile_depths`: an explicit nominal grid that replaces the derived one (readings further than ±0.25 m from it stay
  in Level1 only)
- `profile_interpolation`: `{"grid": [[start, stop, step], ...], "max_gap": metres or null}` for high-resolution or
  irregular-depth profilers: Level2 profiles are linearly interpolated onto this fixed grid instead of snapped
  (`scripts/inventory.py` says when to use it)

All of these are logged in `corrections/<source>.csv`.

## quality_assurance.json

Hard lower and upper bounds (envass `simple` checks) per variable. `time` bounds are in seconds since
1970-01-01 00:00:00 UTC; `"now"` is replaced by the current time when the pipeline runs.

## events.csv

Rows should be added to the events.csv file as follows:

start;stop;parameter;comments
20150101 00:00:00;20151231 23:59:59;All;Example: flag everything at every station
20150101 00:00:00;20151231 23:59:59;Temp;Example: flag temperature at every station
20150101 00:00:00;20151231 23:59:59;bled_zahodna_kotanja/Temp;Example: flag temperature at one station only

***
It is important that the start and stop datetimes exactly follow the pattern above (YYYYMMDD HH:MM:SS, UTC) and that
the parameter is "All", one of Temp, Chla_probe, Chla_lab, Secchi, TN, TP, NH4, NO3, NO2, or one of those prefixed with
`<lake>_<station>/`. Times are UTC; readings without a recorded time are at 12:00 UTC (all of SI-ARSO).
***

## corrections/<source>.csv

Generated per source by `scripts/main.py` on every full run; do not edit by hand. One row per Level0 row that was dropped, flagged or
changed (in Level1 or Level2), with the action taken and the reason.

## sources.json

One entry per data provider (`SOURCE` value in the DiMark export), keyed by an ASCII source key:

- `source`: exact `SOURCE` value; `enabled`: processed by default; `level0_file`: export in `data/Level0`
- `provider`, `country`: written to the NetCDF credit attributes
- `time_zone`: time zone of the `TIME` column (only `UTC` is implemented). Readings without a time take the mean
  recorded time of the same station and date, or 12:00 UTC
- `methods`: ordered rules `{variable, method, method_type[, parameter]}`; `method` `"*"` matches any method; the first
  matching rule wins; every VARIABLE/METHOD combination of the source must match a rule
- `comments`: every `COMMENTS` value of the source mapped to `none`, `below_detection_limit`, `station_metadata`
  (describes the station; also put it in `stations.json`) or `keep` (kept in Level1 `source_comment` only)
- `unflagged_repeats`: `[station_key, parameter]` pairs whose differing repeated values are genuine measurements
- `parameter_comments`: source-specific text appended to the variable `comment` attributes

Use `python scripts/inventory.py --source "<SOURCE>"` to draft a new entry.
