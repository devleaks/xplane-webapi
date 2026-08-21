"""Flight data recorder

XPPython3 Plug In to create a FDR file during a flight.

See Also
    https://www.x-plane.com/kb/creating-fdr-files/
    <X-Plane 12 Folder>/Instructions/FDR Example Version 3.fdr
    <X-Plane 12 Folder>/Instructions/FDR Example Version 4.fdr

Header fields permitted (in any order):
=======================

COMM: any comment

ACFT: the aircraft file to use, with full directory path from the X-Plane folder (ex: Aircraft/Heavy Metal/Boeing 747.acf).
TAIL: tail number of the aircraft (ex: N8141Q). Must come immediately after the ACFT line.
TIME: ZULU time of the beginning of the flight (ex: 18:54:32).
DATE: date of the flight (ex: 03/05/02).
PRES: sea-level pressure during the flight in inches HG (ex: 29.92).
TEMP: sea-level temperatre during the flight in degrees farenheit (ex: 65).
WIND: wind during th flight in degrees then knots (ex: 230,17).
CALI: the actual takeoff or touchdown logitude, latitude, and elevation in feet for calibration to X-Plane scenery. (ex: -118.34, 34.57, 456).

WARN: time to play a warning sound file, with full directory path from X-Plane itself to the .wav file (ex: 10,Resources/sounds/alert/1000ft.WAV).
TEXT: time & text to be read aloud by computer speech synthesis software (10,Copilot left the cockpit here).
MARK: time at which a text marker will appear in the time slider (ex: 15,Approach began here).
EVNT: highlights the flight path at the specified time, for a specified duration (ex: 10.5).
DATA: comma-delimited floating-point numbers that make up the bulk of the .fdr data (see explanation table below)

Keyworkd DATA is optional in FDR Version 4.

Example:
ACFT, Aircraft/Laminar Research/Lancair Evolution/N844X.acf
TAIL, N844X
DATE, 01/18/2023
PRES, 30.01
DISA, 0
WIND, 270,15

By convention, last comment before data contains the header column name (FDRData.name)
"""

import os
import inspect
import re
from datetime import date, datetime, timedelta, timezone
from traceback import print_stack
from typing import Tuple, Callable, Any
from dataclasses import dataclass

try:
    import xp
    from XPPython3.utils import xp_pip
    from XPPython3.utils.datarefs import find_dataref

except ImportError:
    print("X-Plane not loaded")

yaml = False
missing_modules = []
try:
    import ruamel
    from ruamel.yaml import YAML

    ruamel.yaml.representer.RoundTripRepresenter.ignore_aliases = lambda x, y: True
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
except ModuleNotFoundError:
    missing_modules.append("ruamel.yaml")



# Changelog


# To do, idea, suggestions
#
# Per aircraft "preference" file to monitor different sets of datarefs
# Either a fdr.prf in the acf folder or a preference file named after the acf, or a acf section in the pref file?

# Helper Data Class container
#
HIDDEN_CB_SRC = "_callback_src"
@dataclass
class FDRData:
    name: str  # tail number
    dataref: str  # sim/aircraft/view/acf_tailnum
    callback: Callable | None = None
    unit: str | None = None
    factor: float = 1.0
    dref = None

    def init(self) -> bool:
        try:
            self.dref = find_dataref(self.dataref)
            return self.dref is not None
        except:
            print(f"FDRData::init: {self.dataref} not found")
        return False

    def fun(self) -> str | None:
        # See http://xion.io/post/code/python-get-lambda-code.html
        s = repr(self)
        if self.callback is None:
            return s
        if hasattr(self, HIDDEN_CB_SRC): # callback installed through eval()
            sc = f"callback: {getattr(self, HIDDEN_CB_SRC)}"
            s1 = re.sub(r"callback=\<function \<lambda\> at 0[xX][0-9a-fA-F]+\>", sc, s)
            # print(f"FDRData::fun: re.sub: {s} => {s1}")
            return s1
        try:
            line = inspect.getsourcelines(self.callback)[0][0].strip()
            cmt = line.rindex("#")  # remove comments at end of line
            if cmt > 0:
                line = line[:cmt]  # remove comma after closing parent if any
            cmt = line.rindex(")")
            if cmt > 0:
                line = line[:cmt+1] # keep the )
            return line
        except:
            print_stack()
        return None

    @property
    def value(self) -> int | float | str | None:
        if self.dref is None:
            print("FDRData::value: no dref")
            return None
        v = self.dref.value
        if self.callback is not None:
            v = self.callback(v)
        return v


