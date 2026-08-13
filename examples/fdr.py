"""Flight data recorder

Extrernal (to X-Plane) application to create a FDR file during a flight.

File first collect FDR header information such as aircraft type and registration, date, and basic weather information.
It then permanently collects FDR data, a set of mandatory data (ZULU time, longitude, latitude, altitude, magnetic heading, pitch and roll),
and a set of optional dataref.

Dataref values get saved every WRITE_FREQUENCY and written FLUSH_FREQUENCY second.

Currently use Websocket API. TO do: Use alternate protocols: REST, UDP. Should work out of the box.

See Also

    https://www.x-plane.com/kb/creating-fdr-files/

"""

import os
import sys
import logging
import argparse
import datetime
import inspect
from dataclasses import dataclass
from typing import Callable, Dict
from time import sleep

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi
from xpwsapp import XPWSAPIApp

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)



@dataclass
class FDRData:
    name: str
    dataref: str  # sim/aircraft/view/acf_tailnum
    dtype: str = "int"  # int, float, vint, vfloat, data
    value: int | float | list = 0
    unit: str = ""
    callback: Callable | None = None # if not None, store value = callback(dataref value), to change units for example
    dref = None # API entitry

    def fun(self) -> str | None:
        # See http://xion.io/post/code/python-get-lambda-code.html
        if self.callback is None:
            return None
        line = inspect.getsourcelines(self.callback)[0][0].strip()
        cmt = line.rindex("#")
        if cmt > 0:
            # print(f"removed comment {line[cmt:]}")
            line = line[:cmt]
        cmt = line.rindex(")")
        if cmt > 0:
            # print(f"removed eol {line[cmt+1:]}")
            line = line[:cmt+1] # keep the )
        # print(f"func {line}")
        return line


# Header fields permitted (in any order):
#
# COMM: any comment
#
# ACFT: the aircraft file to use, with full directory path from the X-Plane folder (ex: Aircraft/Heavy Metal/Boeing 747.acf).
# TAIL: tail number of the aircraft (ex: N8141Q). Must come immediately after the ACFT line.
# TIME: ZULU time of the beginning of the flight (ex: 18:54:32).
# DATE: date of the flight (ex: 03/05/02).
# PRES: sea-level pressure during the flight in inches HG (ex: 29.92).
# TEMP: sea-level temperatre during the flight in degrees farenheit (ex: 65).
# WIND: wind during th flight in degrees then knots (ex: 230,17).
# CALI: the actual takeoff or touchdown logitude, latitude, and elevation in feet for calibration to X-Plane scenery. (ex: -118.34, 34.57, 456).
#
# WARN: time to play a warning sound file, with full directory path from X-Plane itself to the .wav file (ex: 10,Resources/sounds/alert/1000ft.WAV).
# TEXT: time & text to be read aloud by computer speech synthesis software (10,Copilot left the cockpit here).
# MARK: time at which a text marker will appear in the time slider (ex: 15,Approach began here).
# EVNT: highlights the flight path at the specified time, for a specified duration (ex: 10.5).
# DATA: comma-delimited floating-point numbers that make up the bulk of the .fdr data (see explanation table below)
#
# Keyworkd data is optional in FR Version 4.
#
# Example:
# ACFT, Aircraft/Laminar Research/Lancair Evolution/N844X.acf
# TAIL, N844X
# DATE, 01/18/2023
# PRES, 30.01
# DISA, 0
# WIND, 270,15
#
# By convention, last comment before data contains the header column name (FDRData.name)


# Units
# °DEC: Decimal degree
# °T Decimal degree relative to True North
# °M Decimal degree relative to Magnetic North

HEADER = [
    FDRData(name="ACFT", dataref="sim/aircraft/view/acf_relative_path", dtype="data"),
    FDRData(name="TAIL", dataref="sim/aircraft/view/acf_tailnum", dtype="data"),
    FDRData(name="DMON", dataref="sim/cockpit2/clock_timer/current_month", dtype="int"),
    FDRData(name="DDAY", dataref="sim/cockpit2/clock_timer/current_day", dtype="int"),
    FDRData(name="PRES", dataref="sim/weather/barometer_current_inhg", dtype="float"),
    FDRData(name="SEAL", dataref="sim/weather/barometer_sealevel_inhg", dtype="float"),
    FDRData(name="WDIR", dataref="sim/weather/aircraft/wind_now_direction_degt", dtype="float"),
    FDRData(name="WSPD", dataref="sim/weather/aircraft/wind_now_speed_msc", dtype="float"),  # 1 m/s = 1,94384449 knt
]

