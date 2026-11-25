# -*- coding: utf-8 -*-
"""
Processing classes for the in-situ lake monitoring data contained in the DiMark database export.

Source-specific behaviour (which rows to use, how methods map to parameters and method types, how comments are
interpreted, data-manager decisions) is configured in notes/sources.json; station metadata in notes/stations.json.
Anything a source has not configured raises an error instead of being guessed.

Level0 -> Level1  : InsituLevel1   one NetCDF per station, dimension `obs` (one entry per kept measurement)
Level1 -> Level2  : InsituProfiles (depth, time) grid of single-depth probe measurements, yearly files
                    InsituSamples  (time) lab samples and Secchi depth, split into named layers, yearly files
"""
import os
import json
import hashlib
from datetime import datetime, timezone

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
from envass import qualityassurance

from general.functions import GenericInstrument, json_converter

TIME_UNITS = "seconds since 1970-01-01 00:00:00"
QUAL_UNITS = "0 = nothing to report, 1 = more investigation"
SNAP_TOLERANCE = 0.25  # m, probe depths are snapped to the nominal grid within this tolerance
DUPLICATE_TOLERANCE = 0.05  # blank-method rows within this of a named-method row are treated as duplicates
NOON = 12 * 3600
# Profiles are split into files at year boundaries where the sampled depths change (see split_periods): a new file
# is started only if it saves more than PERIOD_ALPHA years' worth of a completely empty depth grid.
PERIOD_ALPHA = 0.4
CREDIT = "{provider}; compiled within the DiMark project; processed by Eawag"

# DiMark VARIABLE -> parameter. Chlorophyll is split by method (probe / lab) in the source configuration.
DIMARK_VARIABLES = {"WaterTemperature_C": "Temp", "SecchiDisk_m": "Secchi", "TN_ug/L": "TN", "TP_ug/L": "TP",
                    "NH4_ug/L": "NH4", "NO3_ug/L": "NO3", "NO2_ug/L": "NO2", "PO4_ug/L": "PO4", "SIO2_ug/L": "SiO2",
                    "Turbidity_NTU": "Turbidity", "Chlorophyll_ug/L": None}

# Integer codes used in Level1 for `variable` and `method_type`. Append only: codes must stay stable.
VARIABLE_CODES = {"Temp": 1, "Chla_probe": 2, "Chla_lab": 3, "Secchi": 4, "TN": 5, "TP": 6, "NH4": 7, "NO3": 8, "NO2": 9,
                  "PO4": 10, "SiO2": 11, "Turbidity": 12}
METHOD_TYPE_CODES = {"probe": 1, "lab": 2, "secchi_disk": 3, "not_recorded": 4, "thermometer": 5}
PROFILE_VARIABLES = ["Temp", "Chla_probe", "Turbidity"]
SAMPLE_VARIABLES = ["Secchi", "Chla_lab", "TN", "TP", "NH4", "NO3", "NO2", "PO4", "SiO2"]
LAB_VARIABLES = [v for v in SAMPLE_VARIABLES if v != "Secchi"]
# A lab parameter at a station goes to the LabProfiles (depth, time) product instead of the layered Samples product
# when most of its samples are taken at single depths and at least this many depths are sampled per date (median).
LAB_PROFILE_MIN_DEPTHS = 3
COMMENT_ACTIONS = ["none", "below_detection_limit", "station_metadata", "keep"]

# Generic attributes; notes/sources.json `parameter_comments` add source-specific comments.
PARAMETERS = {
    "Temp": {"unit": "degC", "long_name": "water temperature", "comment": "Measurement at a single depth."},
    "Chla_probe": {"unit": "ug/L", "long_name": "chlorophyll a concentration (in-situ probe)",
                   "comment": "In-situ probe chlorophyll at a single depth. Not merged with laboratory chlorophyll (Chla_lab)."},
    "Chla_lab": {"unit": "ug/L", "long_name": "chlorophyll a concentration (laboratory)",
                 "comment": "Laboratory analysis of a water sample, possibly mixed over the depth range given by the depth_top / depth_bottom variables."},
    "Secchi": {"unit": "m", "long_name": "Secchi depth", "comment": "Secchi disk."},
    "TN": {"unit": "ug/L", "long_name": "total nitrogen", "comment": ""},
    "TP": {"unit": "ug/L", "long_name": "total phosphorus", "comment": ""},
    "NH4": {"unit": "ug/L", "long_name": "ammonium", "comment": ""},
    "NO3": {"unit": "ug/L", "long_name": "nitrate", "comment": ""},
    "NO2": {"unit": "ug/L", "long_name": "nitrite", "comment": ""},
    "PO4": {"unit": "ug/L", "long_name": "orthophosphate", "comment": ""},
    "SiO2": {"unit": "ug/L", "long_name": "dissolved silica", "comment": ""},
    "Turbidity": {"unit": "NTU", "long_name": "turbidity", "comment": "Measurement at a single depth."},
}

LAYERS = {
    "": "upper layer sample (shallowest top depth on the date)",
    "_column": "whole-column sample (from the surface sample depth to at least the deepest sample on the date)",
    "_mid": "intermediate layer sample",
    "_deep": "deepest layer sample (deepest bottom depth on the date)",
}

N_PER_NO3 = 14.007 / 62.004  # ug N per ug NO3
TIME_SOURCE_CODES = {"not_recorded": 0, "recorded": 1, "same_date": 2}
TIME_COMMENT = ("Time in UTC. Where the source gives a sampling time it is used (a time range as its midpoint); a "
                "reading without a time takes the mean recorded time of the station's other readings on the same date, "
                "or 12:00 UTC if no time was recorded that day.")
TIME_COMMENT_L1 = TIME_COMMENT + " See time_source."
TIME_COMMENT_L2 = TIME_COMMENT + " In Level2 each sampling date is one profile / sample, stored at the mean time of its readings."
HIGH_FREQUENCY_LIMIT = 2  # median readings per station/date/depth/variable above which a series is a mooring, not profiles