# Collected once for session, displayed in FDR report header
HEADER = [
    FDRData(name="ACFT", dataref="sim/aircraft/view/acf_relative_path"),
    FDRData(name="TAIL", dataref="sim/aircraft/view/acf_tailnum"),
    # FDRData(name="ICAO", dataref="sim/aircraft/view/acf_ICAO"),
    FDRData(name="DMON", dataref="sim/cockpit2/clock_timer/current_month"),
    FDRData(name="DDAY", dataref="sim/cockpit2/clock_timer/current_day"),
    FDRData(name="SEAL", dataref="sim/weather/region/sealevel_pressure_pas", callback=lambda x: x * 0.00029529980164712),  # 1 pascal = 0.00029529980164712 in hg
    FDRData(name="WSPD", dataref="sim/weather/aircraft/wind_now_speed_msc", callback=lambda x: x * 1.94384449),  # 1 m/s = 1,94384449 kt, FDR expects kt
    FDRData(name="WDIR", dataref="sim/weather/aircraft/wind_now_direction_degt"),
    FDRData(name="DISA", dataref="sim/weather/region/temperatures_aloft_deg_c[0]"),
    FDRData(name="ZDAY", dataref="sim/time/zulu_date_days"),  # used to get simulator time
    FDRData(name="ZSEC", dataref="sim/time/zulu_time_sec"),  # used to get simulator date (assume current year)
    FDRData(name="MOVE", dataref="sim/flightmodel2/position/groundspeed"),
]

# "Mandatory" FDR data at start of each CSV line
#
# They MUST BE the ZULU time, then the longitude, latitude, altitude in feet, magnetic heading in degrees, then pitch and roll in degrees.
# Note: Not sure where to fetch temperature offset from ISA.
FDR_DATA = [
    FDRData(name="longitude", dataref="sim/flightmodel/position/longitude"),
    FDRData(name="latitude", dataref="sim/flightmodel/position/latitude"),
    FDRData(name="altitude", dataref="sim/flightmodel/position/elevation", callback=lambda x: x * 3.28084, unit="ft"),  # m to ft, FDR expects ft
    FDRData(name="heading", dataref="sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot"),
    FDRData(name="pitch", dataref="sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot"),
    FDRData(name="roll", dataref="sim/cockpit2/gauges/indicators/roll_electric_deg_pilot"),
]


# Constants
#
PLUGIN_ROOT_PATH = os.path.dirname(os.path.abspath(__file__))  # .../PythonPlugins
SCRIPT_NAME = os.path.basename(__file__)

SHOW_TRACE = True
NAME = "FDR"
DESCRIPTION = "Flight Data Recordder"
VERSION = "3.0.0"

FDR_PREFERENCE_FILE = "fdr.yaml"

FDR_VERSION = 4
FDR_ARCH = "Apple"  # "IBM"

WRITE_FREQUENCY = 1.0  # seconds
REPORT_FREQUENCY = 100 # number of writes

FDR_MENU = "Start or stop FDR"
FDR_RESET_COMMAND = "xppython3/fdr/main_toggle"
FDR_RESET_COMMAND_DESC = "Start or stop a new FDR session"
FDR_PLUGIN_SIGNATURE = "com.xppython3.fdr"

AUTOSTART = True
AUTOSTART_FREQUENCY = 2.0  # secs
AUTOSTART_THRESHOLD = 2.0  # m/s
AUTOSTOP_THRESHOLD = 600.0  # seconds

