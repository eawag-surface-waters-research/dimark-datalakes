# -*- coding: utf-8 -*-
"""
Profile one SOURCE of a DiMark export before adding it to the pipeline, and print draft entries for
notes/sources.json and notes/stations.json. Nothing is written; review the output and complete the TODOs by hand.

    python scripts/inventory.py                         # list all sources in the export
    python scripts/inventory.py --source "SI-ARSO"      # profile one source
"""
import os
import re
import json
import argparse
import unicodedata
import numpy as np
import pandas as pd
from insitu import read_level0, DIMARK_VARIABLES, SAMPLE_VARIABLES, InsituSamples, profile_structure

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_FILE = os.path.join(REPO, "data", "Level0", "Database DiMark 19_02_2026(in).csv")


def ascii_id(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def section(title):
    print("\n== {} ==".format(title))


def inventory(df, source):
    df = df[df["SOURCE"] == source].copy()
    if len(df) == 0:
        raise ValueError("No rows with SOURCE == {}".format(source))
    df["date"] = pd.to_datetime(df["DATE"], format="%d/%m/%Y")
    df["is_range"] = df["DEPTH_m"].str.contains("_")
    df["top"] = df["DEPTH_m"].str.split("_").str[0].astype(float)
    df["bottom"] = df["DEPTH_m"].str.split("_").str[-1].astype(float)
    df["value"] = df["VALUE"].astype(float)
    print("{}: {} rows, {} lakes, {} stations, {} to {}".format(source, len(df), df["LAKE"].nunique(),
          df.groupby(["LAKE", "STATION"]).ngroups, df["date"].min().date(), df["date"].max().date()))

    section("Stations")
    print(df.groupby(["LAKE", "STATION", "LAT", "LON"]).agg(rows=("value", "size"), dates=("date", "nunique"),
          first=("date", "min"), last=("date", "max")).to_string())

    section("TIME column")
    filled = df["TIME"] != ""
    print("filled in {} of {} rows; examples: {}".format(int(filled.sum()), len(df), df.loc[filled, "TIME"].value_counts().head(8).to_dict()))
    per_day = df.groupby(["LAKE", "STATION", "DATE"])["TIME"].nunique()
    print("max distinct times per station-date: {}".format(per_day.max()))

    section("VARIABLE x METHOD (rows, of which depth ranges)")
    print(df.groupby(["VARIABLE", "METHOD"]).agg(rows=("value", "size"), ranges=("is_range", "sum"),
          vmin=("value", "min"), vmax=("value", "max")).to_string())
    unknown = set(df["VARIABLE"]) - set(DIMARK_VARIABLES)
    if unknown:
        print("UNKNOWN VARIABLES (add to DIMARK_VARIABLES / PARAMETERS first): {}".format(unknown))

    section("COMMENTS")
    print(df["COMMENTS"].value_counts().to_string())

    section("Repeated station/date/depth/variable/method-group keys")
    key = ["LAKE", "STATION", "DATE", "DEPTH_m", "VARIABLE"]
    size = df.groupby(key)["value"].transform("size")
    rep = df[size > 1]
    if len(rep):
        summary = rep.groupby(key).agg(methods=("METHOD", lambda m: " | ".join(sorted(m))), spread=("value", lambda v: v.max() - v.min()))
        print(summary.groupby(["LAKE", "VARIABLE", "methods"]).agg(keys=("spread", "size"), identical=("spread", lambda s: int((s == 0).sum())),
              le_0_05=("spread", lambda s: int((s <= 0.05 + 1e-9).sum())), max_spread=("spread", "max")).to_string())
    else:
        print("none")

    section("Sample layers per date (ranges and lab variables)")
    lab = df[df["is_range"] | df["VARIABLE"].map(lambda v: DIMARK_VARIABLES.get(v) in SAMPLE_VARIABLES and v != "SecchiDisk_m")]
    problems = []
    for (lake, station, date, var), g in lab.groupby(["LAKE", "STATION", "DATE", "VARIABLE"]):
        ranges = sorted(set(zip(g["top"], g["bottom"])))
        if len(ranges) > 2:
            try:
                InsituSamples.assign_layers(ranges)
            except ValueError as e:
                problems.append((lake, station, date, var, str(e)))
    counts = lab.groupby(["LAKE", "STATION", "DATE", "VARIABLE"])["DEPTH_m"].nunique().value_counts().sort_index()
    print("layers per date/variable: {}".format(counts.to_dict()))
    print("dates the layer rule cannot resolve: {}".format(problems if problems else "none"))

    section("NO3 > TN")
    p = df[df["VARIABLE"].isin(["TN_ug/L", "NO3_ug/L"])].pivot_table(index=["LAKE", "STATION", "DATE", "DEPTH_m"], columns="VARIABLE", values="value", aggfunc="mean")
    if {"TN_ug/L", "NO3_ug/L"} <= set(p.columns):
        p = p.dropna()
        bad = p["NO3_ug/L"] > p["TN_ug/L"]
        print(bad.groupby(level="LAKE").agg(["sum", "size", "mean"]).to_string())
    else:
        print("TN and NO3 not both present")

    section("Single-depth readings per station (the Level2 grid is derived from these; see exclude_depths)")
    single = df[~df["is_range"] & (df["VARIABLE"] != "SecchiDisk_m")]
    for (lake, station), g in single.groupby(["LAKE", "STATION"]):
        print("{} / {}: {}".format(lake, station, g["DEPTH_m"].value_counts().sort_index(key=lambda s: s.astype(float)).to_dict()))

    section("Profile depth structure (snap to nominal depths, or interpolate onto a fixed grid?)")
    probe = single[single["VARIABLE"].isin(["WaterTemperature_C", "Chlorophyll_ug/L", "Turbidity_NTU"])]
    for (lake, station), g in probe.groupby(["LAKE", "STATION"]):
        p = profile_structure(g["top"].values, g["DATE"].values)
        print("{} / {}: {} nominal depths, median {:g} per profile, within-profile coverage {:.0%}, deepest {:g} m -> {}".format(
            lake, station, p["nominal_depths"], p["median_depths_per_profile"], p["coverage"], g["top"].max(),
            "INTERPOLATE: add profile_interpolation {grid: [[start, stop, step], ...], max_gap} to stations.json"
            if p["interpolate"] else "snap to nominal depths (default)"))

    section("Draft notes/sources.json entry")
    draft = {ascii_id(source): {
        "source": source, "enabled": False, "level0_file": os.path.basename(DEFAULT_FILE), "provider": "TODO",
        "country": "TODO", "time_zone": "UTC",
        "methods": [{"variable": v, "method": m, "method_type": "TODO: probe | lab | secchi_disk | not_recorded"}
                    | ({"parameter": "TODO: Chla_probe | Chla_lab"} if v == "Chlorophyll_ug/L" else {})
                    for v, m in sorted(set(zip(df["VARIABLE"], df["METHOD"])))],
        "comments": {c: "TODO: none | below_detection_limit | station_metadata | keep" for c in sorted(df["COMMENTS"].unique())},
        "unflagged_repeats": [], "parameter_comments": {}}}
    print(json.dumps(draft, ensure_ascii=False, indent=2))

    section("Draft notes/stations.json entries")
    stations = {}
    for (lake, station), g in df.groupby(["LAKE", "STATION"]):
        stations["{}_{}".format(ascii_id(lake), ascii_id(station))] = {
            "source": ascii_id(source), "lake_name": lake, "lake_id": "TODO (Alplakes key, e.g. {})".format(ascii_id(lake)),
            "lake_long_name": lake, "station_name": station, "station_id": ascii_id(station), "station_description": "TODO",
            "latitude": float(g["LAT"].iloc[0]), "longitude": float(g["LON"].iloc[0]), "altitude": None,
            "exclude_depths": [], "comment": ""}
    print(json.dumps(stations, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", "-f", default=DEFAULT_FILE, help="DiMark export (Level0)")
    parser.add_argument("--source", "-s", help="Exact SOURCE value to profile; omit to list sources")
    args = parser.parse_args()
    data = read_level0(args.file)
    if args.source is None:
        print(data.groupby("SOURCE").agg(rows=("VALUE", "size"), lakes=("LAKE", "nunique"), stations=("STATION", "nunique")).to_string())
    else:
        pd.set_option("display.width", 250)
        pd.set_option("display.max_rows", 1000)
        pd.set_option("display.max_colwidth", 80)
        inventory(data, args.source)