# "Mandatory" FDR data at start of each CSV line
#
# They MUST BE the ZULU time, then the longitude, latitude, altitude in feet, magnetic heading in degrees, then pitch and roll in degrees.
# Note: Not sure where to fetch temperature offset from ISA.
FDR_DATA = [
    FDRData(name="ZHRS", dataref="sim/cockpit2/clock_timer/zulu_time_hours", dtype="int"),
    FDRData(name="ZMIN", dataref="sim/cockpit2/clock_timer/zulu_time_minutes", dtype="int"),
    FDRData(name="ZSEC", dataref="sim/cockpit2/clock_timer/zulu_time_seconds", dtype="float"),
    FDRData(name="longitude", dataref="sim/flightmodel/position/longitude", dtype="float", unit="°DEC"),
    FDRData(name="latitude", dataref="sim/flightmodel/position/latitude", dtype="float", unit="°DEC"),
    FDRData(name="altitude", dataref="sim/flightmodel/position/elevation", dtype="float", callback=lambda x: x * 3.28084, unit="ft"),  # callback converts m to ft for FDR
    FDRData(name="heading", dataref="sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot", dtype="float", unit="°DEC"),
    FDRData(name="pitch", dataref="sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot", dtype="float", unit="°"),
    FDRData(name="roll", dataref="sim/cockpit2/gauges/indicators/roll_electric_deg_pilot", dtype="float", unit="°"),
]

# Additional datarefs that user wants to be saved
#
FDR_OPTIONAL = set()

try:
    from fdr_optional import FDR_OPTIONAL
    if len(FDR_OPTIONAL) > 0:
        logger.info(f"imported {len(FDR_OPTIONAL)} optional datarefs")
except ImportError:
    pass

# Default values
#
SCRIPT_NAME = os.path.basename(__file__)
SCRIPT_VERSION = "2.0.0"

FDR_FILENAME = "out.fdr"
FDR_VERSION = 3
WRITE_FREQUENCY = 1.0  # seconds
REPORT_FREQUENCY = 20.0  # seconds, 0 to disable
TOO_LONG = 10.0

