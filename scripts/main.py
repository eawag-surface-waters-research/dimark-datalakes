# -*- coding: utf-8 -*-
import os
import shutil
import argparse
from insitu import InsituLevel1, InsituProfiles, InsituLabProfiles, InsituSamples, Corrections, load_config, read_level0, select_source, sha256
from general.functions import logger


def main(logs=False, sources=None, stations=None):
    """Process every enabled source in notes/sources.json (or only `sources`, a list of source keys), optionally
    restricted to the station keys in `stations`."""
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if logs:
        log = logger(os.path.join(repo, "logs/dimark"))
    else:
        log = logger()
    log.initialise("Processing DiMark in-situ lake data")
    directories = {f: os.path.join(repo, "data", f) for f in ["Level0", "Level1", "Level2"]}
    for directory in directories:
        os.makedirs(directories[directory], exist_ok=True)
    notes = os.path.join(repo, "notes")
    qa_file = os.path.join(notes, "quality_assurance.json")
    events_file = os.path.join(notes, "events.csv")
    os.makedirs(os.path.join(notes, "corrections"), exist_ok=True)
    source_config, station_config = load_config(notes)
    if sources is None:
        sources = [k for k, s in source_config.items() if s.get("enabled", False)]
    unknown = set(sources) - set(source_config)
    if unknown:
        raise ValueError("Unknown sources {}; configured: {}".format(unknown, list(source_config)))
    edited_files = []
    level0_cache = {}

    for source_key in sources:
        source = source_config[source_key]
        log.begin_stage("Collecting inputs for {} ({})".format(source_key, source["source"]))
        file = os.path.join(directories["Level0"], source["level0_file"])
        if not os.path.isfile(file):
            raise ValueError("Level0 file not found: {}".format(file))
        if file not in level0_cache:
            level0_cache[file] = (read_level0(file), sha256(file))
        df, file_sha256 = level0_cache[file]
        log.info("{} (sha256 {})".format(file, file_sha256))
        rows = select_source(df, source_key, source, station_config)
        log.info("{} rows with SOURCE == {}".format(len(rows), source["source"]))
        log.end_stage()

        log.begin_stage("Processing {}".format(source_key))
        corrections = Corrections()
        keys = [k for k, s in station_config.items() if s["source"] == source_key and (stations is None or k in stations)]
        for key in keys:
            station = station_config[key]
            args = (key, station, source_key, source, file, file_sha256)
            for level in ["Level1", "Level2"]:
                folder = os.path.join(directories[level], key)
                if os.path.isdir(folder):
                    shutil.rmtree(folder)  # full reprocessing from a single export; export() would otherwise append

            sensor = InsituLevel1(*args, log=log)
            if not sensor.read_data(rows[rows["station_key"] == key]):
                log.warning("No data for {}".format(key))
                continue
            sensor.resolve_repeats(corrections)
            sensor.flag_below_detection_limit(corrections)
            sensor.flag_nitrate_above_total_nitrogen(corrections)
            sensor.quality_assurance(file_path=qa_file, maintenance_file=events_file, corrections=corrections)
            edited_files.extend(sensor.write_netcdf(os.path.join(directories["Level1"], key), "L1_{}".format(key)))
            level1 = sensor.df

            sensor = InsituProfiles(*args, log=log)
            if sensor.read_data(level1, corrections):
                sensor.mask_data()
                edited_files.extend(sensor.export_periods(os.path.join(directories["Level2"], key), "L2_Profiles_{}".format(key)))

            sensor = InsituLabProfiles(*args, log=log)
            if sensor.read_data(level1, corrections):
                sensor.mask_data()
                edited_files.extend(sensor.export_periods(os.path.join(directories["Level2"], key), "L2_LabProfiles_{}".format(key)))

            sensor = InsituSamples(*args, log=log)
            if sensor.read_data(level1, corrections):
                sensor.mask_data()
                edited_files.extend(sensor.export_periods(os.path.join(directories["Level2"], key), "L2_Samples_{}".format(key)))

        if stations is None:
            out = corrections.to_csv(os.path.join(notes, "corrections", "{}.csv".format(source_key)))
            log.info("Written notes/corrections/{}.csv ({} rows)".format(source_key, len(out)))
            for (station, action), n in out.groupby(["station", "action"]).size().items():
                log.info("{:<24} {:<30} {}".format(station, action, n), indent=1)
        else:
            log.warning("Station subset processed: notes/corrections/{}.csv not rewritten".format(source_key))
        log.end_stage()

    return edited_files


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--logs', '-l', help="Write logs to file", action='store_true')
    parser.add_argument('--source', '-s', nargs="+", help="Source keys from notes/sources.json (default: all enabled sources)")
    parser.add_argument('--station', '-st', nargs="+", help="Only process these station keys from notes/stations.json")
    args = vars(parser.parse_args())
    main(logs=args["logs"], sources=args["source"], stations=args["station"])
