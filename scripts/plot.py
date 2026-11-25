# -*- coding: utf-8 -*-
"""
Write one PNG per NetCDF file, mirroring the data folder structure:

    data/Level2/bled_zahodna_kotanja/L2_Profiles_..._20200101_000000.nc -> plots/Level2/bled_zahodna_kotanja/L2_Profiles_..._20200101_000000.png

    python scripts/plot.py                                     # all Level1 and Level2 files
    python scripts/plot.py data/Level2/bled_zahodna_kotanja    # one folder (or individual .nc files)
    python scripts/plot.py --output /tmp/plots --dpi 150

Layouts
- Level1 (L1_*):           one panel per variable, value against time, coloured by sample mid-point depth;
                           flagged values (value_qual > 0) are drawn as crosses.
- Level2 Profiles and
  LabProfiles:             one row per variable: profiles (value against depth, one line per date; at most 12 dates
                           spread over the file) and a depth-time heatmap. Flagged values are already masked in Level2.
- Level2 Samples:          one panel per variable, time series of each sample layer (upper, column, mid, deep).
"""
import os
import glob
import argparse
import numpy as np
import pandas as pd
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Fixed categorical order for sample layers (identity), never cycled.
LAYER_COLORS = {"": "#2a78d6", "_column": "#eb6834", "_mid": "#1baf7a", "_deep": "#eda100"}
LAYER_LABELS = {"": "upper", "_column": "column", "_mid": "mid", "_deep": "deep"}
# Single-hue sequential ramps for magnitude.
HEATMAP_CMAPS = {"Temp": "Reds", "Chla_probe": "Greens", "Chla_lab": "Greens", "Turbidity": "Greys", "TN": "Purples", "NH4": "Purples",
                 "NO3": "Purples", "NO2": "Purples", "TP": "Oranges", "PO4": "Oranges", "SiO2": "Greys"}
# Depth ramp starts at a mid blue so shallow (0.5 m) points stay visible on the white surface.
DEPTH_CMAP = matplotlib.colors.LinearSegmentedColormap.from_list("depth", plt.get_cmap("Blues")(np.linspace(0.35, 1, 256)))
TEXT = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"
SAMPLE_VARIABLES = ["Secchi", "Chla_lab", "TN", "TP", "NH4", "NO3", "NO2", "PO4", "SiO2"]
PROFILE_VARIABLES = ["Temp", "Chla_probe", "Turbidity"]
MAX_PROFILES = 12

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9, "axes.edgecolor": MUTED, "axes.labelcolor": TEXT,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False,
    "figure.facecolor": "white",
})


def label(ds, var):
    units = ds[var].attrs.get("units", "")
    return "{} ({})".format(var, units) if units else var


def title(ds, file):
    return "{} - {}\n{}".format(ds.attrs.get("lake", ""), ds.attrs.get("station", ""), os.path.basename(file))


def times(ds):
    return pd.to_datetime(ds["time"].values, unit="s") if np.issubdtype(ds["time"].dtype, np.number) else pd.to_datetime(ds["time"].values)


def set_date_axis(ax):
    locator = mdates.AutoDateLocator(minticks=3, maxticks=10)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def plot_level1(ds, file):
    codes = dict(zip(ds["variable"].attrs["flag_values"].tolist(), ds["variable"].attrs["flag_meanings"].split()))
    var_codes = [c for c in codes if (ds["variable"].values == c).any()]
    t = times(ds)
    fig, axes = plt.subplots(len(var_codes), 1, figsize=(12, 2.2 * len(var_codes) + 0.8), sharex=True, squeeze=False,
                             layout="constrained")
    depth = ds["depth"].values
    norm = plt.Normalize(0, max(np.nanmax(depth), 1))
    for ax, code in zip(axes[:, 0], var_codes):
        name = codes[code]
        sel = ds["variable"].values == code
        flagged = sel & (ds["value_qual"].values > 0)
        ok = sel & ~flagged
        sc = ax.scatter(t[ok], ds["value"].values[ok], c=depth[ok], cmap=DEPTH_CMAP, norm=norm, s=10, linewidths=0)
        if flagged.any():
            ax.scatter(t[flagged], ds["value"].values[flagged], marker="x", color=TEXT, s=18, linewidths=0.8,
                       label="flagged (value_qual = 1): {}".format(int(flagged.sum())))
            ax.legend(loc="upper left", fontsize=8)
        ax.set_ylabel(name)
        ax.set_title("{}  ({} values)".format(name, int(sel.sum())), loc="left", color=TEXT)
    set_date_axis(axes[-1, 0])
    fig.colorbar(sc, ax=axes[:, 0].tolist(), label="mid-point depth (m)", shrink=0.4, aspect=30, pad=0.01)
    fig.suptitle(title(ds, file), x=0.01, ha="left", color=TEXT)
    return fig


