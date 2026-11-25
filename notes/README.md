# Notes

## stations.json

Station metadata keyed by `<lake_id>_<station_id>` (ASCII; unique across all sources), with `source` naming the entry in `sources.json`. `lake_name` and `station_name` must match the `LAKE` and
`STATION` columns of the Level0 DiMark export exactly.

The Level2 profile depth grid is derived from the data: every depth that occurs is a nominal depth unless it lies within
±0.25 m of a depth sampled on more dates, in which case readings are snapped to that depth. Optional keys:
- `exclude_depths`: depths whose readings stay in Level1 only (e.g. `[0.0]` for the single 0.0 m reading at Bled)
- `profile_depths`: an explicit nominal grid that replaces the derived one (readings further than ±0.25 m from it stay
  in Level1 only)
- `snap_tolerance`: snapping distance in m (default 0.25), e.g. with `profile_depths: [0.5]` and `snap_tolerance: 0.5` a
  single reading per date at 0-1 m becomes a surface series (IT-FEM Garda 369)
- `lab_profiles`: `true`/`false` overrides the automatic choice between the LabProfiles and Samples products for
  single-depth lab samples; `lab_interpolation`, `lab_profile_depths`, `lab_exclude_depths` work like the probe
  equivalents for LabProfiles
- `high_frequency`: `true` treats every time as its own profile (detected automatically when there are more than 2
  readings per date, depth and variable, e.g. the hourly IT-APPA BZ level meter)
- `profile_interpolation`: `{"grid": [[start, stop, step], ...], "max_gap": metres or null}` for high-resolution or
  irregular-depth profilers: Level2 profiles are linearly interpolated onto this fixed grid instead of snapped
  (`scripts/inventory.py` says when to use it)

All of these are logged in `corrections/<source>.csv`.

## quality_assurance.json

Hard lower and upper bounds (envass `simple` checks) per variable. `time` bounds are in seconds since
1970-01-01 00:00:00 UTC; `"now"` is replaced by the current time when the pipeline runs.

## events.csv

Manual masking of values that pass the automatic checks but are wrong (e.g. a temperature spike). Each row masks one
parameter (or `All`) at **one station** between two UTC times; rows without a valid station key stop the pipeline,
because they would otherwise mask every station:

start;stop;parameter;comments
20150714 00:00:00;20150714 23:59:59;bled_zahodna_kotanja/Temp;Example: spike at 12 m
20180101 00:00:00;20181231 23:59:59;constance_wallhausen/All;Example: sensor fault

Station keys are those in `stations.json`; parameters are Temp, Chla_probe, Chla_lab, Secchi, TN, TP, NH4, NO3, NO2,
PO4, SiO2, Turbidity or All. Times are UTC; data without a recorded time are at 12:00 UTC.

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
