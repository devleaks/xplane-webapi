"""Flight data recorder

Extrernal (to X-Plane) application to create a FDR file during a flight.

File first collect FDR header information such as aircraft type and registration, date, and basic weather information.
It then permanently collects FDR data, a set of mandatory data (ZULU time, longitude, latitude, altitude, magnetic heading, pitch and roll),
and a set of optional dataref.

Dataref values get saved every WRITE_FREQUENCY and written FLUSH_FREQUENCY second.

"""

import os
import sys
import logging
import threading
import datetime
from typing import Dict
from time import sleep

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


# From sample FDR 4 data file:
#
# ACFT: aicraft path in X-Plane
# TAIL: tail number
# DATE: local time in xx/xx/xx format
# PRES: local baro pressure in inches
# DISA: temperature offset from ISA in degrees C
# WIND: wind direction and speed in knots
#
# Example:
# ACFT, Aircraft/Laminar Research/Lancair Evolution/N844X.acf
# TAIL, N844X
# DATE, 01/18/2023
# PRES, 30.01
# DISA, 0
# WIND, 270,15
#
HEADER = {
    "sim/aircraft/view/acf_relative_path",
    "sim/aircraft/view/acf_tailnum",
    "sim/cockpit2/clock_timer/current_month",
    "sim/cockpit2/clock_timer/current_day",
    "sim/weather/barometer_current_inhg",
    "sim/weather/barometer_sealevel_inhg",
    "sim/weather/aircraft/wind_now_direction_degt",
    "sim/weather/aircraft/wind_now_speed_msc",  # 1 m/s = 1,94384449 knt
}

# "Mandatory" FDR data at start of each CSV line
#
# They MUST BE the ZULU time, then the longitude, latitude, altitude in feet, magnetic heading in degrees, then pitch and roll in degrees.
# Note: Not sure where to fetch temperature offset from ISA.
FDR_DATA = {
    "sim/cockpit2/clock_timer/zulu_time_hours",
    "sim/cockpit2/clock_timer/zulu_time_minutes",
    "sim/cockpit2/clock_timer/zulu_time_seconds",
    "sim/flightmodel/position/longitude",
    "sim/flightmodel/position/latitude",
    "sim/cockpit/pressure/cabin_altitude_actual_ft",
    "sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot",
    "sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot",
    "sim/cockpit2/gauges/indicators/roll_electric_deg_pilot",
}

# Additional datarefs that user wants to be saved
#
FDR_OPTIONAL = set()

try:
    from fdr_optional import FDR_OPTIONAL

    logger.info(f"imported {len(FDR_OPTIONAL)} optional datarefs")
except ImportError:
    pass

# Default values
#
FILENAME = "out.fdr"
WRITE_FREQUENCY = 1.0  # seconds
REPORT_FREQUENCY = 20.0 # secs