class PythonInterface:

    def __init__(self) -> None:
        self.trace = SHOW_TRACE  # produces extra debugging in XPPython3.log for this class

        self.Name = NAME
        self.Sig = PLUGIN_ROOT_PATH.strip("/").replace("/", ".")
        self.Desc = DESCRIPTION + " (Rel. " + VERSION + ")"
        self.Info = self.Name + f" {VERSION}"

        self._enabled = False

        self.fdrCmdRef = None
        self.menuIdx = None

        self.flightLoop = None
        self.refFlightLoop = dict()

        self.autoStartLoop = None
        self.refAutoStartLoop = dict()

        self.file = None
        self.prefs = {}

        self.header = {d.name: d for d in HEADER}  # collected once
        self.fdr_data = FDR_DATA

        # can be changed in preferences
        self.fdr_optional = []
        self.frequency = max(self.prefs.get("frequency", WRITE_FREQUENCY), WRITE_FREQUENCY)
        self.report_frequency = max(self.prefs.get("report_frequency", REPORT_FREQUENCY), REPORT_FREQUENCY)
        self.version = self.prefs.get("fdr_version", FDR_VERSION)
        self.arch = self.prefs.get("fdr_arch", FDR_ARCH)
        if self.version not in [3, 4]:
            self.version = FDR_VERSION
        self.start_time = None
        self.last_stop = None
        self.writes = 0

    @property
    def fdr_all_data(self) -> dict:
        return self.fdr_data + self.fdr_optional

    def debug(self, message, force: bool = False):
        if self.trace or force:
            print(self.Info, message)

    def XPluginStart(self) -> tuple[str, str, str]:
        self.debug("FDR::XPluginStart: starting..")

        try:
            xp_pip.load_packages(missing_modules, "Loading missing modules", "Modules loaded.\nCheck for errors, and RESTART X-Plane.")
            self.debug(f"XPluginEnable: loaded packages {missing_modules}", force=True)
        except:
            self.debug(f"XPluginEnable: could not load packages {missing_modules}", force=True)

        for d in self.header.values():
            d.init()

        for d in self.fdr_data:
            d.init()

        # Install plugin in X-Plane
        self.fdrCmdRef = xp.createCommand(FDR_RESET_COMMAND, FDR_RESET_COMMAND_DESC)
        xp.registerCommandHandler(self.fdrCmdRef, self.fdrCmd, 1, None)
        if self.fdrCmdRef is not None:
            self.debug("FDR::XPluginStart: command registered")
        else:
            self.debug("FDR::XPluginStop: command not registered")

        self.menuIdx = xp.appendMenuItemWithCommand(xp.findPluginsMenu(), FDR_MENU, self.fdrCmdRef)
        if self.menuIdx is None or (self.menuIdx is not None and self.menuIdx < 0):
            self.info("FDR::XPluginStart: menu not added")
        else:
            xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 1)
            self.debug("FDR::XPluginStart: menu added")

        self.debug("FDR::XPluginStart: ..started")
        return self.Name, self.Sig, self.Desc

    def XPluginStop(self):
        self.debug("FDR::XPluginStop: stopping..")

        if self.fdrCmdRef:
            xp.unregisterCommandHandler(self.fdrCmdRef,
                                        self.fdrCmd,
                                        1, None)
            self.fdrCmdRef = None
            self.debug("FDR::XPluginStop: command unregistered")
        else:
            self.debug("FDR::XPluginStop: command not unregistered")

        if self.menuIdx is not None and self.menuIdx >= 0:
            oldidx = self.menuIdx
            xp.removeMenuItem(xp.findPluginsMenu(), self.menuIdx)
            self.menuIdx = None
            self.debug("FDR::XPluginStop: menu removed")
        else:
            self.debug("FDR::XPluginStop: menu not removed")

        self.debug("FDR::XPluginStop: ..stopped")
        pass

    def XPluginEnable(self) -> int:
        self.debug("FDR::XPluginEnable: enabling..")
        self.loadPreferences()
        self.debug("FDR::XPluginEnable: ..enabled")
        self._enabled = True
        return 1

    def XPluginDisable(self):
        self.debug("FDR::XPluginDisable: disabled")
        self._enabled = False

    def XPluginReceiveMessage(self, inFromWho: int, inMessage: int, inParam: int | str):
        pass

    def fdrCmd(self, commandRef, phase: int, refCon: Any):
        if not self._enabled:
            self.debug("FDR::fdrCmd: not enabled", force=True)
            return 1

        if phase != 0:
            return 1

        if self.file is None:  # toggle ON
            outfile = os.path.join(xp.getSystemPath(), "Output", "fdr")
            if not os.path.isdir(outfile):
                os.makedirs(outfile)
            outfile = os.path.join(outfile, f"fdr{self.simulator_zulu_datetime.strftime("%Y%m%d%H%M%S")}.fdr")
            self.file = open(outfile, "w")
            self.start()
            self.debug(f"FDR::fdrCmd: FDR started, saving FDR{self.version} into {outfile}", force=True)
            xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 2)
        else:  # toggle OFF
            self.stop()
            self.file.close()
            self.file = None
            self.debug("FDR::fdrCmd: FDR stopped", force=True)
            xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 1)
        return 1

    @property
    def simulator_zulu_datetime(self) -> datetime:
        now = datetime.now(tz=timezone.utc)
        days = self.header.get("ZDAY").value
        secs = self.header.get("ZSEC").value
        return datetime(year=now.year,
                        month=1,
                        day=1,
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                        tzinfo=timezone.utc) + timedelta(days=days) + timedelta(seconds=secs) if days is not None and secs is not None else now

    def loadPreferences(self) -> bool:
        acffile = os.path.join(xp.getSystemPath(), self.header.get("ACFT").value)
        acffile = os.path.join(os.path.dirname(acffile), FDR_PREFERENCE_FILE)
        acfpref = False
        if os.path.exists(acffile):  # try aircraft-specific pref
            self.debug(f"FDR::loadPreferences: aircraft preference file found at {acffile}", force=True)
            try:
                with open(acffile, "r") as fp:
                    self.prefs = yaml.load(fp)
                self.debug(f"FDR::loadPreferences: {acffile} loaded")
                acfpref = True
            except Exception as e:
                print("error", e)

        if not acfpref:  # try generic pref
            preffile = os.path.join(xp.getSystemPath(), "Output", "preferences", FDR_PREFERENCE_FILE)
            if os.path.exists(preffile):
                try:
                    with open(preffile, "r") as fp:
                        self.prefs = yaml.load(fp)
                    self.debug(f"FDR::loadPreferences: {preffile} loaded")
                except Exception as e:
                    print("error", e)
                    self.prefs = {}
                    return False
            else:
                self.debug(f"FDR::loadPreferences: no preference file {preffile}")
                return True

        self.frequency = abs(max(self.prefs.get("frequency", WRITE_FREQUENCY), WRITE_FREQUENCY))  # no per frame request
        self.report_frequency = max(self.prefs.get("report_frequency", REPORT_FREQUENCY), REPORT_FREQUENCY)  # set to 0 to ignore
        self.version = self.prefs.get("fdr_version", FDR_VERSION)
        if self.version not in [3, 4]:
            self.version = FDR_VERSION
        self.arch = self.prefs.get("fdr_arch", FDR_ARCH)
        if self.arch not in [FDR_ARCH, "IBM"]:
            self.arch = FDR_ARCH

        # Add optional datarefs
        opts = self.prefs.get("fdr_optional", {})
        if len(opts) > 0:
            self.fdr_optional = []
            for d in opts:
                callback = d.get("callback")
                if callback is not None:
                    del d["callback"]
                f = FDRData(**d)
                if callback is not None:
                    self.debug(f"eval callback {callback}", force=True)
                    setattr(f, HIDDEN_CB_SRC, callback)
                    f.callback = eval(callback, {})
                f.init()
                self.fdr_optional.append(f)
            self.debug(f"FDR::loadPreferences: added {len(self.fdr_optional)} datarefs to monitor", force=True)

        self.debug("FDR::loadPreferences: loaded", force=True)

        if AUTOSTART:
            self.autoStart()

        return True

    def csv_header_line(self):
        print(f"{FDR_ARCH[0]}\r{self.version}\n", file=self.file)  # note A may not be visible on Apple computers because of simple carriage return after it (no new line)

        # Script info, use local time
        print(f"COMM, {SCRIPT_NAME} rel. {VERSION} on {datetime.now().replace(microsecond=0).astimezone().isoformat()}\n", file=self.file)

        # FDR Meta data
        print(f"ACFT, {self.header.get('ACFT').value}", file=self.file)
        print(f"TAIL, {self.header.get('TAIL').value}", file=self.file)
        print(f"DATE, {self.simulator_zulu_datetime.strftime("%m/%d/%Y")}", file=self.file)  # MM/DD/YYYY
        print(f"PRES, {round(self.header.get('SEAL').value, 2)}", file=self.file)
        print(f"DISA, {round(self.header.get('DISA').value[0], 2)}", file=self.file)
        print(f"WIND, {int(self.header.get('WDIR').value)}," +
                   f" {round(self.header.get('WSPD').value, 2)}", file=self.file)
        # print(f"COMM, Aircraft ICAO Model {self.header.get('ICAO').value}", file=self.file)

        # FDR Datarefs
        if len(self.fdr_optional) > 0:
            print("\n", file=self.file)
            for d in self.fdr_optional:
                if d.dref is None:
                    self.debug(f"dataref {d} not found, not monitored", force=True)
                    print(f"COMM, dataref {d} not found, not monitored", file=self.file)
                    continue
                f = d.factor
                if d.callback is not None:
                    f = d.callback(f)  # ok if we assume simple multiplication factor
                print(f"DREF, {d.dataref}  {d.factor}", file=self.file)

        # FDRReader meta
        print("\n", file=self.file)
        for d in self.fdr_all_data:
            print(f"COMM, {d.fun()}", file=self.file)

        # CSV Header
        columns = ", ".join([d.name for d in self.fdr_all_data if "zulu" not in d.dataref])
        print("\nCOMM, UTC time, " + columns + "\n", file=self.file)
        self.debug("FDR header written")

    def csv_data_line(self) -> str:
        data = ""
        if self.version == 3:
            data = f"DATA, {round((self.simulator_zulu_datetime - self.start_time).total_seconds(), 1)}"
        elif self.version == 4:
            data = self.simulator_zulu_datetime.strftime("%H:%M:%S.%f, ")
        data = data + ",".join([f"{v}" for v in [d.value for d in self.fdr_all_data if "zulu" not in d.dataref]])
        return data + "\n"

    def loop(self, elapsedSinceLastCall, elapsedTimeSinceLastFlightLoop, counter, inRefcon):
        if self.file is not None:
            self.file.write(self.csv_data_line())
            self.writes = self.writes + 1
            self.file.flush()
            if self.report_frequency > 0 and self.writes % self.report_frequency == 0:
                self.debug(f"FDR::loop: {self.writes} events since {self.start_time.isoformat()}", force=True)
        else:
            self.debug("FDR::loop: no file", force=True)
        return self.frequency

    def start(self):
        if self.file is not None:
            self.start_time = self.simulator_zulu_datetime
            self.last_stop = None
            self.writes = 0
            self.csv_header_line()
            if self.flightLoop is None:
                self.flightLoop = xp.createFlightLoop(callback=self.loop, phase=xp.FlightLoop_Phase_AfterFlightModel, refCon=self.refFlightLoop)
                xp.scheduleFlightLoop(self.flightLoop, self.frequency, 1)
                self.debug(f"FDR::start: started at {self.start_time.isoformat()}")
        else:
            self.debug("FDR::start: no file, not started")

    def stop(self):
        if self.flightLoop is not None:
            xp.destroyFlightLoop(self.flightLoop)
            self.flightLoop = None
        self.debug("FDR::stop: stopped")

    def autoStartLoop(self, elapsedSinceLastCall, elapsedTimeSinceLastFlightLoop, counter, inRefcon):
        if self.header.get("MOVE").value > AUTOSTART_THRESHOLD:
            self.debug("FDR::autoStartLoop: move detected, starting FDR..")
            if self.file is None:  # toggle ON
                outfile = os.path.join(xp.getSystemPath(), "Output", "fdr")
                if not os.path.isdir(outfile):
                    os.makedirs(outfile)
                outfile = os.path.join(outfile, f"fdr{self.simulator_zulu_datetime.strftime("%Y%m%d%H%M%S")}.fdr")
                self.file = open(outfile, "w")
                self.start()
                self.debug(f"FDR::autoStartLoop: ..started, saving FDR{self.version} into {outfile}", force=True)
                xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 2)
            else:
                self.debug("FDR::autoStartLoop: file aready open?", force=True)
        else:  # stop after a 10 minute continuous stop time out?
            if self.last_stop is None:
                self.last_stop = datetime.now().astimezone()
            tdiff = self.last_stop - datetime.now().astimezone()
            if tdiff.total_seconds() > AUTOSTOP_THRESHOLD:
                self.debug(f"FDR::autoStartLoop: stoppe for {round(tdiff.total_seconds(), 0)} seconds, stopping FDR..")
                if self.file is not None:
                    self.stop()
                    self.file.close()
                    self.file = None
                    self.debug("FDR::autoStartLoop: ..FDR stopped", force=True)
                    xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 1)
                else:
                    self.debug("FDR::autoStartLoop: file aready closed?", force=True)
        return AUTOSTART_FREQUENCY

    def autoStart(self):
        if self.autoStartLoop is None:
            self.autoStartLoop = xp.createFlightLoop(callback=self.autoStartLoop, phase=xp.FlightLoop_Phase_AfterFlightModel, refCon=self.refAutoStartLoop)
            xp.scheduleFlightLoop(self.autoStartLoop, AUTOSTART_FREQUENCY, 1)
            self.debug("FDR::autoStart: started")

    def stopAutoStart(self):
        if self.autoStartLoop is not None:
            xp.destroyFlightLoop(self.autoStartLoop)
            self.autoStartLoop = None
        self.debug("FDR::stopAutoStart: stopped")



