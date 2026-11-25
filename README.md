# In-situ lake monitoring data from the DiMark database

## Project Information

The DiMark project compiled in-situ monitoring data (water temperature, chlorophyll a, Secchi depth, nutrients) for 42
lakes from 15 data providers in the Alpine region into one database. This repository converts that database export to
NetCDF, one dataset per sampling station, for publication on [Datalakes](https://www.datalakes-eawag.ch/) (Eawag).

The pipeline is generic; each data provider (`SOURCE` in the export) is enabled separately once its data has been
reviewed and configured in `notes/sources.json` and `notes/stations.json` (see *Adding a source*).

| Source key | SOURCE | Provider | Status |
|---|---|---|---|
| `si_arso` | SI-ARSO | Slovenian Environment Agency (ARSO) | processed (7 stations, 1985-2024) |
| | 14 other sources | see `python scripts/inventory.py` | not yet configured |

### SI-ARSO stations

| Lake | Lake id | Station | Station id | Lat | Lon | Period | Notes |
|---|---|---|---|---|---|---|---|
| Bled | `bled` | ZAHODNA KOTANJA (west basin) | `zahodna_kotanja` | 46.36283 | 14.08774 | 1985-2024 | profiles 0.5-29 m, samples, Secchi |
| Bled | `bled` | VZHODNA KOTANJA (east basin) | `vzhodna_kotanja` | 46.36567 | 14.09997 | 1985-2005 | surface temperature only |
| Gajševsko jezero | `gajsevsko` | TOCKA T1 | `t1` | 46.53393 | 16.11957 | 2007-2024 | < 500 m from shore |
| Ledavsko jezero | `ledavsko` | TOCKA T2 | `t2` | 46.75068 | 16.04195 | 2003-2024 | < 500 m from shore |
| Perniško jezero | `pernisko` | TOCKA T1 | `t1` | 46.58351 | 15.73087 | 2007-2023 | < 500 m from shore |
| Slivniško jezero | `slivnisko` | TOCKA T1 | `t1` | 46.19283 | 15.44208 | 2007-2023 | < 500 m from shore |
| Šmartinsko jezero | `smartinsko` | TOCKA T3 | `t3` | 46.27626 | 15.26249 | 2007-2024 | < 500 m from shore |

Lake ids match the Alplakes lake keys. Each NetCDF file credits its provider: "<provider>; compiled within the DiMark
project; processed by Eawag".

## Citation

TODO: authors (year). In-situ lake monitoring data from the DiMark database. doi: TODO (one citation per source or per dataset to be decided)

## Keywords

DiMark, Alpine lakes, water temperature, chlorophyll a, Secchi depth, nutrients, lake monitoring data

## Folder structure
- **data** contains the raw and processed data (see the section Data Structure for details)
- **notebooks** contains a jupyter notebook (`Plot Data.ipynb`) that plots the Level2 data of every station
- **notes** contains the source configuration (`sources.json`), the station metadata (`stations.json`), the quality
  assurance bounds (`quality_assurance.json`), the manual events file (`events.csv`) and the generated logs of all
  corrections and flags (`corrections/<source>.csv`)
- **scripts** contains the processing scripts, including helper functions

## Code

[![License: MIT][mit-by-shield]][mit-by]

**You need to have [git](https://git-scm.com/downloads) installed in order to successfully clone the repository.**

- Clone the repository to your local machine using the command:

 `git clone --depth 1 TODO-repository-url`

 Note that the repository will be copied to your current working directory.

- Use conda and install the requirements with:

`conda env create -f environment.yml`

## Usage

### Reprocess data

Place the DiMark export `Database DiMark 19_02_2026(in).csv` in `data/Level0` (or download it with
`python scripts/download_remote_data.py`) and run:

`python scripts/main.py`

This processes every source with `"enabled": true` in `notes/sources.json`. Use `--source si_arso` to process selected
sources and `--station bled_zahodna_kotanja` for selected stations. Because the input is a database export, every run
rebuilds `data/Level1/<lake>_<station>` and `data/Level2/<lake>_<station>` completely and regenerates
`notes/corrections/<source>.csv` (not when `--station` is used). Level0 is never modified.

### Plot the output

`python scripts/plot.py` writes one PNG per NetCDF file to `plots/`, mirroring `data/` (e.g.
`plots/Level2/bled_zahodna_kotanja/L2_Profiles_bled_zahodna_kotanja_20200101_000000.png`). Pass files or folders to
plot a subset, e.g. `python scripts/plot.py data/Level2/bled_zahodna_kotanja`, and `--output` for another folder.

- Level1: one panel per variable, value against time, coloured by sample depth; flagged values drawn as crosses
- Level2 Profiles: per variable, profiles (one line per date, at most 12 dates spread over the file) and the depth-time heatmap
- Level2 Samples: per variable, the time series of each sample layer, with the depth ranges sampled in the legend

`plots/` is not committed. The notebook `notebooks/Plot Data.ipynb` plots each station's whole record instead.

### Adding a source

1. Profile it: `python scripts/inventory.py --source "<SOURCE value>"`. This prints stations, the TIME column,
   VARIABLE x METHOD counts, comments, repeated keys, sample layers, NO3 > TN cases, the depths sampled, and draft
   entries for `notes/sources.json` and `notes/stations.json`.
2. Review the data with the provider's documentation and fill in the drafts: `provider`, method types (probe / lab /
   secchi_disk / not_recorded; chlorophyll also needs `Chla_probe` or `Chla_lab`), what each comment means, lake ids
   (Alplakes keys), `exclude_depths` for one-off depths that should not appear in Level2, and source-specific `parameter_comments` (unit assumptions, merged series).
3. Set `"enabled": true` and run `python scripts/main.py --source <key>`. The pipeline stops with an error, rather than
   guessing, on unconfigured methods, comments or stations, on unrecognised TIME values, on sample dates the layer
   rule cannot resolve (e.g. FR-OLA's lab nutrients, which are discrete-depth profiles and need a depth-profile
   product), and on high-frequency series (e.g. the hourly IT-APPA BZ level meter), which need a time-series product.
4. Check the outputs and `notes/corrections/<key>.csv`, then add the source's known issues to this README.

### Adapt/Extend data processing pipeline

The python script `scripts/main.py` defines the processing steps, while `scripts/insitu.py` contains the source
configuration logic and the python classes
**InsituLevel1**, **InsituProfiles** and **InsituSamples** (subclasses of `GenericInstrument` in
`scripts/general/functions.py`) with the corresponding class methods. To add a processing step, create a class method in
`insitu.py` and call it from `main.py`. `scripts/pipeline.py` wraps `main.py` with the download/upload/Datalakes options
used by the Docker container.

## Data

### License

[![CC BY 4.0][cc-by-shield]][cc-by]

This data is released under the Creative Commons license - Attribution - CC BY (https://creativecommons.org/licenses/by/4.0/). This license states that consumers ("Data Users" herein) may distribute, adapt, reuse, remix, and build upon this work, as long as they give appropriate credit, provide a link to the license, and indicate if changes were made.

The Data User has an ethical obligation to cite the data source (see the DOI number) in any publication or product that results from its use. Communication, collaboration, or co-authorship (as appropriate) with the creators of this data package is encouraged.

Extensive efforts are made to ensure that online data are accurate and up to date, but the authors will not take responsibility for any errors that may exist in data provided online. Furthermore, the Data User assumes all responsibility for errors in analysis or judgment resulting from use of the data. The Data User is urged to contact the authors of the data if any questions about methodology or results occur.

### Data Structure

All names are ASCII: `<lake>_<station>`, e.g. `bled_zahodna_kotanja`.

- **Level 0**: `data/Level0/Database DiMark 19_02_2026(in).csv`, the full DiMark export (483,281 rows, 42 lakes, 15
  sources, sha256 `c223d14782f637759de304cfbe25f6dded3991c7f807915d6858ab0b736c3888`). Semicolon separated, cp1252
  encoded. Each source uses only its own rows (SI-ARSO: 11,990 rows). The file name and sha256 are written to the `source` and
  `history` attributes of every NetCDF file.

- **Level 1**: `data/Level1/<lake>_<station>/L1_<lake>_<station>.nc`, one file per station. A faithful conversion
  without gridding: dimension `obs`, one entry per kept measurement. Variables:
  - `time`, `depth_top`, `depth_bottom`, `depth` (mid-point)
  - `value`, `value_qual`
  - `variable` (integer code, `flag_values`/`flag_meanings`: Temp, Chla_probe, Chla_lab, Secchi, TN, TP, NH4, NO3, NO2,
    PO4, SiO2, Turbidity; codes are fixed across sources)
  - `method_type` (integer code: probe, lab, secchi_disk, not_recorded)
  - `method` (text, as in the source), `source_comment` (text, as in the source), `l0_row` (row index in the Level0 file)

  Samples mixed over a range (`DEPTH_m` = `"top_bottom"`, e.g. `0.5_20`) have `depth_top` < `depth_bottom`; single
  depths have `depth_top` = `depth_bottom`.

- **Level 2**: Datalakes products per station. Files are named by the calendar year in which they start
  (`..._<YYYY>0101_000000.nc`) and carry `time_coverage_start` / `time_coverage_end`. Values with `_qual > 0` are
  masked (NaN).
  - **Profiles** `data/Level2/<lake>_<station>/L2_Profiles_<lake>_<station>_<YYYY>0101_000000.nc`: dimensions
    `(depth, time)`; `time` is the union of the probe-variable dates. Two ways to build the depth axis:
    - *snap* (default, discrete sampling depths): the station's nominal sampling grid, derived from the data: every
      depth that occurs, except depths within ±0.25 m of a depth sampled on more dates, whose readings are snapped to it
      (Bled west basin: 0.5, 1, 2 ... 29 m; the one profile recorded at 1.14, 2.01 ... 27.83 m is snapped). Depths in
      `exclude_depths` (`notes/stations.json`) stay in Level1 only (Bled west: the single 0.0 m reading); an explicit
      `profile_depths` replaces the derived grid.
    - *interpolate* (high-resolution or irregular-depth profilers, `profile_interpolation` in `notes/stations.json`):
      each profile is linearly interpolated from its unflagged readings onto a fixed grid (e.g.
      `{"grid": [[0, 30, 1], [30, 310, 5]], "max_gap": null}`), within the measured depth range only and optionally not
      across gaps larger than `max_gap` m. `scripts/inventory.py` suggests this mode when profiles are dense (≥ 50
      depths) or sample under 40% of the nominal depths within their own depth range (e.g. FR-OLA Geneva and
      Bourget, IT-ARPAV Garda 369). No SI-ARSO station uses it.

    **File periods.** The record is split at year boundaries where the sampled depths change, and each file contains
    only the depths sampled in it, so the depth axis differs between files (Datalakes plots them together; combining
    them with `xr.concat(..., dim="time")` gives the full grid). The split minimises *empty cells + λ × files* with
    λ = 0.4 × (depths sampled) × (median profiles per year), i.e. a new file must save more than 0.4 years of a
    completely empty grid (`PERIOD_ALPHA` in `scripts/insitu.py`). α was chosen by testing on every multi-depth
    station in the export that uses snap mode (33 stations): 88 files instead of 585 yearly ones, at 89% fill (yearly: 92%),
    with few single-year files; smaller α fragments records, larger α merges changeover years. SI-ARSO: Bled west
    1985-2006 (2 m), 2007-2009 (changeover) and 2010-2024 (1 m); the small lakes 2007-2016 (1-2 depths) and from
    2017-2019 (full profiles).
  - **Samples** `data/Level2/<lake>_<station>/L2_Samples_<lake>_<station>_<YYYY>0101_000000.nc`, one file per
    station (no depth axis, so splitting would not change the display): dimension `time`, the
    union of Secchi, lab chlorophyll and nutrient dates. Lab samples are split into up to four layers per date, each a
    separate variable with its own `_qual`, `_depth_top` and `_depth_bottom`:

    | Suffix | Layer | Rule |
    |---|---|---|
    | (none) | upper | the sample with the shallowest top depth (shortest if two start at the surface) |
    | `_column` | whole column | a second sample starting at the surface and reaching deeper, or a surface sample reaching at least as deep as all others when ≥ 2 others exist |
    | `_mid` | intermediate | any sample left after upper, column and deep |
    | `_deep` | deep | the sample with the deepest bottom depth among the rest |

    Only layers that occur at a station are written. Up to 2014 Bled has three layers (e.g. `0.5_8`, `8_24`, `24_28`);
    from 2015 a whole-column sample (`0.5_27`/`0.5_28`) is added.

### Variables

Methods are those of SI-ARSO; other sources record theirs in the Level1 `method` variable.

| Variable | Product | Unit | Description | Method(s) in SI-ARSO |
|---|---|---|---|---|
| `Temp` | Profiles | degC | water temperature | `HL series 004165HY` or blank |
| `Chla_probe` | Profiles | ug/L | chlorophyll a, in-situ probe | `HL series Chlorophyll a 007202` or blank |
| `Chla_lab` | Samples | ug/L | chlorophyll a, laboratory | `SIST ISO 10260:2001` |
| `Secchi` | Samples | m | Secchi depth | `Hydro-bios` |
| `TN` | Samples | ug/L | total nitrogen as N | `SIST EN 12260:1996`, `SIST EN 12260:2003`, `SIST EN 20236:2022` |
| `TP` | Samples | ug/L | total phosphorus as P | `SIST EN ISO 6878:2004` |
| `NH4` | Samples | ug/L | ammonium as N | `SIST ISO 7150-1:1996`, `ISO 7150/1` |
| `NO3` | Samples | ug/L | nitrate as N | `ISO 10304-1:2007`, `ISO 10304-1` |
| `NO2` | Samples | ug/L | nitrite as N | `SIST EN 26777:1996` |
| `PO4` | Samples | ug/L | orthophosphate as P | (other sources) |
| `SiO2` | Samples | ug/L | dissolved silica | (other sources) |
| `Turbidity` | Profiles | NTU | turbidity | (other sources) |

- SI-ARSO: `Chla_probe` merges the blank-method and `HL series` rows: they are one instrument relabelled in 2020, never share a
  date, and give the same lab/probe ratio (Bled 1.30 and 1.32). The probe reads about 25% below the lab, so `Chla_lab`
  is a separate variable and the two are never merged.
- SI-ARSO nutrient units are taken to be µg/L as N and as P (see Known issues).

### How to deal with netCDF

**Reading from NetCDF**.
There are a number of resources that give detailed information on how to read and interact with NetCDF files. Linked below are some suggested resources.

- Python		https://unidata.github.io/netcdf4-python/ or https://docs.xarray.dev/
- R		https://cran.r-project.org/web/packages/ncdf4/ncdf4.pdf

**Reading Time.** Time is stored as `seconds since 1970-01-01 00:00:00` (UTC). Source times (`TIME`) are taken to be
UTC; a time range (`10:00-12:00`) is stored as its midpoint. A reading without a time takes the mean recorded time of
the station's other readings on the same date, or 12:00 UTC if none was recorded that day; the Level1 variable
`time_source` says which (0 = not recorded, 12:00 UTC; 1 = recorded; 2 = mean time of the same date). In Level2 each
sampling date is one profile / sample, stored at the mean time of its readings. **SI-ARSO records no sampling times:
all its data are at 12:00 UTC.** *Warning*: the display in the
[Datalakes website](https://www.datalakes-eawag.ch/) is in local time but the downloaded data are always in UTC.

- Python
```
from datetime import datetime, timezone
dt = datetime.fromtimestamp(unixdatetime, timezone.utc)
```
- R
```
library(anytime)
dt <- anytime(unixdatetime, tz = "UTC")
```

## Quality assurance

Quality flags (`_qual`): 0 = nothing to report, 1 = more investigation. Level1 keeps flagged values; Level2 masks them.

- **Range checks** with [envass](https://pypi.org/project/envass/) `simple` bounds from `notes/quality_assurance.json`
  (Temp 0-35, Chla 0-500, Secchi 0-20, TN 0-10000, TP 0-2000, NH4/NO3/NO2 0-10000, time 1985-01-01 to now).
- **Manual events** in `notes/events.csv` (`start;stop;parameter;comments`, see `notes/README.md`). Currently empty.
- **Corrections** are made in the pipeline, never in Level0. Every dropped, flagged or changed row is written to
  `notes/corrections/<source>.csv` (station, date, variable, method, depth, old value, new value, level, action, reason, Level0
  row index):

| Action | Rule |
|---|---|
| `dropped_duplicate` | Same station/date/depth/variable twice, blank method and named method, values within 0.05: the named-method row is kept, the blank row dropped. |
| `dropped_identical_repeat` | Repeated key with identical values: one row kept. |
| `repeat_kept_L2_mean_flagged` | Repeated key with different values: all rows kept in Level1 with `value_qual = 1`; Level2 uses the mean with `_qual = 1`. |
| `repeat_kept_L2_mean` | Station/parameter listed in the source's `unflagged_repeats` (SI-ARSO: Perniško temperature, two `HL series` readings at 0.5 m on the same date, differing by 0.1-1.7 °C. Treated as two genuine readings: both kept in Level1 unflagged; Level2 uses the mean, unflagged. |
| `flagged_below_dl` | Comment configured as `below_detection_limit` (SI-ARSO: `BELOW DL`): `_qual = 1`, kept in Level1, masked in Level2. |
| `flagged_no3_gt_tn` | NO3 > TN in the same sample: both values `_qual = 1`. |
| `flagged_qa` | Value outside the QA bounds or inside a manual event. |
| `depth_snapped` | Probe depth snapped to the nominal grid in Level2 (old/new values are depths). |
| `L1_only_excluded_depth` | Probe depth listed in the station's `exclude_depths` (Bled west: 0.0 m): Level1 only. |
| `L1_only_off_grid` | Only with an explicit `profile_depths`: depth more than 0.25 m from that grid, Level1 only. |
| `L2_cell_mean_flagged` | Several readings in one Level2 grid cell after snapping: mean with `_qual = 1`. |

## Known issues / open questions for ARSO (SI-ARSO)

1. **Is blank-method chlorophyll from the HL probe?** Single-depth chlorophyll without a method (Bled 1,779 rows
   2010-2019; 9-70 rows per small lake) is treated as probe chlorophyll (`Chla_probe`). At Perniško on 2019-06-27 and
   2019-08-22 a blank-method value at 0.5 m is *higher* than the lab value on the same date (70 vs 58.06, 190 vs 116.47),
   the opposite of the Bled relation.
2. **Are nutrients reported as N and as P?** NO3 <= TN in every sample except three on 2016-07-26 (Slivniško,
   Šmartinsko), and in all three NO3 is the `BELOW DL` code 497 µg/L (≈ 2.2 mg/L NO3 expressed as N). This supports
   µg/L as N (TN, NH4, NO3, NO2) and as P (TP), but it is not stated in the source.
3. **Why do duplicate temperature rows exist?** Bled (367), Slivniško (8) and Šmartinsko (8) have the same reading twice
   (blank method and `HL series`, differing only by rounding). Perniško has 40 dates with two different `HL series`
   readings at 0.5 m (0.1-1.7 °C apart). Bled 2016-08-04 has two different samples labelled `22_27` for TN, TP, NH4 and
   NO3 (e.g. NH4 77 and 301.1); one may belong to another layer.
4. **How are below-detection-limit values coded?** The 67 `BELOW DL` rows carry a constant value per parameter and
   period (e.g. NH4 7.8/10.1, NO3 4.5-5.9 or 497, NO2 2.13, TP 4.6/4.9, TN 200), never 0. Are these the detection limits?
5. **Can sampling times be supplied?** `TIME` is empty for all Slovenian rows; 12:00 UTC is used.

Further notes:
- Fixes in the shared `scripts/general/functions.py` (also needed in the other repositories that copy it): yearly
  `export()` used `relativedelta(year=+1)` (sets the year to 1) instead of `relativedelta(years=+1)`;
  `quality_assurance()` only stored the `_qual` flags when `events.csv` had rows; `logger.error()` used `traceback`
  without importing it. Level2 files are written by `InsituStation.write_file()` rather than `export()`, which names
  files by the first sampling time and writes nothing for a single-profile file in `"file"` mode.
- No altitude is given for the small lakes (TODO).

## Docker

#### Build the docker environment

`docker build -t dimark-lakes .`

#### Download data from S3

`docker run -v $(pwd):/repository --rm -t dimark-lakes --download`

#### Process data

`docker run -v $(pwd):/repository --rm -t dimark-lakes --reprocess`

#### Upload data to S3

`docker run -e AWS_ACCESS_KEY_ID=****** -e AWS_SECRET_ACCESS_KEY=****** -v $(pwd):/repository --rm -t dimark-lakes --upload`

## Collaborators

- **Data collection** the data providers listed above (SI-ARSO: Slovenian Environment Agency, ARSO)
- **Data compilation** DiMark project
- **Data pipeline** TODO
- **Data review** TODO

## Contacts
- TODO

[cc-by]: http://creativecommons.org/licenses/by/4.0/
[cc-by-shield]: https://img.shields.io/badge/License-CC%20BY%204.0-g.svg?label=Data%20License
[mit-by]: https://opensource.org/licenses/MIT
[mit-by-shield]: https://img.shields.io/badge/License-MIT-g.svg?label=Code%20License
