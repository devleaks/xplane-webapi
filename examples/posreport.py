"""Send position report periodically

Extrernal (to X-Plane) application to detect OOOI ACARS message changes and generate appropriate message.

/data2/19//N/POSITION REPORT OVHD HABBS AT 1249Z/18700 PPOS:4512.2N/07425.3W AT 1249Z/18700 TO COMAU AT 1252Z NEXT MITIG WIND 325/23 SAT -20 ETA 1304Z SPEED 265 GND SPEED 354 VERT SPEED -2000FPM HDG 68 TRK 71
/data2/18//N/POSITION REPORT OVHD ARVIE AT 1247Z/FL221 PPOS:4507.0N/07437.2W AT 1247Z/FL221 TO HABBS AT 1249Z NEXT COMAU WIND 350/21 SAT -27 ETA 1304Z SPEED 260 GND SPEED 357 VERT SPEED -1900FPM HDG 69 TRK 73

"""

import logging
import os
from re import DEBUG
import sys
import threading
from datetime import datetime, timezone
from enum import StrEnum
from typing import Dict, Any, Tuple

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lat_lon_parser import to_deg_min
from unitutil import convert

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


version = "1.0.0"


class DREFS(StrEnum):
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


class PositionReport:

    def __init__(self, api, frequency: int, callsign: str, logon: str, station: str, eta: datetime | None = None) -> None:
        self.name = type(self).__name__
        self.ws = api

        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}
        self._report_thread = threading.Thread(target=self.report_loop, name="ACARS Progress Report")
        self._report_run = threading.Event()
        self.frequency = frequency

        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)

    def get_dataref_names(self) -> set:
        return DREFS

    def dataref_changed(self, dataref, value):
        self.datarefs[dataref].value = value

    def dataref_value(self, dataref: str):
        dref = self.datarefs.get(dataref)
        return dref.value if dref is not None else 0

    def run(self):
        self._report_thread.start()
        ws.connect()
        ws.wait_connection()
        ws.monitor_datarefs(datarefs=self.datarefs, reason=self.name)
        self._report_thread.start()
        ws.start()

    def terminate(self):
        self._report_run.set()
        ws.unmonitor_datarefs(datarefs=self.datarefs, reason=self.name)
        self.ws.disconnect()

    def report(self) -> str:
        def f(dref: str, rnd: int = 0) -> int | float:
            val = self.dataref_value(dataref=dref)
            if val is not None:
                return int(val) if rnd == 0 else round(val, rnd)
            return 0

        lat = self.dataref_value(DREFS.LATITUDE)
        ldeg, lmin = to_deg_min(lat)
        latstr = f"{ldeg:02d}{lmin:04.1f}{'N' if ldeg >=0 else 'S'}"
        lon = self.dataref_value(DREFS.LONGITUDE)
        ldeg, lmin = to_deg_min(lon)
        lonstr = f"{ldeg:03d}{lmin:04.1f}{'E' if ldeg >=0 else 'W'}"

        zulustr = now().strftime("%H%M")

        vs = self.dataref_value(DREFS.VS)
        vs = convert.ms_to_fpm(ms=vs)
        vs = round(vs/100) * 100
        alt = self.dataref_value(DREFS.ALT)
        if alt < 8000:
            altstr = f"{round(alt/10) * 10}"
        else:
            altstr = convert.meters_to_fl(convert.feet_to_meters(ft=alt))

        # find weather parameters for layer
        wind_dir = int(self.dataref_value(DREFS.WINDDIR))
        wind_speed = int(self.dataref_value(DREFS.WINDSPD))
        sat = int(self.dataref_value(DREFS.AIR_TEMP))

        return " ".join([
            "POSITION REPORT",
            f"PPOS:{latstr}/{lonstr} AT {zulustr}Z/{altstr}",
            f"WIND {wind_dir}/{wind_speed} SAT {saturation}",
            f"SPEED {f(DREFS.INDICATED_AIRSPEED)} GND SPEED {f(DREFS.GROUND_SPEED)} VERT SPEED {vs}FPM",
            f"HDG {f(DREFS.HDG)} TRK {f(DREFS.TRK)}",
            "PARTIAL AUTOGEN"
        ])

    def report_loop(self):
        loop = True
        while loop:
            try:
                logger.debug(self.report())
            except:
                logger.warning("error producing report")
            if self._report_run.wait(self.frequency):
                loop = False


if __name__ == "__main__":
    ws = xpwebapi.ws_api()
    pr = PositionReport(ws, frequency=5, callsign="BEL034", logon="none", station="EBJA")
    try:
        pr.run()
    except KeyboardInterrupt:
        logger.warning("terminating..")
        pr.terminate()
        logger.warning("..terminated")