class FDR:

    def __init__(self, api, filename: str = FILENAME, frequency: float = WRITE_FREQUENCY) -> None:
        self.ws = api
        self.filename = filename
        self.frequency = frequency
        self.header_ok = False
        self.header = {}
        self.lines = []
        self.file = None
        self.writes = 0
        self.write_thread = threading.Thread(target=self.write, name="FDR Data Writer")
        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}
        self.optional_datarefs: Dict[str, xpwebapi.Dataref] = {}
        self.init()

    def init(self):
        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)

    def start(self):
        ws.connect()
        ws.wait_connection()
        ws.monitor_datarefs(datarefs=self.datarefs, reason="Flight data recorder")
        ws.start()

    def get_dataref_names(self) -> set:
        return HEADER | FDR_DATA | FDR_OPTIONAL

    def dataref_value(self, dataref: str, is_string: bool = False, rounding: int | None = None):
        dref = self.datarefs.get(dataref)
        if dref is None:
            logger.warning(f"dataref {dataref} not found")
            return "" if is_string else 0
        if is_string:
            value = dref.get_string_value(encoding="ascii")
            return value
        if rounding is not None:
            return round(dref.value, rounding)
        return dref.value

    def print_header(self):
        with open(self.filename, "w") as fp:
            # FDR Header
            print("A\r4\n", file=fp)  # note A may not be visible on Apple computers because of simple carriage return after it (no new line)

            # FDR Meta data
            print(f"ACFT, {self.dataref_value('sim/aircraft/view/acf_relative_path', is_string=True)}", file=fp)
            print(f"TAIL, {self.dataref_value('sim/aircraft/view/acf_tailnum', is_string=True)}", file=fp)
            print(
                f"DATE, {self.dataref_value('sim/cockpit2/clock_timer/current_month')}/{self.dataref_value('sim/cockpit2/clock_timer/current_day')}/2025",
                file=fp,
            )  # MM/DD/YYYY
            print(f"PRES, {self.dataref_value('sim/weather/barometer_sealevel_inhg', rounding=2)}", file=fp)
            print("DISA, 0", file=fp)
            print(
                f"WIND, {int(self.dataref_value('sim/weather/aircraft/wind_now_direction_degt'))}, {round(self.dataref_value('sim/weather/aircraft/wind_now_speed_msc') * 1.94384449, 2)}",
                file=fp,
            )

            # FDR Data
            if len(FDR_OPTIONAL) > 0:
                print("\nCOMM, Additional datarefs", file=fp)
                for d in FDR_OPTIONAL:
                    comment = ""
                    dref = self.datarefs.get(d)
                    if dref is None:
                        logger.warning(f"dataref {d} not found, not monitored")
                        continue
                    elif not dref.valid:
                        logger.warning(f"warning: dataref {d} is not valid, not monitored")
                        continue
                    elif not dref.is_writable:
                        logger.warning(f"warning: dataref {d} is not writable, monitored")
                        comment = "not writable"
                    print(f"DREF, {d}  1.0 // comment: {comment}", file=fp)
                    self.optional_datarefs[d] = dref

            # CSV Header as a comment
            optional = "" if len(self.optional_datarefs) == 0 else ", " + ", ".join(self.optional_datarefs.keys())
            print("\nCOMM, UTC time, longitude, latitude, altmsl(ft), heading, pitch, roll" + optional + "\n", file=fp)

        logger.debug("FDR header written")

    def print_line(self) -> str:
        base = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S.%f")
        base = base + ", ".join([f"{self.dataref_value(d)}" for d in FDR_DATA if "zulu" not in d])
        optional = "" if len(self.optional_datarefs) == 0 else ", " + ", ".join([f"{self.dataref_value(d)}" for d in self.optional_datarefs.keys()])
        return base + optional + "\n"

    def write(self):
        r = int(self.frequency if self.frequency > REPORT_FREQUENCY else REPORT_FREQUENCY / self.frequency)
        while not self.file.closed:
            self.file.write(self.print_line())
            self.writes = self.writes + 1
            self.file.flush()
            if self.writes % r == 0:
                logger.info(f"..FDR written.. ({self.writes})")
            sleep(self.frequency)

    def dataref_changed(self, dataref, value):
        def has_value(d) -> bool:
            if d.startswith("sim/aircraft/view/"):
                return self.dataref_value(d, is_string=True) is not None
            return self.dataref_value(d) not in [None, "", 0]

        self.datarefs[dataref].value = value
        if not self.header_ok:
            if dataref in HEADER:
                self.header[dataref] = value
                self.header_ok = len([d for d in self.header if has_value(d)]) == len(HEADER)
                if self.header_ok:
                    # writing header
                    self.print_header()
                    # writing buffered lines
                    self.file = open(self.filename, "a")
                    for l in self.lines:
                        self.writes = self.writes + 1
                        self.file.write(l)
                    logger.debug(f"FDR {len(self.lines)} buffered lines written")
                    self.lines = []
                    self.write_thread.start()
                    logger.info(f"FDR writer started")
                return

            # buffering lines while header not written
            if dataref == "sim/cockpit2/clock_timer/zulu_time_seconds":
                self.lines.append(self.print_line())

    def terminate(self):
        if self.file is not None:
            self.file.close()
            self.file = None
        ws.register_bulk_dataref_value_event(datarefs=self.datarefs, on=False)
        self.ws.disconnect()


if __name__ == "__main__":
    ws = xpwebapi.ws_api(host="192.168.1.141", port=8080)
    fdr = FDR(ws)
    try:
        fdr.start()
    except KeyboardInterrupt:
        logger.warning("terminating..", exc_info=True)
        fdr.terminate()