class FDR(XPWSAPIApp):

    def __init__(self, api, filename: str = FDR_FILENAME, frequency: float = WRITE_FREQUENCY) -> None:
        XPWSAPIApp.__init__(self, api=api)

        self.filename = filename
        self.frequency = frequency
        self.header = {d.dataref: False for d in HEADER}
        self.lines = []
        self.others = []
        self.file = None
        self.writes = 0
        self.fdr_data = {d.dataref: d for d in FDR_DATA + FDR_OPTIONAL}
        self.optional_datarefs: Dict[str, xpwebapi.Dataref] = {}

    @property
    def header_ok(self) -> bool:
        return all(self.header.values())

    def get_dataref_names(self) -> set:
        return set([d.dataref for d in HEADER] + [d.dataref for d in FDR_DATA] + [d.dataref for d in FDR_OPTIONAL])

    def dataref_value(self, dataref: str, is_string: bool = False, rounding: int | None = None):
        dref = self.datarefs.get(dataref)
        if dref is None:
            logger.warning(f"dataref {dataref} not found")
            return "" if is_string else 0
        if is_string:
            value = dref.get_string_value(encoding="ascii")
            return value
        # check is local convertion function to suit FDR expected unit
        dref_meta = self.fdr_data.get(dataref)
        value = dref.value
        if dref_meta is not None and dref_meta.callback is not None:
            v = value
            value = dref_meta.callback(v)
        if rounding is not None:
            return round(value, rounding)
        return value

    def print_header(self):
        with open(self.filename, "w") as fp:
            # FDR Header
            print(f"A\r{FDR_VERSION}\n", file=fp)  # note A may not be visible on Apple computers because of simple carriage return after it (no new line)

            print(f"COMM, {SCRIPT_NAME} rel. {SCRIPT_VERSION}, xpwebapi rel. {xpwebapi.version}", file=fp)
            print(f"COMM, on {datetime.datetime.now().replace(microsecond=0).astimezone().isoformat()}\n", file=fp)

            # FDR Meta data
            print(f"ACFT, {self.dataref_value('sim/aircraft/view/acf_relative_path', is_string=True)}", file=fp)
            print(f"TAIL, {self.dataref_value('sim/aircraft/view/acf_tailnum', is_string=True)}", file=fp)
            print(
                f"DATE, {self.dataref_value('sim/cockpit2/clock_timer/current_month')}/{self.dataref_value('sim/cockpit2/clock_timer/current_day')}/{datetime.datetime.now().year}",
                file=fp,
            )  # MM/DD/YYYY
            print(f"PRES, {self.dataref_value('sim/weather/barometer_sealevel_inhg', rounding=2)}", file=fp)
            print("DISA, 0", file=fp)
            print(
                f"WIND, {int(self.dataref_value('sim/weather/aircraft/wind_now_direction_degt'))}, {round(self.dataref_value('sim/weather/aircraft/wind_now_speed_msc') * 1.94384449, 2)}",
                file=fp,
            )

            # Pass information to FDRReader
            print("\nCOMM, FDRData", file=fp)
            for d in self.fdr_data.values():
                if "zulu" in d.dataref:
                    continue
                if d.callback is not None:
                    print(f"COMM, {d.fun()}", file=fp)
                else:
                    print(f"COMM, {repr(d)}", file=fp)

            # FDR Data
            if len(FDR_OPTIONAL) > 0:
                print("\nCOMM, Additional datarefs", file=fp)
                for d in [d.dataref for d in FDR_OPTIONAL]:
                    comment = ""
                    dref = self.datarefs.get(d)
                    if dref is None:
                        logger.warning(f"dataref {d} not found, not monitored")
                        print(f"COMM, WARNING: dataref {d} not found, not monitored", file=fp)
                        continue
                    elif not dref.valid:
                        print(f"COMM, WARNING: dataref {d} not valid, not monitored", file=fp)
                        logger.warning(f"dataref {d} is not valid, not monitored")
                        continue
                    elif not dref.is_writable:
                        # logger.warning(f"dataref {d} is not writable, will be monitored")
                        comment = "not writable"
                    print(f"DREF, {d}  1.0 // comment: {comment}", file=fp)
                    self.optional_datarefs[d] = dref

            # Column units as a comment
            mandatory = ", ".join([d.unit for d in FDR_DATA if "zulu" not in d.dataref])
            optional = "" if len(self.optional_datarefs) == 0 else ", " + ", ".join([d.unit for d in FDR_OPTIONAL])
            print("\nCOMM, H:%M:%S.%f, " + mandatory + optional, file=fp)

            # CSV Header as a comment
            mandatory = ", ".join([d.name for d in FDR_DATA if "zulu" not in d.dataref])
            optional = "" if len(self.optional_datarefs) == 0 else ", " + ", ".join([d.name for d in FDR_OPTIONAL])
            print("COMM, UTC time, " + mandatory + optional + "\n", file=fp)

            mandatory = ", ".join([f"{d.name}({d.unit})" for d in FDR_DATA if "zulu" not in d.dataref])
            optional = "" if len(self.optional_datarefs) == 0 else ", " + ", ".join([f"{d.name}({d.unit})" for d in FDR_OPTIONAL])
            logger.info("Header completed: UTC time, " + mandatory + optional)

        logger.debug("FDR header written")

    def print_line(self) -> str:
        base = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S.%f, ")
        if FDR_VERSION == 3:
            base = "DATA," + base
        values = [self.dataref_value(d.dataref) for d in FDR_DATA if "zulu" not in d.dataref]
        base = base + ",".join([f"{v}" for v in values])
        optional = "" if len(self.optional_datarefs) == 0 else "," + ",".join([f"{self.dataref_value(d)}" for d in self.optional_datarefs.keys()])
        return base + optional + "\n"

    def loop(self):
        r = 100000
        if REPORT_FREQUENCY > 0:
            r = int(self.frequency if self.frequency > REPORT_FREQUENCY else REPORT_FREQUENCY / self.frequency)
        logger.info("FDR writer started")
        while not self.file.closed:
            self.file.write(self.print_line())
            self.writes = self.writes + 1
            self.file.flush()
            if self.writes % r == 0:
                logger.info(f"..FDR written {self.writes} event..")
            sleep(self.frequency)
        logger.info("FDR writer stopped")

    def dataref_changed(self, dataref, value):
        super().dataref_changed(dataref=dataref, value=value)

        if not self.header_ok:
            if dataref in [d.dataref for d in HEADER]:
                logger.debug(f"got mandarory {dataref}")
                self.header[dataref] = True
                if self.header_ok:
                    self.start()
                return

            # buffering lines every second while header not written
            if dataref == "sim/cockpit2/clock_timer/zulu_time_seconds":
                self.lines.append(self.print_line())
                if len(self.lines) % 1000 == 0:
                    logger.warning("failed to collect header")
                    logger.debug(self.header)

    def start(self):
        self.start_time = datetime.datetime.now()
        how_long = - (datetime.datetime.now() - self.start_time).total_seconds()
        print("how long", how_long)
        if not self.header_ok and how_long > TOO_LONG:
            logger.warning("{round(how_long, 1)} since start and no full header {self.header}")
        if not self.header_ok:
            return
        # writing header
        self.print_header()
        # writing buffered lines
        self.file = open(self.filename, "a")
        for l in self.lines:
            self.writes = self.writes + 1
            self.file.write(l)
        logger.debug(f"FDR {len(self.lines)} buffered line{'s' if len(self.lines) > 1 else ''} written")
        self.lines = []
        super().start()

    def stop(self):
        if self.file is not None:
            self.file.close()
            self.file = None


# ######################################################
#
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
    app = FDR(api, frequency=1.0)
    try:
        app.run()
    except KeyboardInterrupt:
        logger.warning("terminating..")
        app.terminate()
        logger.warning("..terminated")
