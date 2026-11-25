# In-situ lake monitoring data from the DiMark database

[![CC BY 4.0][cc-by-shield]][cc-by] [![License: MIT][mit-by-shield]][mit-by]

The DiMark project compiled in-situ monitoring data (water temperature, chlorophyll a, Secchi depth, nutrients) from
lakes in the Alpine region into one database. This repository converts that export into NetCDF, one dataset per
station, for [Datalakes](https://www.datalakes-eawag.ch/) (Eawag). 14 sources, 48 stations and 41 lakes are
processed; Swiss data (CH-EAWAG, Greifensee) are excluded.

Each file credits its provider: "<provider>; compiled within the DiMark project; processed by Eawag".

**Citation:** TODO: authors (year). Title. doi: TODO

## Sources and stations

Data are stored by country, lake and station (`data/<Level>/<country>/<lake>/<station>/`, e.g. `data/Level2/austria/attersee/deepest_point/`); file names use the station key `<lake>_<station>`; full metadata (names as in the source, coordinates, site codes) is in
`notes/stations.json`, source settings in `notes/sources.json`.

| Source | Provider | Period | Stations |
|---|---|---|---|
| `si_arso` | Slovenian Environment Agency (ARSO) | 1985-2024 | `bled_vzhodna_kotanja`, `bled_zahodna_kotanja`, `gajsevsko_t1`, `ledavsko_t2`, `pernisko_t1`, `slivnisko_t1`, `smartinsko_t3` |
| `at_ages` | Austrian Agency for Health and Food Safety (AGES) / Federal Government of Lower Austria | 2015-2024 | `allentsteig_bathing_site`, `geras_bathing_site`, `langschlag_bathing_site`, `litschau_bathing_site`, `ottenstein_bathing_site`, `poysdorf_bathing_site` |
| `at_uibk_carinthia` | Amt der Kärntner Landesregierung, Abteilung 8 - Umwelt, Naturschutz und Klimaschutz, Kärntner Institut für Seenforschung | 2007-2023 | `faakersee_deepest_point`, `millstattersee_deepest_point`, `ossiachersee_deepest_point`, `worthersee_saag` |
| `at_uibk_salzburg` | Amt der Salzburger Landesregierung, Abteilung 7 Wasser, Gewässerschutz | 2007-2024 | `fuschlsee_deepest_point`, `grabensee_deepest_point`, `mattsee_deepest_point`, `obertrumersee_deepest_point`, `wallersee_deepest_point`, `wolfgangsee_st_gilgen`, `zellersee_deepest_point` |
| `at_uibk_baw` | Bundesamt für Wasserwirtschaft, Institut für Gewässerökologie und Fischereiwirtschaft | 2007-2024 | `attersee_deepest_point`, `hallstattersee_deepest_point`, `irrsee_deepest_point`, `mondsee_deepest_point`, `traunsee_deepest_point`, `wolfgangsee_strobl` |
| `at_uibk_vorarlberg` | Institut für Umwelt und Lebensmittelsicherheit des Landes Vorarlberg, Abteilung Gewässergüte | 2007-2024 | `constance_bregenz_bay` |
| `de_ukon` | University of Konstanz, Limnological Institute | 2015-2024 | `constance_wallhausen` |
| `fr_ola` | OLA, Observatory on LAkes (INRAE) | 1974-2023 | `annecy_grand_lac`, `bourget_point_b`, `geneva_shl2` |
| `it_appa_bz` | Provincial Environmental Protection Agency of Bolzano (APPA Bolzano) | 2015-2025 | `caldaro_bathing_facility`, `caldaro_deepest_point`, `caldaro_level_meter` |
| `it_appa_tn` | Provincial Environmental Protection Agency of Trento (APPA Trento) | 2000-2024 | `caldonazzo_main` |
| `it_arpal` | IT-ARPAL (TODO: full provider name) | 2004-2024 | `como_dervio`, `idro_anfo` |
| `it_arpav` | Regional Agency for Environmental Protection of Veneto (ARPAV) | 1997-2024 | `garda_deepest_point_arpav`, `garda_south_basin_arpav` |
| `it_fem` | Fondazione Edmund Mach (FEM) | 1990-2023 | `garda_deepest_point_fem`, `garda_south_basin_fem` |
| `de_lfu_bayern` | Bavarian Environment Agency (LfU Bayern) | 2009-2024 | `ammersee_deepest_point`, `konigssee_deepest_point`, `starnbergersee_deepest_point` |

## Usage

```console
conda env create -f environment.yml
python scripts/main.py                      # process all enabled sources (rebuilds data/Level1 and data/Level2)
python scripts/main.py --source si_arso     # one source; --station <key> for single stations
python scripts/plot.py                      # one PNG per NetCDF file in plots/ (not committed)
```

`notebooks/Plot Data.ipynb` plots each station's full record. Data are synced with the S3 bucket in `.bucket` via
`scripts/download_remote_data.py` / `scripts/upload_remote_data.py`; `scripts/pipeline.py` (used by the Docker
image: `docker build -t dimark-lakes .`, `docker run -v $(pwd):/repository --rm -t dimark-lakes --reprocess`) wraps
download, processing, upload and the Datalakes update.

**Adding a source:** run `python scripts/inventory.py --source "<SOURCE>"`, which profiles the source and prints draft
`sources.json` / `stations.json` entries, complete them (method types, comment meanings, unit basis, lake ids), then
process it. The pipeline stops on anything not configured (unknown methods, comments, stations or time formats,
unresolvable sample layers) instead of guessing.

## Data

**Level 0** `data/Level0/Database DiMark 19_02_2026(in).csv`: the DiMark export (483,281 rows, sha256
`c223d147…3888`; `;`-separated, cp1252). Never modified; its name and sha256 are in every file's `source` / `history`.

**Level 1** `data/Level1/<country>/<lake>/<station>/L1_<lake>_<station>.nc`: one file per station, one entry per measurement (dimension `obs`):
`time`, `time_source`, `depth_top`, `depth_bottom`, `depth`, `value`, `value_qual`, `variable` and `method_type`
(integer codes with `flag_values` / `flag_meanings`), `method` and `source_comment` (text as in the source), `l0_row`.

**Level 2** `data/Level2/<country>/<lake>/<station>/L2_<product>_<lake>_<station>_<YYYY>0101_000000.nc`, flagged values masked:

| Product | Dimensions | Content |
|---|---|---|
| `Profiles` | depth, time | probe / thermometer measurements at single depths (`Temp`, `Chla_probe`, `Turbidity`) |
| `LabProfiles` | depth, time | lab samples at discrete depths, where ≥ 3 depths are sampled per date (`Chla_lab`, nutrients) |
| `Samples` | time | `Secchi` and the other lab samples; samples mixed over a depth range are split into layers `<var>` (upper), `<var>_column`, `<var>_mid`, `<var>_deep`, each with `_depth_top` / `_depth_bottom` |

- **Depth axis:** readings are snapped to the station's nominal depths (derived from the data, ±0.25 m), or, for
  high-resolution or irregular profilers (Geneva, Bourget, Annecy, Garda deepest point ARPAV), interpolated onto a
  fixed grid within each profile's measured range (`profile_interpolation` in `notes/stations.json`).
- **Files:** a new file starts at a year boundary only where the sampled depths change (optimal split, see
  `split_periods` in `scripts/insitu.py`), and each file contains only the depths sampled in it, so depth axes differ
  between files. `Samples` is one file per station.
- **Time:** seconds since 1970-01-01 00:00:00 UTC. Source times are taken as UTC (ranges as their midpoint); readings
  without a time get the mean time of the same date, or 12:00 UTC (`time_source`). In Level2 each date is one
  profile at the mean time of its readings (every time is kept at the hourly Caldaro level meter).

| Variable | Unit | Description |
|---|---|---|
| `Temp` | degC | water temperature |
| `Chla_probe` / `Chla_lab` | ug/L | chlorophyll a, in-situ probe / laboratory (never merged) |
| `Turbidity` | NTU | turbidity |
| `Secchi` | m | Secchi depth |
| `TN`, `TP`, `NH4`, `NO3`, `NO2`, `PO4`, `SiO2` | ug/L | nutrients; the `long_name` gives the basis (as N / as P / as NO3) where known |

## Quality control

`_qual`: 0 = nothing to report, 1 = more investigation. Level1 keeps flagged values, Level2 masks them. The aim is
that bad values are masked and good values are not:

- **Masked:** values outside the bounds in `notes/quality_assurance.json` (physically impossible, e.g. Temp 0-35 °C,
  Secchi 0-25 m); below-detection values (`BELOW DL`, and concentrations reported as exactly 0); a fraction above its
  total in the same sample by more than 10% (NO3-N > TN, PO4-P > TP; both values); repeated measurements of the same
  station, date, depth and variable that disagree (more than 0.2 °C, or 10% for other variables); periods listed in
  `notes/events.csv`.
- **Not masked:** repeats that agree within those tolerances (Level2 uses their mean), and the SI-ARSO Perniško
  surface-temperature pairs (`unflagged_repeats`).
- **Dropped from Level1:** blank-method duplicates of a named-method reading (within 0.05) and identical repeats.
- Every dropped, flagged or changed row is listed in `notes/corrections/<source>.csv`. Values that look wrong but pass
  these checks (e.g. a temperature spike) are masked by adding them to `notes/events.csv`.

## Known issues and open questions

- **Unit basis:** stated by AT-UIBK (as N / as P) and assumed for SI-ARSO; unknown for the other sources. FR-OLA
  reports nitrate as NO3 (NO3 ≈ 3.6 × TN; ≈ 0.8 × TN as N) and phosphate as PO4 (PO4 ≈ 2.5 × TP; ≈ 0.8 × TP as P);
  values are kept as reported and converted only for the consistency checks.
- **DE-UKON:** two temperature probes (Moldaenke, STS) measured the same points in 2016-2019 and differ by a median
  0.93 °C (up to 9.2 °C); both are flagged, so these temperatures are masked in Level2. Which probe is right?
- **Coordinates:** 197 IT-ARPAL Como rows carry Lake Garda's coordinates (Dervio's are used); AT-AGES Allentsteig has
  three nearby coordinate pairs (the most frequent is used).
