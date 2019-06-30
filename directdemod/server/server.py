"""
This module provides an functionality for implementing flask
web-server, which supports displaying NOAA images.
"""
import os
import re
import json
import time
import atexit

from typing import List
from shutil import copyfile
from flask import Flask, render_template, send_file, abort, request
from apscheduler.schedulers.background import BackgroundScheduler

APP = Flask(__name__)

CONF_PATH = APP.root_path + "/conf.json"
conf = json.load(open(CONF_PATH, 'r'))
RATE = int(conf["update_rate"])

start_date = time.time()
PATTERN = re.compile("SDRSharp_[0-9]{8}_[0-9]{6}Z_[0-9]{9}Hz_IQ.png$")


def get_interval(start_time: float, rate: int) -> str:
    """computes the interval and returns it's string representation

    Args:
        start_time (:obj:`float`): start of the interval
        rate (:obj:`int`): width of the interval in seconds

    Returns:
        :obj:`string`:
    """

    return time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime(start_time)) + "_" + \
           time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime(start_time + rate))


@APP.route('/upload.html', methods=['GET', 'POST'])
@APP.route('/upload', methods=['GET', 'POST'])
def upload_page():
    """renders upload.html page"""
    if request.method == 'POST':
        dir_path = APP.root_path + "/images/img" + get_interval(
            start_date, RATE)
        if not os.path.isdir(dir_path):
            os.mkdir(dir_path)

        for key in request.files.keys():
            file = request.files[key]
            if bool(PATTERN.match(file.filename)):
                file.save(dir_path + "/" + request.form["sat_type"] + "_" +
                          file.filename)

    return render_template('upload.html', conf=json.dumps(conf))


@APP.route('/map.html')
@APP.route('/map')
def map_page():
    """renders map.html page"""
    return render_template('map.html', conf=json.dumps(conf))


@APP.route('/globe.html')
@APP.route('/globe')
def globe_page():
    """renders globe.html page"""
    return render_template('globe.html', conf=json.dumps(conf))


@APP.route('/tms/<path:file>', methods=['GET'])
def get_tms(file: str):
    """gets file from tms directory

    Args:
        file (:obj:`string`): name of file from tms directory
    """

    file_name = APP.root_path + "/tms/" + file
    if not os.path.isfile(file_name):
        abort(404)
    return send_file(file_name)


def update() -> None:
    """processes data collected during this interval and
    saves the update, so it will be displayed during next
    page renders
    """

    global start_date
    interval = get_interval(start_date, RATE)
    dir_path = APP.root_path + "/images/img" + interval

    if not os.path.isdir(dir_path) or not os.listdir(dir_path):
        start_date += RATE
        return

    images = os.listdir(dir_path)
    tms_path = APP.root_path + "/tms/tms" + interval
    process(dir_path, tms_path, images)
    start_date += RATE
    move_unprocessed_files(dir_path, images)

    conf[conf["counter"]] = interval
    conf["counter"] += 1


def move_unprocessed_files(dir_path: str, images: List[str]) -> None:
    """moves all unprocessed files to the next time interval

    Args:
        dir_path (:obj:`str`): path to images directory
        images (:obj:list[str]): list of images paths
    """

    dimages = set(images)
    dgeo = set(map(lambda x: os.path.splitext(x)[0] + "_geo.tif", dimages))
    not_processed = []

    for file in os.listdir(dir_path):
        if file not in dimages and file not in dgeo and file != "merged.tif":
            not_processed.append(file)

    if not_processed:
        new_dir_path = APP.root_path + "/images/img" + get_interval(
            start_date, RATE)
        os.mkdir(new_dir_path)

        for file in not_processed:
            os.rename(dir_path + "/" + file, new_dir_path + "/" + file)


def process(dir_path: str, tms_path: str, images: List[str]) -> None:
    """processes all images from `images` array, merges them and creates tms
    which is store in `tms_path`

    Args:
        dir_path (:obj:`str`): path to images directory
        tms_path (:obj:`str`): path to tms directory
        images (:obj:list[str]): list of images paths
    """

    from directdemod.misc import save_metadata, preprocess
    from directdemod.georeferencer import Georeferencer, set_nodata
    from directdemod.merger import merge
    from directdemod.constants import TLE_NOAA

    sat_types = list(map(lambda f: f[0:7], images))
    images = list(map(lambda f: dir_path + "/" + f, images))
    georeferenced = list(
        map(lambda f: os.path.splitext(f)[0] + "_geo.tif", images))
    referencer = Georeferencer(tle_file=TLE_NOAA)

    for index, val in enumerate(images):
        try:
            preprocess(val, georeferenced[index])
            save_metadata(
                file_name=val,
                image_name=georeferenced[index],
                sat_type=sat_types[index],  # extracting NOAA satellite
                tle_file=TLE_NOAA)
            referencer.georef_tif(georeferenced[index], georeferenced[index])
        except Exception as exp:
            print(exp)
            # FIXME: add logging
            continue

    merged_file = dir_path + "/merged.tif"
    if len(georeferenced) > 1:
        merge(georeferenced, output_file=merged_file)
        os.system("gdal2tiles.py --profile=mercator -z 1-6 -w none " +
                  merged_file + " " + tms_path)
    elif len(georeferenced) == 1:
        copyfile(georeferenced[0], merged_file)
        set_nodata(merged_file, value=0)
        os.system("gdal2tiles.py --profile=mercator -z 1-6 -w none " +
                  merged_file + " " + tms_path)

    save_conf()


def save_conf() -> None:
    """saves configuration file"""
    with open(CONF_PATH, 'w') as out:
        json.dump(conf, out)


def main() -> None:
    """registers scheduler jobs and onExit functions"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=update, trigger="interval", seconds=RATE)
    scheduler.start()
    atexit.register(scheduler.shutdown)
    atexit.register(save_conf)


main()  # DON'T  ADD __name__ == '__main__'
