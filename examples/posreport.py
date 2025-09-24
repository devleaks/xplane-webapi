"""Send position report periodically

Extrernal (to X-Plane) application to detect OOOI ACARS message changes and generate appropriate message.

/data2/19//N/POSITION REPORT OVHD HABBS AT 1249Z/18700 PPOS:4512.2N/07425.3W AT 1249Z/18700 TO COMAU AT 1252Z NEXT MITIG WIND 325/23 SAT -20 ETA 1304Z SPEED 265 GND SPEED 354 VERT SPEED -2000FPM HDG 68 TRK 71
/data2/18//N/POSITION REPORT OVHD ARVIE AT 1247Z/FL221 PPOS:4507.0N/07437.2W AT 1247Z/FL221 TO HABBS AT 1249Z NEXT COMAU WIND 350/21 SAT -27 ETA 1304Z SPEED 260 GND SPEED 357 VERT SPEED -1900FPM HDG 69 TRK 73

"""

import logging
import os
import sys
import argparse
from re import DEBUG
from datetime import datetime, timezone
from enum import StrEnum
from typing import Dict, Any, Tuple

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lat_lon_parser import to_deg_min
from unitutil import convert

import xpwebapi
from xpwsapp import XPWSAPIApp

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


version = "1.0.0"


class DATAREFS(StrEnum):
    DAYS = "sim/time/local_date_days"
    ZULU_SECS = "sim/time/zulu_time_sec"
    GROUND_SPEED = "sim/flightmodel2/position/groundspeed"
    AGL = "sim/flightmodel/position/y_agl"
    ALT = "sim/cockpit/pressure/cabin_altitude_actual_ft"
    TRK = "sim/cockpit2/gauges/indicators/ground_track_mag_pilot"  # The ground track of the aircraft in degrees magnetic
    HDG = "sim/cockpit2/gauges/indicators/compass_heading_deg_mag"  # Indicated heading of the wet compass, in degrees.
    INDICATED_AIRSPEED = "sim/flightmodel/position/indicated_airspeed"
    VS = "sim/flightmodel/position/local_vy"
    LATITUDE = "sim/flightmodel/position/latitude"
    LONGITUDE = "sim/flightmodel/position/longitude"
    WINDDIR = "sim/weather/aircraft/wind_now_direction_degt"
    WINDSPD = "sim/weather/aircraft/wind_speed_kts"
    WINDSPD_M = "sim/weather/aircraft/wind_now_speed_msc"
    AIR_TEMP = "sim/weather/aircraft/temperature_ambient_deg_c"


def now() -> datetime:
    return datetime.now(timezone.utc)


class PositionReport(XPWSAPIApp):

    def __init__(self, api, frequency: int, callsign: str, logon: str, station: str, eta: datetime | None = None) -> None:
        XPWSAPIApp.__init__(self, api=api)
        self.frequency = frequency

    def get_dataref_names(self) -> set:
        return DATAREFS

    def loop(self):
        while not self.finish.is_set():
            try:
                print(self.report())
                logger.debug(self.report())
            except:
                logger.warning("error producing report", exc_info=True)
            self.finish.wait(self.frequency)

    def report(self) -> str:
        def f(dref: str, rnd: int = 0) -> int | float:
            val = self.dataref_value(dataref=dref)
            if val is not None:
                return int(val) if rnd == 0 else round(val, rnd)
            return 0

        lat = self.dataref_value(DATAREFS.LATITUDE)
        ldeg, lmin = to_deg_min(lat)
        latstr = f"{int(ldeg):02d}{lmin:04.1f}{'N' if ldeg >=0 else 'S'}"
        lon = self.dataref_value(DATAREFS.LONGITUDE)
        ldeg, lmin = to_deg_min(lon)
        lonstr = f"{int(ldeg):03d}{lmin:04.1f}{'E' if ldeg >=0 else 'W'}"

        zulustr = now().strftime("%H%M")

        vs = self.dataref_value(DATAREFS.VS)
        vs = convert.ms_to_fpm(ms=vs)
        vs = round(vs/100) * 100
        alt = self.dataref_value(DATAREFS.ALT)
        if alt < 8000:
            altstr = f"{round(alt/10) * 10}"
        else:
            altstr = convert.meters_to_fl(convert.feet_to_meters(ft=alt))

        # find weather parameters for layer
        wind_dir = int(self.dataref_value(DATAREFS.WINDDIR))
        wind_speeds = self.dataref_value(DATAREFS.WINDSPD)
        wind_speed = int(wind_speeds[0])
        sat = int(self.dataref_value(DATAREFS.AIR_TEMP))

        return " ".join([
            "POSITION REPORT",
            f"PPOS:{latstr}/{lonstr} AT {zulustr}Z/{altstr}",
            f"WIND {wind_dir}/{wind_speed} SAT {sat}",
            f"SPEED {f(DATAREFS.INDICATED_AIRSPEED)} GND SPEED {f(DATAREFS.GROUND_SPEED)} VERT SPEED {vs}FPM",
            f"HDG {f(DATAREFS.HDG)} TRK {f(DATAREFS.TRK)}",
            "PARTIAL AUTOGEN"
        ])


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Show simulator time")
    parser.add_argument("--version", action="store_true", help="shows version information and exit")
    parser.add_argument("--use-beacon", action="store_true", help="REMOTE USE ONLY: attempt to use X-Plane UDP beacon to discover network address")
    parser.add_argument("--host", nargs=1, help="REMOTE USE ONLY: X-Plane hostname or ip address (default to localhost)")
    parser.add_argument("--port", nargs="?", help="REMOTE USE ONLY: X-Plane web api TCP/IP port number (defatul to 8086)")
    parser.add_argument("-v", "--verbose", action="store_true", help="shows more information")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    if args.version:
        print(version)
        os._exit(0)

    probe = None
    api = None

    if args.use_beacon:
        probe = xpwebapi.beacon()
        api = xpwebapi.ws_api()
        probe.set_callback(api.beacon_callback)
        probe.start_monitor()
    else:
        if args.host is not None and args.port is not None:
            if args.verbose:
                logger.info(f"api at {args.host}:{args.port}")
            api = xpwebapi.ws_api(host=args.host, port=args.port)
        else:
            if args.verbose:
                logger.info("api at localhost:8086")
            api = xpwebapi.ws_api()

    logger.debug("starting..")
    app = PositionReport(api, frequency=5, callsign="BEL034", logon="none", station="EBJA")
    try:
        app.run()
    except KeyboardInterrupt:
        logger.warning("terminating..")
        app.terminate()
        logger.warning("..terminated")