def plot_profiles(ds, file):
    """Probe Profiles and LabProfiles files: every (depth, time) variable."""
    grid_vars = [v for v in ds.data_vars if ds[v].dims == ("depth", "time") and not v.endswith("_qual")]
    variables = [v for v in grid_vars if np.isfinite(ds[v].values).any()] or grid_vars[:1]
    t = times(ds)
    depth = ds["depth"].values
    fig, axes = plt.subplots(len(variables), 2, figsize=(12, 3.6 * len(variables) + 0.8), squeeze=False,
                             gridspec_kw={"width_ratios": [1, 2.4]})
    # Files can span many years: draw at most MAX_PROFILES dates, spread evenly over the file.
    shown = np.unique(np.linspace(0, len(t) - 1, min(len(t), MAX_PROFILES)).round().astype(int))
    date_colors = dict(zip(shown, plt.get_cmap("Blues")(np.linspace(0.35, 1, len(shown)))))
    for row, var in enumerate(variables):
        values = ds[var].values
        ax = axes[row, 0]
        for j in shown:
            col = values[:, j]
            if np.isfinite(col).any():
                ax.plot(col, depth, "-o", color=date_colors[j], lw=1.5, ms=3, label=t[j].strftime("%Y-%m-%d"))
        ax.set_ylim(depth.max() + 0.5, 0)
        ax.set_xlabel(label(ds, var))
        ax.set_ylabel("depth (m)")
        ax.set_title("{} profiles{}".format(var, "" if len(shown) == len(t) else " ({} of {} times)".format(len(shown), len(t))), loc="left", color=TEXT)
        if row == 0 and len(shown) > 1:  # dates are the same for every variable: one legend, outside the plot
            ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(0.0, -0.18), ncol=min(len(t), 4))
        ax = axes[row, 1]
        ax.grid(False)
        if np.isfinite(values).any() and len(depth) > 1:
            m = ax.pcolormesh(t, depth, values, shading="nearest", cmap=HEATMAP_CMAPS.get(var, "Greys"))
            fig.colorbar(m, ax=ax, label=label(ds, var), pad=0.01)
            ax.set_ylim(depth.max() + 0.5, 0)
        elif np.isfinite(values).any():
            ax.grid(True)
            ax.plot(t, values[0], "-o", color=LAYER_COLORS[""], lw=1.5, ms=4)
            ax.set_ylabel("{} at {:g} m".format(label(ds, var), depth[0]))
        else:
            ax.text(0.5, 0.5, "no {} data in this file".format(var), transform=ax.transAxes, ha="center", color=MUTED)
        ax.set_title("{} depth-time ({} times, {} depths)".format(var, len(t), len(depth)), loc="left", color=TEXT)
        set_date_axis(ax)
        ax.set_xlim(t.min() - pd.Timedelta(days=7), t.max() + pd.Timedelta(days=7))
    fig.suptitle(title(ds, file), x=0.01, ha="left", color=TEXT)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.75 / fig.get_figheight()))  # room for the two-line title
    return fig


def plot_samples(ds, file):
    variables = [v for v in SAMPLE_VARIABLES if v in ds]
    t = times(ds)
    fig, axes = plt.subplots(len(variables), 1, figsize=(12, 1.9 * len(variables) + 0.8), sharex=True, squeeze=False)
    for ax, var in zip(axes[:, 0], variables):
        n_layers = 0
        for suffix, color in LAYER_COLORS.items():
            name = var + suffix
            if name not in ds:
                continue
            v = ds[name].values
            ok = np.isfinite(v)
            if not ok.any():
                continue
            n_layers += 1
            rng = ""
            if name + "_depth_top" in ds:
                # the sampled range can change from date to date: list the distinct ranges
                pairs = sorted(set(zip(ds[name + "_depth_top"].values[ok], ds[name + "_depth_bottom"].values[ok])))
                text = ["{:g}".format(a) if a == b else "{:g}-{:g}".format(a, b) for a, b in pairs]
                rng = ": " + (", ".join(text) + " m" if len(text) <= 3 else "{} different depth ranges".format(len(text)))
            ax.plot(t[ok], v[ok], "-o", color=color, lw=1.5, ms=4, label=LAYER_LABELS[suffix] + rng)
        if n_layers == 0:
            ax.text(0.5, 0.5, "no valid {} data in this file".format(var), transform=ax.transAxes, ha="center", color=MUTED)
        elif n_layers > 1 or var != "Secchi":
            ax.legend(fontsize=7, loc="center left", bbox_to_anchor=(1.0, 0.5))
        if var == "Secchi":
            ax.invert_yaxis()
        ax.set_ylabel(label(ds, var))
    set_date_axis(axes[-1, 0])
    axes[-1, 0].set_xlim(t.min() - pd.Timedelta(days=7), t.max() + pd.Timedelta(days=7))
    fig.suptitle(title(ds, file), x=0.01, ha="left", color=TEXT)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.75 / fig.get_figheight()))  # room for the two-line title
    return fig


def plot_file(file, data_root, output):
    name = os.path.basename(file)
    with xr.open_dataset(file, decode_times=False) as ds:
        ds = ds.load()
    if name.startswith("L1_"):
        fig = plot_level1(ds, file)
    elif name.startswith("L2_Profiles_") or name.startswith("L2_LabProfiles_"):
        fig = plot_profiles(ds, file)
    elif name.startswith("L2_Samples_"):
        fig = plot_samples(ds, file)
    else:
        print("Skipping unrecognised file {}".format(file))
        return None
    rel = os.path.relpath(file, data_root)
    out = os.path.join(output, os.path.splitext(rel)[0] + ".png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)
    return out


def collect(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            files.extend(glob.glob(os.path.join(path, "**", "*.nc"), recursive=True))
        elif path.endswith(".nc"):
            files.append(path)
    return sorted(set(os.path.abspath(f) for f in files))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=[os.path.join(REPO, "data", "Level1"), os.path.join(REPO, "data", "Level2")],
                        help="NetCDF files or folders (default: data/Level1 and data/Level2)")
    parser.add_argument("--output", "-o", default=os.path.join(REPO, "plots"), help="Output folder (default: plots/)")
    parser.add_argument("--dpi", type=int, default=110)
    args = parser.parse_args()
    files = collect(args.paths)
    data_root = os.path.join(REPO, "data")
    written = 0
    for f in files:
        root = data_root if os.path.commonpath([f, data_root]) == data_root else os.path.dirname(f)
        if plot_file(f, root, args.output):
            written += 1
    print("Written {} plots to {}".format(written, args.output))