def sha256(file):
    h = hashlib.sha256()
    with open(file, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config(notes):
    """Read notes/sources.json and notes/stations.json and check that they are consistent."""
    with open(os.path.join(notes, "sources.json"), encoding="utf-8") as f:
        sources = json.load(f)
    with open(os.path.join(notes, "stations.json"), encoding="utf-8") as f:
        stations = json.load(f)
    for key, station in stations.items():
        if station["source"] not in sources:
            raise ValueError("Station {} refers to unknown source {}".format(key, station["source"]))
        if key != "{}_{}".format(station["lake_id"], station["station_id"]):
            raise ValueError("Station key {} must be <lake_id>_<station_id>".format(key))
    for key, source in sources.items():
        for action in source.get("comments", {}).values():
            if action not in COMMENT_ACTIONS:
                raise ValueError("Source {}: unknown comment action {} (use one of {})".format(key, action, COMMENT_ACTIONS))
    return sources, stations


def read_level0(file):
    """Read a DiMark export (cp1252, ';', everything as strings). `l0_row` is the 0-based data row index in the
    file (header excluded)."""
    df = pd.read_csv(file, sep=";", encoding="cp1252", dtype=str, keep_default_na=False)
    df.columns = [c.strip().rstrip(",").strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].str.strip()
    df["COMMENTS"] = df["COMMENTS"].str.rstrip(", \t")
    df["l0_row"] = np.arange(len(df))
    return df


def select_source(df, source_key, source, stations):
    """Rows of one source, parsed and classified according to its configuration."""
    df = df[df["SOURCE"] == source["source"]].copy()
    if len(df) == 0:
        raise ValueError("No rows with SOURCE == {}".format(source["source"]))

    # Time (UTC). Readings without a time take the mean recorded time of the station's readings on that date.
    if source.get("time_zone", "UTC") != "UTC":
        raise NotImplementedError("{}: only time_zone 'UTC' is implemented".format(source_key))
    df["time"], df["date"], df["time_source"] = parse_times(df, source_key)

    # Depth and value
    parts = df["DEPTH_m"].str.split("_")
    df["depth_top"] = parts.str[0].astype(float)
    df["depth_bottom"] = parts.str[-1].astype(float)
    df["depth"] = df["DEPTH_M_m"].astype(float)
    df["value"] = df["VALUE"].astype(float)

    # Parameter and method type
    unknown_vars = set(df["VARIABLE"]) - set(DIMARK_VARIABLES)
    if unknown_vars:
        raise ValueError("{}: unknown DiMark variables {}".format(source_key, unknown_vars))
    rules = source.get("methods", [])
    parameter, method_type, unmatched = [], [], set()
    for variable, method in zip(df["VARIABLE"], df["METHOD"]):
        rule = next((r for r in rules if r["variable"] == variable and r["method"] in (method, "*")), None)
        if rule is None:
            unmatched.add((variable, method))
            parameter.append(None)
            method_type.append(None)
            continue
        p = rule.get("parameter", DIMARK_VARIABLES[variable])
        if p not in VARIABLE_CODES or rule["method_type"] not in METHOD_TYPE_CODES:
            raise ValueError("{}: invalid method rule {}".format(source_key, rule))
        parameter.append(p)
        method_type.append(rule["method_type"])
    if unmatched:
        raise ValueError("{}: no method rule in notes/sources.json for VARIABLE/METHOD {}".format(source_key, sorted(unmatched)))
    df["parameter"] = parameter
    df["method_type"] = method_type

    # Comments
    unknown_comments = set(df["COMMENTS"]) - set(source.get("comments", {}))
    if unknown_comments:
        raise ValueError("{}: comments not configured in notes/sources.json: {}".format(source_key, unknown_comments))
    df["comment_action"] = df["COMMENTS"].map(source.get("comments", {}))

    # Stations
    configured = {(s["lake_name"], s["station_name"]): k for k, s in stations.items() if s["source"] == source_key}
    df["station_key"] = [configured.get(x) for x in zip(df["LAKE"], df["STATION"])]
    missing = set(zip(df.loc[df["station_key"].isna(), "LAKE"], df.loc[df["station_key"].isna(), "STATION"]))
    if missing:
        raise ValueError("{}: stations missing from notes/stations.json: {}".format(source_key, missing))

    # Readings are grouped into profiles / samples by sampling date, except at high-frequency stations (e.g. hourly
    # moorings: median readings per date/depth/variable > HIGH_FREQUENCY_LIMIT), where every time is its own profile.
    single = df[df["depth_top"] == df["depth_bottom"]]
    per_key = single.groupby(["station_key", "date", "DEPTH_m", "parameter"]).size().groupby(level="station_key").median()
    high = set(per_key[per_key > HIGH_FREQUENCY_LIMIT].index)
    high |= {k for k, s in stations.items() if s.get("source") == source_key and s.get("high_frequency")}
    df["high_frequency"] = df["station_key"].isin(high)
    df["profile_key"] = np.where(df["high_frequency"], df["time"], df["date"])
    df["product"] = assign_products(df, stations)
    return df


def assign_products(df, stations):
    """Level2 product of every row: "profiles" (single-depth probe/thermometer measurements), "lab_profiles"
    (single-depth lab samples at stations sampling >= LAB_PROFILE_MIN_DEPTHS depths per date), "samples" (Secchi and
    the remaining lab samples, assigned to layers) or "level1_only" (e.g. probe readings averaged over a range).
    `lab_profiles: true/false` in notes/stations.json overrides the automatic choice."""
    product = np.full(len(df), "level1_only", dtype=object)
    single = (df["depth_top"] == df["depth_bottom"]).values
    probe = df["parameter"].isin(PROFILE_VARIABLES).values
    product[probe & single] = "profiles"
    product[(df["parameter"] == "Secchi").values] = "samples"
    lab = df["parameter"].isin(LAB_VARIABLES).values
    for (station, parameter), g in df[lab].groupby(["station_key", "parameter"]):
        override = stations[station].get("lab_profiles")
        g_single = g["depth_top"] == g["depth_bottom"]
        depths = g[g_single].groupby("profile_key")["DEPTH_m"].nunique()
        auto = g_single.mean() >= 0.5 and len(depths) and depths.median() >= LAB_PROFILE_MIN_DEPTHS
        idx = df.index.get_indexer(g.index)
        if (override if override is not None else auto):
            product[idx[g_single.values]] = "lab_profiles"
            product[idx[~g_single.values]] = "samples"
        else:
            product[idx] = "samples"
    return product


def parse_times(df, source_key):
    """Returns (time, date, time_source): seconds since 1970 UTC per row, the sampling date (00:00 UTC) and
    TIME_SOURCE_CODES (recorded on the row / taken from the same date's other readings / not recorded -> 12:00)."""
    date = pd.to_datetime(df["DATE"], format="%d/%m/%Y", utc=True)
    date = ((date - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()).values
    seconds = np.full(len(df), np.nan)
    bad = set()
    for i, text in enumerate(df["TIME"].values):
        if text == "":
            continue
        parts = text.split("-")
        try:
            values = []
            for part in parts:
                hms = [int(x) for x in part.split(":")]
                if len(hms) not in (2, 3) or not (0 <= hms[0] <= 24 and 0 <= hms[1] < 60):
                    raise ValueError
                values.append(hms[0] * 3600 + hms[1] * 60 + (hms[2] if len(hms) == 3 else 0))
            if len(values) > 2 or (len(values) == 2 and values[1] < values[0]):
                raise ValueError
            seconds[i] = np.mean(values)  # a range "HH:MM-HH:MM" is stored as its midpoint
        except ValueError:
            bad.add(text)
    if bad:
        raise ValueError("{}: unrecognised TIME values {}".format(source_key, sorted(bad)[:20]))
    frame = pd.DataFrame({"station": df["LAKE"].values + "|" + df["STATION"].values, "date": date, "seconds": seconds})
    same_date = frame.groupby(["station", "date"])["seconds"].transform("mean").values
    recorded = np.isfinite(seconds)
    from_date = ~recorded & np.isfinite(same_date)
    time_of_day = np.where(recorded, seconds, np.where(from_date, same_date, NOON))
    source = np.where(recorded, TIME_SOURCE_CODES["recorded"], np.where(from_date, TIME_SOURCE_CODES["same_date"], TIME_SOURCE_CODES["not_recorded"]))
    return date + time_of_day, date, source


def date_times(df):
    """Profiles of a Level2 product (sampling dates, or every time at high-frequency stations) and the mean time of
    the product's readings in each."""
    means = df.groupby("profile_key")["time"].mean().round()  # whole seconds
    return means.index.values, means.values


def iso_date(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def split_periods(present, time, alpha=PERIOD_ALPHA):
    """Split a (depth, time) product into files covering whole calendar years.

    Chooses the segmentation (boundaries only at year starts) that minimises
        empty cells + lambda * number of files,   lambda = alpha * depths sampled * median profiles per year,
    where the cells of a file are (depths with data in that file) x (profiles in that file). Solved exactly by
    dynamic programming. Returns a list of boolean time masks, one per file, in time order."""
    years = np.array([datetime.fromtimestamp(t, timezone.utc).year for t in time])
    unique = np.unique(years)
    blocks = [present[:, years == y] for y in unique]
    n = len(blocks)
    lam = alpha * max(1, int(present.any(axis=1).sum())) * float(np.median([b.shape[1] for b in blocks]))
    cost = np.zeros((n, n))
    for i in range(n):
        rows = np.zeros(present.shape[0], dtype=bool)
        filled = cols = 0
        for j in range(i, n):
            rows |= blocks[j].any(axis=1)
            filled += int(blocks[j].sum())
            cols += blocks[j].shape[1]
            cost[i, j] = rows.sum() * cols - filled
    best = np.full(n + 1, np.inf)
    best[0] = 0.0
    prev = np.zeros(n + 1, dtype=int)
    for j in range(1, n + 1):
        for i in range(j):
            c = best[i] + cost[i, j - 1] + lam
            if c < best[j]:
                best[j], prev[j] = c, i
    segments, j = [], n
    while j > 0:
        segments.append((prev[j], j - 1))
        j = prev[j]
    return [np.isin(years, unique[a:b + 1]) for a, b in segments[::-1]]


def nominal_grid(depth, time):
    """Nominal sampling depths from single-depth readings: every depth that occurs, unless it lies within
    SNAP_TOLERANCE of a depth sampled on more dates (readings there are snapped to that depth)."""
    dates = pd.Series(np.asarray(time)).groupby(np.asarray(depth, dtype=float)).nunique()
    nominal = []
    for d in sorted(dates.index, key=lambda d: (-dates[d], d)):  # most frequently sampled first
        if all(abs(d - n) > SNAP_TOLERANCE + 1e-9 for n in nominal):
            nominal.append(d)
    return np.array(sorted(nominal), dtype=float)


def profile_structure(depth, time):
    """Summary used to choose between snapping and interpolation: nominal grid size, median depths per profile, and
    the median share of the nominal depths within each profile's own depth range that the profile samples
    (profiles with >= 3 depths). Interpolation is suggested for dense (>= 50 depths) or irregular (< 40%) profiles."""
    depth, time = np.asarray(depth, dtype=float), np.asarray(time)
    grid = nominal_grid(depth, time)
    snapped = grid[np.abs(depth[:, None] - grid[None, :]).argmin(axis=1)]
    per_profile, coverage = [], []
    for t in np.unique(time):
        idx = np.unique(np.searchsorted(grid, snapped[time == t]))
        per_profile.append(len(idx))
        if len(idx) >= 3:
            coverage.append(len(idx) / (idx.max() - idx.min() + 1))
    median = float(np.median(per_profile))
    cov = float(np.median(coverage)) if coverage else np.nan
    return {"nominal_depths": len(grid), "median_depths_per_profile": median, "coverage": cov,
            "interpolate": bool(median >= 50 or (coverage and cov < 0.4))}


def depth_grid(spec):
    """Fixed interpolation grid from [[start, stop, step], ...] (stop inclusive)."""
    parts = [np.arange(a, b + step / 2, step) for a, b, step in spec]
    return np.unique(np.round(np.concatenate(parts), 6))


def interpolate_profile(depth, value, grid, max_gap=None):
    """Linear interpolation of one profile onto `grid`, within the measured depth range only (no extrapolation) and,
    if max_gap is given, not across gaps between measurements larger than max_gap metres."""
    order = np.argsort(depth)
    depth, value = depth[order], value[order]
    out = np.full(len(grid), np.nan)
    if len(depth) == 1:
        hit = np.abs(grid - depth[0]) <= SNAP_TOLERANCE + 1e-9
        if hit.any():
            out[np.argmin(np.abs(grid - depth[0]))] = value[0]
        return out
    inside = (grid >= depth[0] - 1e-9) & (grid <= depth[-1] + 1e-9)
    out[inside] = np.interp(grid[inside], depth, value)
    if max_gap is not None:
        upper = np.searchsorted(depth, grid, side="left").clip(1, len(depth) - 1)
        gap = depth[upper] - depth[upper - 1]
        exact = np.isin(np.round(grid, 6), np.round(depth, 6))
        out[(gap > max_gap) & ~exact] = np.nan
    return out


class Corrections:
    """Collects every Level0 row that is dropped, flagged or changed."""
    columns = ["station", "date", "variable", "method", "depth", "old_value", "new_value", "level", "action", "reason", "l0_row"]

    def __init__(self):
        self.rows = []

    def add(self, station, row, action, reason, level, old_value=None, new_value=None, depth=None):
        self.rows.append({
            "station": station,
            "date": iso_date(row["time"]),
            "variable": row["parameter"],
            "method": row["METHOD"],
            "depth": row["DEPTH_m"] if depth is None else depth,
            "old_value": row["value"] if old_value is None else old_value,
            "new_value": new_value,
            "level": level,
            "action": action,
            "reason": reason,
            "l0_row": int(row["l0_row"]),
        })

    def to_csv(self, file):
        df = pd.DataFrame(self.rows, columns=self.columns)
        df = df.sort_values(["station", "action", "date", "variable", "l0_row"])
        df.to_csv(file, sep=";", index=False)
        return df


class InsituStation(GenericInstrument):
    """Shared station metadata and attributes for all in-situ products."""

    def __init__(self, station_key, station, source_key, source, source_file, source_sha256, *args, **kwargs):
        super(InsituStation, self).__init__(*args, **kwargs)
        self.key = station_key
        self.station = station
        self.source_key = source_key
        self.source = source
        self.credit = CREDIT.format(provider=source["provider"])
        self.source_file = os.path.basename(source_file)
        self.source_sha256 = source_sha256
        self.product = ""

    def set_general_attributes(self, product, description):
        s = self.station
        self.product = product
        attrs = {
            "title": "{} - {} ({}): in-situ {} ({})".format(s["lake_long_name"], s["station_name"], s["station_description"], product, self.source["provider"]),
            "institution": self.credit,
            "source": "{} lake monitoring data (rows with SOURCE == '{}') from the DiMark database export '{}' (sha256 {})".format(
                self.source["provider"], self.source["source"], self.source_file, self.source_sha256),
            "references": "TODO: DOI / data paper. Pipeline: TODO repository URL",
            "history": "{} UTC: {} created by scripts/main.py from Level0 file '{}' (sha256 {}). Corrections and flags are listed in notes/corrections/{}.csv.".format(
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), product, self.source_file, self.source_sha256, self.source_key),
            "conventions": "CF 1.7",
            "comment": "{} {} Data provider: {}.".format(description, TIME_COMMENT_L2 if product.startswith("Level2") else TIME_COMMENT_L1, self.credit),
            "latitude": s["latitude"],
            "longitude": s["longitude"],
            "lake": s["lake_long_name"],
            "lake_id": s["lake_id"],
            "station": s["station_name"],
            "station_id": s["station_id"],
            "license": "CC BY 4.0",
            "acknowledgement": self.credit,
            "country": self.source.get("country", ""),
            "creator_name": "TODO: author list",
            "doi": "TODO: DOI",
            "contact": "TODO: contact e-mail(s)",
        }
        if s.get("altitude") is not None:
            attrs["altitude"] = float(s["altitude"])
        if s.get("comment"):
            attrs["station_comment"] = s["comment"]
        self.general_attributes = attrs

    def parameter(self, name):
        """Generic parameter attributes with the source-specific comment appended."""
        p = dict(PARAMETERS[name])
        p["long_name"] = self.source.get("parameter_long_names", {}).get(name, p["long_name"])
        extra = self.source.get("parameter_comments", {}).get(name, "")
        p["comment"] = " ".join(x for x in [p["comment"], extra] if x)
        return p

    def write_file(self, folder, title, time_mask, depth_index=None):
        """Write one Level2 file (same layout as the shared GenericInstrument.export(): float64, NaN fill, zlib,
        units/long_name, plus comment and CF attributes), named by the calendar year in which it starts.
        export() itself is not used: in "file" mode it writes nothing for a single-profile file and names files by
        the first sampling time."""
        os.makedirs(folder, exist_ok=True)
        time = np.asarray(self.data["time"])[time_mask]
        start = datetime.fromtimestamp(time[0], timezone.utc)
        out = os.path.join(folder, "{}_{}0101_000000.nc".format(title, start.year))
        if os.path.exists(out):
            raise ValueError("Two Level2 files would start in the same year: {}".format(out))
        with netCDF4.Dataset(out, mode="w", format="NETCDF4") as nc:
            attrs = dict(self.general_attributes)
            attrs["time_coverage_start"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            attrs["time_coverage_end"] = datetime.fromtimestamp(time[-1], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for key, value in attrs.items():
                setattr(nc, key, value)
            for key, values in self.dimensions.items():
                size = values["dim_size"]
                if key == "depth" and depth_index is not None:
                    size = len(depth_index)
                nc.createDimension(values["dim_name"], size)
            for key, values in self.variables.items():
                var = nc.createVariable(values["var_name"], np.float64, values["dim"], fill_value=np.nan, zlib=True, complevel=4)
                var.units = values["unit"]
                var.long_name = values["long_name"]
                for attr in ["comment", "standard_name", "positive", "calendar"]:
                    if attr in values:
                        setattr(var, attr, values[attr])
                arr = np.asarray(self.data[key])
                if values["dim"] == ("depth",):
                    var[:] = arr if depth_index is None else arr[depth_index]
                elif values["dim"] == ("time",):
                    var[:] = arr[time_mask]
                elif values["dim"] == ("depth", "time"):
                    arr = arr[:, time_mask]
                    var[:] = arr if depth_index is None else arr[depth_index]
                else:
                    raise ValueError("Unsupported dimensions {} for {}".format(values["dim"], key))
        self.log.info("Written {} ({} times)".format(os.path.basename(out), len(time)), indent=2)
        return out


class InsituLevel1(InsituStation):
    """Faithful per-station conversion of the Level0 rows to NetCDF (no gridding)."""

    def __init__(self, *args, **kwargs):
        super(InsituLevel1, self).__init__(*args, **kwargs)
        self.set_general_attributes("Level1 observations",
                                    "Faithful conversion of the source rows for this station: one entry per kept measurement "
                                    "(dimension obs), no gridding.")
        self.dimensions = {"obs": {"dim_name": "obs", "dim_size": None}}
        self.variables = {
            "time": {"var_name": "time", "dim": ("obs",), "unit": TIME_UNITS, "long_name": "time", "standard_name": "time",
                     "calendar": "standard", "comment": TIME_COMMENT_L1},
            "time_source": {"var_name": "time_source", "dim": ("obs",), "unit": "1", "long_name": "origin of the time value"},
            "depth_top": {"var_name": "depth_top", "dim": ("obs",), "unit": "m", "long_name": "top depth of the sample", "positive": "down"},
            "depth_bottom": {"var_name": "depth_bottom", "dim": ("obs",), "unit": "m", "long_name": "bottom depth of the sample", "positive": "down"},
            "depth": {"var_name": "depth", "dim": ("obs",), "unit": "m", "long_name": "mid-point depth of the sample",
                      "standard_name": "depth", "positive": "down"},
            "value": {"var_name": "value", "dim": ("obs",), "unit": "", "long_name": "measured value"},
            "value_qual": {"var_name": "value_qual", "dim": ("obs",), "unit": QUAL_UNITS, "long_name": "value_qual"},
            "variable": {"var_name": "variable", "dim": ("obs",), "unit": "1", "long_name": "measured variable"},
            "method_type": {"var_name": "method_type", "dim": ("obs",), "unit": "1", "long_name": "type of measurement method"},
            "method": {"var_name": "method", "dim": ("obs",), "unit": "", "long_name": "measurement method as given in the source"},
            "source_comment": {"var_name": "source_comment", "dim": ("obs",), "unit": "", "long_name": "comment given in the source"},
            "l0_row": {"var_name": "l0_row", "dim": ("obs",), "unit": "1", "long_name": "0-based data row index in the Level0 file"},
        }
        self.df = None
        self.qa_dict = {}

    def read_data(self, df):
        self.log.info("Reading {} Level0 rows for {}".format(len(df), self.key), indent=1)
        self.df = df.copy().sort_values(["time", "parameter", "depth_top", "depth_bottom", "l0_row"]).reset_index(drop=True)
        self.df["value_qual"] = 0
        self.df["repeat_group"] = -1
        self.df["repeat_flag"] = 0
        return len(self.df) > 0

    def resolve_repeats(self, corrections):
        """Repeated station/date/depth/variable keys.
        1. blank-method rows within DUPLICATE_TOLERANCE of a named-method row are dropped (keep the named row);
        2. rows with identical values: keep one (named method preferred);
        3. remaining differing rows are all kept; Level2 uses their mean, flagged unless (station, parameter) is in the source's `unflagged_repeats`."""
        self.log.info("Resolving repeated keys", indent=2)
        drop = []
        group_id = 0
        for _, g in self.df.groupby(["profile_key", "parameter", "DEPTH_m"]):
            if len(g) < 2:
                continue
            named = g[g["METHOD"] != ""]
            keep = list(g.index)
            if len(named) > 0:
                for i, r in g[g["METHOD"] == ""].iterrows():
                    diffs = np.abs(named["value"].values - r["value"])
                    if diffs.min() <= DUPLICATE_TOLERANCE + 1e-9:
                        match = named.iloc[int(np.argmin(diffs))]
                        drop.append(i)
                        keep.remove(i)
                        corrections.add(self.key, r, "dropped_duplicate", "Blank-method row duplicates the '{}' row (value {}) within {}; named-method row kept".format(
                            match["METHOD"], match["value"], DUPLICATE_TOLERANCE), "L1", new_value=match["value"])
            remaining = g.loc[keep].sort_values("METHOD", ascending=False)  # named methods first
            seen = []
            for i, r in remaining.iterrows():
                if r["value"] in seen:
                    drop.append(i)
                    keep.remove(i)
                    corrections.add(self.key, r, "dropped_identical_repeat", "Identical value repeated for the same station/date/depth/variable; one row kept", "L1", new_value=r["value"])
                else:
                    seen.append(r["value"])
            if len(keep) > 1:
                unflagged = [self.key, g["parameter"].iloc[0]] in self.source.get("unflagged_repeats", [])
                self.df.loc[keep, "repeat_group"] = group_id
                group_id += 1
                mean = float(self.df.loc[keep, "value"].mean())
                for i in keep:
                    r = self.df.loc[i]
                    if unflagged:
                        self.df.loc[i, "repeat_flag"] = 0
                        corrections.add(self.key, r, "repeat_kept_L2_mean", "Differing repeated measurements ({}) kept in Level1 unflagged (decision: two genuine readings); Level2 uses the mean".format(
                            ", ".join(str(v) for v in self.df.loc[keep, "value"])), "L1+L2", new_value=round(mean, 6))
                    else:
                        self.df.loc[i, "repeat_flag"] = 1
                        corrections.add(self.key, r, "repeat_kept_L2_mean_flagged", "Differing repeated measurements ({}) kept in Level1 with value_qual=1; Level2 uses the mean with _qual=1".format(
                            ", ".join(str(v) for v in self.df.loc[keep, "value"])), "L1+L2", new_value=round(mean, 6))
        self.df = self.df.drop(index=drop).reset_index(drop=True)
        self.df.loc[self.df["repeat_flag"] > 0, "value_qual"] = 1
        self.log.info("{} rows dropped, {} repeat groups kept".format(len(drop), group_id), indent=3)

    def flag_below_detection_limit(self, corrections):
        idx = self.df["comment_action"] == "below_detection_limit"
        for _, r in self.df[idx].iterrows():
            corrections.add(self.key, r, "flagged_below_dl", "Source comment '{}': below detection limit, value kept in Level1 with value_qual=1 and masked in Level2".format(r["COMMENTS"]), "L1+L2")
        self.df.loc[idx, "value_qual"] = 1
        self.log.info("{} below-detection-limit rows flagged".format(int(idx.sum())), indent=2)

    def flag_nitrate_above_total_nitrogen(self, corrections):
        """NO3 must not exceed TN in the same sample (station, date, depth range). If the source reports nitrate as
        NO3 (`parameter_basis`: {"NO3": "NO3"} in notes/sources.json) it is converted to N for this check only."""
        factor = N_PER_NO3 if self.source.get("parameter_basis", {}).get("NO3") == "NO3" else 1.0
        n = 0
        sub = self.df[self.df["parameter"].isin(["NO3", "TN"])]
        for _, g in sub.groupby(["profile_key", "DEPTH_m"]):
            no3 = g[g["parameter"] == "NO3"]
            tn = g[g["parameter"] == "TN"]
            if len(no3) == 0 or len(tn) == 0:
                continue
            if no3["value"].mean() * factor > tn["value"].mean():
                n += 1
                for i, r in pd.concat([no3, tn]).iterrows():
                    self.df.loc[i, "value_qual"] = 1
                    corrections.add(self.key, r, "flagged_no3_gt_tn", "NO3{} ({:g}) > TN ({:g}) in the same sample; both flagged (value_qual=1) and masked in Level2".format(
                        " converted to N" if factor != 1 else "", round(no3["value"].mean() * factor, 3), tn["value"].mean()), "L1+L2")
        self.log.info("{} samples with NO3 > TN flagged".format(n), indent=2)
        return n

    def quality_assurance(self, file_path="notes/quality_assurance.json", maintenance_file="notes/events.csv", corrections=None):
        """Range checks (envass simple bounds) per parameter on the long-format `value`, plus manual events.
        The shared GenericInstrument.quality_assurance() cannot be used: Level1 holds all parameters in one `value`
        variable, flags must be combined with the flags set above, and it only stores flags when events exist."""
        self.log.info("Applying quality assurance", indent=2)
        self.qa_dict = json_converter(json.load(open(file_path)))
        time = self.df["time"].values.astype(float)
        flag = np.zeros(len(self.df), dtype=int)
        reasons = [[] for _ in range(len(self.df))]
        if "time" in self.qa_dict:
            q = qualityassurance(time, time, **self.qa_dict["time"]["simple"])
            for i in np.where(q > 0)[0]:
                reasons[i].append("time outside QA bounds")
            flag |= q > 0
        for parameter in VARIABLE_CODES:
            idx = np.where(self.df["parameter"].values == parameter)[0]
            if len(idx) == 0 or parameter not in self.qa_dict:
                continue
            q = qualityassurance(self.df["value"].values[idx].astype(float), time[idx], **self.qa_dict[parameter]["simple"])
            for i in idx[q > 0]:
                reasons[i].append("value outside QA bounds {}".format(self.qa_dict[parameter]["simple"]["bounds"]))
            flag[idx[q > 0]] = 1
        if maintenance_file and os.path.exists(maintenance_file):
            events = pd.read_csv(maintenance_file, sep=";")
            for _, e in events.iterrows():
                start = datetime.strptime(e["start"], "%Y%m%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                stop = datetime.strptime(e["stop"], "%Y%m%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                parameter = str(e["parameter"])
                if "/" in parameter:
                    station, parameter = parameter.split("/", 1)
                    if station != self.key:
                        continue
                in_time = (time >= start) & (time <= stop)
                if parameter != "All":
                    in_time &= self.df["parameter"].values == parameter
                for i in np.where(in_time)[0]:
                    reasons[i].append("event: {}".format(e["comments"]))
                flag[in_time] = 1
        if corrections is not None:
            for i in np.where(flag > 0)[0]:
                corrections.add(self.key, self.df.iloc[i], "flagged_qa", "; ".join(reasons[i]), "L1+L2")
        self.df["value_qual"] = np.maximum(self.df["value_qual"].values, flag)
        self.log.info("{} values flagged by QA bounds/events".format(int(flag.sum())), indent=3)

    def to_dataset(self):
        df = self.df
        variables = {
            "time": df["time"].values.astype(np.float64),
            "time_source": df["time_source"].values.astype(np.int8),
            "depth_top": df["depth_top"].values.astype(np.float64),
            "depth_bottom": df["depth_bottom"].values.astype(np.float64),
            "depth": df["depth"].values.astype(np.float64),
            "value": df["value"].values.astype(np.float64),
            "value_qual": df["value_qual"].values.astype(np.int8),
            "variable": df["parameter"].map(VARIABLE_CODES).values.astype(np.int8),
            "method_type": df["method_type"].map(METHOD_TYPE_CODES).values.astype(np.int8),
            "method": df["METHOD"].values.astype(object),
            "source_comment": df["COMMENTS"].values.astype(object),
            "l0_row": df["l0_row"].values.astype(np.int32),
        }
        ds = xr.Dataset({k: (("obs",), v) for k, v in variables.items()}, attrs=self.general_attributes)
        for key, values in self.variables.items():
            attrs = {"long_name": values["long_name"]}
            if values["unit"]:
                attrs["units"] = values["unit"]
            for attr in ["comment", "standard_name", "positive", "calendar"]:
                if attr in values:
                    attrs[attr] = values[attr]
            ds[key].attrs = attrs
        ds["value"].attrs["comment"] = "Units depend on `variable`: " + "; ".join(
            "{} [{}] {}".format(k, self.parameter(k)["unit"], self.parameter(k)["long_name"]) for k in VARIABLE_CODES)
        ds["variable"].attrs.update({"flag_values": np.array(list(VARIABLE_CODES.values()), dtype=np.int8),
                                     "flag_meanings": " ".join(VARIABLE_CODES.keys()),
                                     "comment": " ".join("{}: {}".format(k, self.parameter(k)["comment"])
                                                         for k in sorted(set(df["parameter"]), key=VARIABLE_CODES.get))})
        ds["time_source"].attrs.update({"flag_values": np.array(list(TIME_SOURCE_CODES.values()), dtype=np.int8),
                                        "flag_meanings": "not_recorded_set_to_1200_UTC recorded_in_source mean_time_of_same_date"})
        ds["method_type"].attrs.update({"flag_values": np.array(list(METHOD_TYPE_CODES.values()), dtype=np.int8),
                                        "flag_meanings": " ".join(METHOD_TYPE_CODES.keys())})
        ds["value_qual"].attrs.update({"comment": "1 for below-detection-limit values, NO3 > TN samples, values outside QA bounds, "
                                                  "manual events and differing repeated measurements. See notes/corrections/{}.csv.".format(self.source_key)})
        return ds

    def write_netcdf(self, folder, title):
        os.makedirs(folder, exist_ok=True)
        out = os.path.join(folder, "{}.nc".format(title))
        if os.path.exists(out):
            os.remove(out)
        ds = self.to_dataset()
        encoding = {k: {"zlib": True, "complevel": 4} for k in ds.data_vars if ds[k].dtype != object}
        for k in ["time", "depth_top", "depth_bottom", "depth", "value"]:
            encoding[k]["_FillValue"] = np.nan
        for k in ["value_qual", "variable", "method_type", "time_source", "l0_row"]:
            encoding[k]["_FillValue"] = None
        ds.to_netcdf(out, encoding=encoding, format="NETCDF4")
        self.log.info("Written {} ({} obs)".format(out, len(self.df)), indent=2)
        return [out]


class InsituProfiles(InsituStation):
    """Level2 (depth, time) grid of single-depth probe measurements.

    Two modes, chosen per station in notes/stations.json:
    - snap (default): the grid is the station's nominal sampling depths, derived from the data; readings within
      SNAP_TOLERANCE of a more frequently sampled depth are snapped to it.
    - interpolate (`profile_interpolation`: {"grid": [[start, stop, step], ...], "max_gap": m or null}): for
      high-resolution or irregular-depth profilers, each profile is linearly interpolated onto the fixed grid from
      its unflagged readings, within the measured range only.
    Files are split into periods by split_periods(); each file holds only the depths with data in it."""

    product_key = "profiles"
    product_name = "Level2 profiles"
    variables_list = PROFILE_VARIABLES
    interpolation_key = "profile_interpolation"
    exclude_key = "exclude_depths"
    what = "Probe"

    def __init__(self, *args, **kwargs):
        super(InsituProfiles, self).__init__(*args, **kwargs)
        self.interpolation = self.station.get(self.interpolation_key)
        if self.interpolation:
            description = (self.what + " profiles linearly interpolated onto a fixed depth grid ({}) from the unflagged readings of "
                           "each profile, within the measured depth range only{}.".format(
                               ", ".join("{:g}-{:g} m every {:g} m".format(*g) for g in self.interpolation["grid"]),
                               "" if self.interpolation.get("max_gap") is None else
                               " and not across gaps larger than {:g} m".format(self.interpolation["max_gap"])))
        else:
            description = (self.what + " profiles on the station's nominal sampling depths, derived from the data (readings within "
                           "+/-{} m of a more frequently sampled depth are snapped to it). Values with _qual > 0 are "
                           "masked.".format(SNAP_TOLERANCE))
        self.set_general_attributes(self.product_name, description + " The record is split into files at year boundaries "
                                    "where the sampled depths change; each file contains only the depths sampled in it, so "
                                    "the depth axis can differ between files.")
        self.depths = None  # set in read_data
        self.dimensions = {
            "depth": {"dim_name": "depth", "dim_size": None},
            "time": {"dim_name": "time", "dim_size": None},
        }
        self.variables = {
            "time": {"var_name": "time", "dim": ("time",), "unit": TIME_UNITS, "long_name": "time", "standard_name": "time",
                     "calendar": "standard", "comment": TIME_COMMENT_L2},
            "depth": {"var_name": "depth", "dim": ("depth",), "unit": "m",
                      "long_name": "interpolation depth" if self.interpolation else "nominal sampling depth",
                      "standard_name": "depth", "positive": "down"},
        }

    def nominal_depths(self, df):
        """Nominal sampling depths of the station. `profile_depths` in notes/stations.json overrides; otherwise every
        depth that occurs is nominal unless it lies within SNAP_TOLERANCE of a depth sampled on more dates (such
        readings are snapped to that depth)."""
        override = self.station.get("profile_depths" if self.product_key == "profiles" else "lab_profile_depths")
        if override:
            return np.array(sorted(override), dtype=float)
        return nominal_grid(df["depth"].values, df["profile_key"].values)

    def read_data(self, df, corrections):
        df = df[df["product"] == self.product_key].copy()
        if len(df) == 0:
            return False
        self.log.info("Gridding {} {} readings for {}".format(len(df), self.what.lower(), self.key), indent=1)
        excluded = np.isin(df["depth"].values, np.array(self.station.get(self.exclude_key, []), dtype=float))
        for _, r in df[excluded].iterrows():
            corrections.add(self.key, r, "L1_only_excluded_depth", "Depth {} m is listed in exclude_depths (notes/stations.json); kept in Level1 only".format(r["depth"]), "L2")
        df = df[~excluded]
        if self.interpolation:
            return self.interpolate(df)
        self.depths = self.nominal_depths(df)
        self.dimensions["depth"]["dim_size"] = len(self.depths)
        dist = np.abs(df["depth"].values[:, None] - self.depths[None, :])
        nearest = dist.argmin(axis=1)
        ok = dist[np.arange(len(df)), nearest] <= SNAP_TOLERANCE + 1e-9
        df["grid_depth"] = np.where(ok, self.depths[nearest], np.nan)
        for _, r in df[~ok].iterrows():
            corrections.add(self.key, r, "L1_only_off_grid", "Depth {} m is more than {} m from the nominal grid; kept in Level1 only".format(r["depth"], SNAP_TOLERANCE), "L2")
        df = df[ok]
        for _, r in df[np.abs(df["depth"] - df["grid_depth"]) > 1e-9].iterrows():
            corrections.add(self.key, r, "depth_snapped", "Depth {} m snapped to nominal depth {} m in Level2 (old/new values are depths)".format(r["depth"], r["grid_depth"]),
                            "L2", old_value=r["depth"], new_value=r["grid_depth"])

        dates, times = date_times(df)
        self.data["time"] = times
        self.data["depth"] = self.depths
        self.present = np.zeros((len(self.depths), len(times)), dtype=bool)
        t_index = {t: i for i, t in enumerate(dates)}
        d_index = {d: i for i, d in enumerate(self.depths)}
        for parameter in self.variables_list:
            sub = df[df["parameter"] == parameter]
            if len(sub) == 0:
                continue
            p = self.parameter(parameter)
            self.variables[parameter] = {"var_name": parameter, "dim": ("depth", "time"), "unit": p["unit"], "long_name": p["long_name"], "comment": p["comment"]}
            self.variables[parameter + "_qual"] = {"var_name": parameter + "_qual", "dim": ("depth", "time"), "unit": QUAL_UNITS, "long_name": parameter + "_qual"}
            values = np.full((len(self.depths), len(times)), np.nan)
            qual = np.zeros((len(self.depths), len(times)))
            for (t, d), g in sub.groupby(["profile_key", "grid_depth"]):
                i, j = d_index[d], t_index[t]
                values[i, j] = g["value"].mean()
                q = g["value_qual"].max()
                if len(g) > 1 and (g["repeat_group"] < 0).any():
                    q = 1  # collision created by snapping, not a known repeat
                    for _, r in g.iterrows():
                        corrections.add(self.key, r, "L2_cell_mean_flagged", "Several readings fall in the same Level2 cell after snapping; mean used with _qual=1", "L2",
                                        new_value=round(float(g["value"].mean()), 6))
                qual[i, j] = q
            self.data[parameter] = values
            self.data[parameter + "_qual"] = qual
            self.present |= np.isfinite(values)  # before masking: depths with only flagged values are kept
        return True

    def interpolate(self, df):
        """Interpolation mode: one profile per sampling date and parameter, from readings with value_qual == 0 (repeated
        readings at one depth are averaged first). Interpolated cells have _qual = 0; everything else is NaN."""
        self.depths = depth_grid(self.interpolation["grid"])
        max_gap = self.interpolation.get("max_gap")
        self.dimensions["depth"]["dim_size"] = len(self.depths)
        good = df[df["value_qual"] == 0]
        dates, times = date_times(df)
        self.data["time"] = times
        self.data["depth"] = self.depths
        self.present = np.zeros((len(self.depths), len(times)), dtype=bool)
        t_index = {t: i for i, t in enumerate(dates)}
        for parameter in self.variables_list:
            if not (df["parameter"] == parameter).any():
                continue
            p = self.parameter(parameter)
            self.variables[parameter] = {"var_name": parameter, "dim": ("depth", "time"), "unit": p["unit"], "long_name": p["long_name"],
                                         "comment": " ".join([p["comment"], "Linearly interpolated onto the depth grid; Level1 holds the measured depths."])}
            self.variables[parameter + "_qual"] = {"var_name": parameter + "_qual", "dim": ("depth", "time"), "unit": QUAL_UNITS, "long_name": parameter + "_qual"}
            values = np.full((len(self.depths), len(times)), np.nan)
            for t, g in good[good["parameter"] == parameter].groupby("profile_key"):
                prof = g.groupby("depth")["value"].mean()
                values[:, t_index[t]] = interpolate_profile(prof.index.values.astype(float), prof.values.astype(float), self.depths, max_gap)
            self.data[parameter] = values
            self.data[parameter + "_qual"] = np.where(np.isfinite(values), 0.0, np.nan)
            self.present |= np.isfinite(values)
        self.log.info("Interpolated {} profiles onto {} depths".format(len(times), len(self.depths)), indent=2)
        return True

    def export_periods(self, folder, title):
        files = []
        for mask in split_periods(self.present, self.data["time"]):
            depth_index = np.where(self.present[:, mask].any(axis=1))[0]
            files.append(self.write_file(folder, title, mask, depth_index))
        return files


class InsituLabProfiles(InsituProfiles):
    """Level2 (depth, time) grid of lab samples taken at single depths (stations sampling several depths per date).
    Same snap / interpolate modes as InsituProfiles, configured with `lab_interpolation`, `lab_profile_depths` and
    `lab_exclude_depths` in notes/stations.json."""
    product_key = "lab_profiles"
    product_name = "Level2 lab profiles"
    variables_list = LAB_VARIABLES
    interpolation_key = "lab_interpolation"
    exclude_key = "lab_exclude_depths"
    what = "Lab sample"


class InsituSamples(InsituStation):
    """Level2 time series of Secchi depth and lab samples, split into named depth layers. One file per station: the
    product has no depth axis, so splitting it would not change how it is displayed."""

    def export_periods(self, folder, title):
        return [self.write_file(folder, title, np.ones(len(self.data["time"]), dtype=bool))]

    def __init__(self, *args, **kwargs):
        super(InsituSamples, self).__init__(*args, **kwargs)
        self.set_general_attributes("Level2 samples",
                                    "Secchi depth and laboratory samples (chlorophyll a, nutrients). Samples mixed over a depth "
                                    "range are assigned to layers: <var> = upper, <var>_column = whole column, <var>_mid = "
                                    "intermediate, <var>_deep = deepest; each has its own _qual and _depth_top/_depth_bottom. "
                                    "Values with _qual > 0 are masked.")
        self.dimensions = {"time": {"dim_name": "time", "dim_size": None}}
        self.variables = {
            "time": {"var_name": "time", "dim": ("time",), "unit": TIME_UNITS, "long_name": "time", "standard_name": "time",
                     "calendar": "standard", "comment": TIME_COMMENT_L2},
        }

    @staticmethod
    def assign_layers(ranges):
        """ranges: list of (top, bottom). Returns {layer_suffix: (top, bottom)}.
        - surface samples share the shallowest top depth;
        - two surface samples: the shorter is the upper layer, the longer the whole-column sample;
        - one surface sample reaching at least as deep as every other sample, with >= 2 others: whole-column sample,
          and the shallowest of the others is the upper layer;
        - of the rest, the one with the deepest bottom (then deepest top) is the deep layer, any other is the mid layer."""
        ranges = sorted(set(ranges))
        if len(ranges) == 1:
            return {"": ranges[0]}
        layers = {}
        rest = list(ranges)
        min_top = min(r[0] for r in rest)
        surface = sorted([r for r in rest if r[0] == min_top], key=lambda r: r[1])
        if len(surface) > 2:
            raise ValueError("More than two samples start at the surface: {}".format(ranges))
        if len(surface) == 2:
            layers[""], layers["_column"] = surface
            rest = [r for r in rest if r not in surface]
        else:
            others = [r for r in rest if r != surface[0]]
            if len(others) >= 2 and surface[0][1] >= max(r[1] for r in others):
                layers["_column"] = surface[0]
                rest = others
                layers[""] = sorted(rest)[0]
                rest = rest[1:]
            else:
                layers[""] = surface[0]
                rest = others
        if rest:
            deep = sorted(rest, key=lambda r: (r[1], r[0]))[-1]
            layers["_deep"] = deep
            rest = [r for r in rest if r != deep]
        if len(rest) > 1:
            raise ValueError("More than one intermediate layer: {}".format(ranges))
        if rest:
            layers["_mid"] = rest[0]
        return layers

    def read_data(self, df, corrections):
        df = df[df["product"] == "samples"].copy()
        if len(df) == 0:
            return False
        self.log.info("Building sample time series from {} rows for {}".format(len(df), self.key), indent=1)
        dates, times = date_times(df)
        t_index = {t: i for i, t in enumerate(dates)}
        self.data["time"] = times
        cells = {}  # (parameter, layer) -> {time index: (value, qual, top, bottom)}
        problems = []
        for (t, parameter), g in df.groupby(["profile_key", "parameter"]):
            samples = {}
            for (top, bottom), s in g.groupby(["depth_top", "depth_bottom"]):
                q = int(s["value_qual"].max())
                if len(s) > 1 and (s["repeat_group"] < 0).any():
                    q = 1
                samples[(top, bottom)] = (float(s["value"].mean()), q)
            if parameter == "Secchi":
                if len(samples) > 1:
                    # Several different Secchi depths on one date: mean, flagged (same rule as differing repeats)
                    mean = float(np.mean([v for v, _ in samples.values()]))
                    for _, r in g.iterrows():
                        corrections.add(self.key, r, "L2_secchi_mean_flagged", "Several different Secchi depths on the same date ({}); Level2 uses the mean with _qual=1".format(
                            ", ".join("{:g}".format(v) for v, _ in samples.values())), "L2", new_value=round(mean, 6))
                    samples = {(np.nan, np.nan): (mean, 1)}
                layers = {"": list(samples)[0]}
            else:
                try:
                    layers = self.assign_layers(list(samples))
                except ValueError as e:
                    problems.append((iso_date(t), parameter, str(e)))
                    continue
            for suffix, rng in layers.items():
                cells.setdefault((parameter, suffix), {})[t_index[t]] = samples[rng] + rng
        if problems:
            raise ValueError("Unresolved sample layers for {}: {}".format(self.key, problems))

        for parameter in SAMPLE_VARIABLES:
            for suffix, layer_desc in LAYERS.items():
                if (parameter, suffix) not in cells:
                    continue
                name = parameter + suffix
                p = self.parameter(parameter)
                values = np.full(len(times), np.nan)
                qual = np.zeros(len(times))
                top = np.full(len(times), np.nan)
                bottom = np.full(len(times), np.nan)
                for i, (v, q, a, b) in cells[(parameter, suffix)].items():
                    values[i], qual[i], top[i], bottom[i] = v, q, a, b
                long_name = p["long_name"] if parameter == "Secchi" else "{}, {}".format(p["long_name"], layer_desc)
                self.variables[name] = {"var_name": name, "dim": ("time",), "unit": p["unit"], "long_name": long_name, "comment": p["comment"]}
                self.variables[name + "_qual"] = {"var_name": name + "_qual", "dim": ("time",), "unit": QUAL_UNITS, "long_name": name + "_qual"}
                self.data[name] = values
                self.data[name + "_qual"] = qual
                if parameter != "Secchi":
                    self.variables[name + "_depth_top"] = {"var_name": name + "_depth_top", "dim": ("time",), "unit": "m",
                                                           "long_name": "top depth of the {} sample".format(name), "positive": "down"}
                    self.variables[name + "_depth_bottom"] = {"var_name": name + "_depth_bottom", "dim": ("time",), "unit": "m",
                                                              "long_name": "bottom depth of the {} sample".format(name), "positive": "down"}
                    self.data[name + "_depth_top"] = top
                    self.data[name + "_depth_bottom"] = bottom
        return True