- **IT-FEM Garda deepest point:** one temperature per date at 0-5 m, stored as surface temperature at 0.5 m.
- **Station names:** "deepest point" is inferred from profile depths reaching the lake's maximum depth; the Caldonazzo
  site (`caldonazzo_main`) is only identified by its code. Lake ids outside Slovenia are not yet checked against the
  Alplakes keys. IT-ARPAL's full provider name and all altitudes except Bled are missing.
- **SI-ARSO questions:** Is blank-method chlorophyll from the HL probe? Are nutrients as N / as P? Why are there
  duplicate temperature rows (and two different `22_27` samples at Bled on 2016-08-04)? Are `BELOW DL` values the
  detection limits? Can sampling times be supplied?
- **Shared code:** `scripts/general/functions.py` has three fixes also needed in other repositories:
  `relativedelta(years=+1)` in `export()`, `_qual` stored without events in `quality_assurance()`, `traceback` import.

## Contacts

TODO

[cc-by]: http://creativecommons.org/licenses/by/4.0/
[cc-by-shield]: https://img.shields.io/badge/License-CC%20BY%204.0-g.svg?label=Data%20License
[mit-by]: https://opensource.org/licenses/MIT
[mit-by-shield]: https://img.shields.io/badge/License-MIT-g.svg?label=Code%20License
