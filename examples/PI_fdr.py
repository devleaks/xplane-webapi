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
import math
import tomllib
from datetime import date, datetime, timedelta, timezone
from traceback import print_stack
from typing import Tuple, Callable, Any, Set
from dataclasses import dataclass
from enum import IntEnum

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

# Helper Data Class container
#
HIDDEN_CB_SRC = "_callback_src"
CB_LEN = 64

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
        except Exception as e:
            print(f"{NAME} {VERSION}::FDRData.init: {self.dataref} init failed: {e}")
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
        except Exception as e:
            print(f"{NAME} {VERSION}::FDRData.fun: {self.name} {self.dataref} exception: {e}")
        return None

    @property
    def data_type(self) -> str | Set | None:
        # @todo
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.data_type: {self.dataref} no dref")
            return None
        v = set()
        if self.dref.types & xp.Type_FloatArray:
            v.add("array_float")
        if self.dref.types & xp.Type_IntArray:
            v.add("array_int")
        if self.dref.types & xp.Type_Double:
            v.add("float")
        if self.dref.types & xp.Type_Float:
            v.add("float")
        if self.dref.types & xp.Type_Int:
            v.add("int")
        if self.dref.types & xp.Type_Data:
            v.add("data")
        if self.dref.types & xp.Type_Unknown:
            v.add("unknown")
        if len(v) > 1:
            print(f"{NAME} {VERSION}::FDRData.data_type: {self.dataref} has more than one type {v}")
        return v[0] if len(v) == 1 else v

    @property
    def value(self) -> int | float | str | None:
        if self.dref is None:
            print(f"{NAME} {VERSION}::FDRData.value: {self.name} {self.dataref} no dref")
            try:  # try to re-init it
                self.init()
            except Exception as e:
                print(f"{NAME} {VERSION}::FDRData.value: init {self.name} {self.dataref} exception: {e}")
            return None
        v = None
        try:
            v = self.dref.value
            if self.callback is not None:
                v = self.callback(v)
        except Exception as e:
            print(f"{NAME} {VERSION}::FDRData.value: callback {self.name} {self.dataref} exception: {e}")
            v = None
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
    FDRData(name="DISA", dataref="sim/weather/region/temperatures_aloft_deg_c[0]"),  # not sure where to fetch temperature offset from ISA
    FDRData(name="ZDAY", dataref="sim/time/zulu_date_days"),  # used to get simulator time
    FDRData(name="ZSEC", dataref="sim/time/zulu_time_sec"),  # used to get simulator date (assume current year)
    FDRData(name="MOVE", dataref="sim/flightmodel2/position/groundspeed"),
    FDRData(name="ABGL", dataref="sim/flightmodel2/position/y_agl"),
    FDRData(name="CHOK", dataref="sim/flightmodel2/gear/is_chocked"),
]
# Through preferences, user can define a set of fdr_info datarefs to complement header information

# "Mandatory" FDR data at start of each CSV line
# They MUST BE the ZULU time, then the longitude, latitude, altitude in feet, magnetic heading in degrees, then pitch and roll in degrees.
FDR_DATA = [
    FDRData(name="longitude", dataref="sim/flightmodel/position/longitude"),
    FDRData(name="latitude", dataref="sim/flightmodel/position/latitude"),
    FDRData(name="altitude", dataref="sim/flightmodel/position/elevation", callback=lambda x: x * 3.28084, unit="ft"),  # m to ft, FDR expects ft
    FDRData(name="heading", dataref="sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot"),
    FDRData(name="pitch", dataref="sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot"),
    FDRData(name="roll", dataref="sim/cockpit2/gauges/indicators/roll_electric_deg_pilot"),
]
# Through preferences, user can define a set of fdr_optional datarefs.

# Constants
#
PLUGIN_ROOT_PATH = os.path.dirname(os.path.abspath(__file__))  # .../PythonPlugins
SCRIPT_NAME = os.path.basename(__file__)

SHOW_TRACE = False
NAME = "FDR"
DESCRIPTION = "Flight Data Recordder"
VERSION = "4.1.8"

FDR_MENU = "Start or stop FDR"
FDR_RESET_COMMAND = "xppython3/fdr/start_stop_toggle"
FDR_RESET_COMMAND_DESC = "Start or stop a new FDR session"
FDR_PLUGIN_SIGNATURE = "com.xppython3.fdr"

FDR_PREFERENCE_FILE = "fdr.yaml"
FDR_VERSION = 4  # 3 or 4
FDR_ARCH = "APPLE"  # "APPLE" or "IBM"

WRITE_FREQUENCY = 10.0  # seconds
REPORT_FREQUENCY = 100 # number of writes

AUTOSTART = True
AUTOSTART_FREQUENCY = 10.0  # secs
AUTOSTART_THRESHOLD = 2.0  # m/s
AUTOSTOP_THRESHOLD = 600.0  # seconds
TAKEOFF_ELEV = 10.0 # m
LANDING_ELEV = 50.0  # m
REG_LEN = 10

class FLIGHT(IntEnum):
    UNKNOWN = 0
    ON_BLOCK = 1
    STOPPED = 2
    MOVING_ON_GROUND = 3
    IN_AIR = 4

class OOOI(IntEnum):
    OUT = 0
    OFF = 1
    ON = 2
    IN = 3


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

        self.recorderFL = None
        self.refRecorder = "FDR:record"

        self.supervisorFL = None
        self.refSupervisor = "FDR:supervisor"

        self.file = None
        self.prefs = {}

        self.header = {d.name: d for d in HEADER}  # collected once
        self.fdr_data = FDR_DATA
        self.fdr_data_by_name = {d.name: d for d in self.fdr_data}

        self.custom_chocks = None

        # Working variables
        self._estimated_state = FLIGHT.UNKNOWN
        self.had_air_time: bool | None = None
        self.last_agl = 0
        self.chocks_removed = None
        self.oooi = {i: None for i in range(len(OOOI))}
        self.oooi_notes = {i: None for i in range(len(OOOI))}
        self.start_time = None
        self.last_stop = None
        self.writes = 0
        self.elevs = []

        # Can be changed in preferences
        self.fdr_info = []
        self.fdr_optional = []
        self.last_acf = ""
        self.frequency = max(self.prefs.get("frequency", WRITE_FREQUENCY), WRITE_FREQUENCY)
        self.report_frequency = max(self.prefs.get("report_frequency", REPORT_FREQUENCY), REPORT_FREQUENCY)
        self.version = self.prefs.get("fdr_version", FDR_VERSION)
        self.arch = self.prefs.get("fdr_arch", FDR_ARCH)
        if self.version not in [3, 4]:
            self.version = FDR_VERSION

    @property
    def fdr_all_data(self) -> dict:
        return self.fdr_data + self.fdr_optional

    @property
    def estimated_state(self) -> FLIGHT:
        return self._estimated_state

    @property
    def chocked(self) -> bool:
        v = self.header.get("CHOK").value if self.custom_chocks is None else self.custom_chocks.value
        return all([t != 0 for t in v]) if type(v) in [list, tuple] else v != 0

    def how_long_stopped(self) -> float:
        # returns total seconds since first stop noticed
        if self.estimated_state not in [FLIGHT.ON_BLOCK, FLIGHT.STOPPED]:
            return 0.0
        if self.last_stop is None:
            self.last_stop = self.system_now_datetime
        return round((self.last_stop - self.system_now_datetime).total_seconds(), 0)

    @property
    def flight_status(self) -> FLIGHT:
        # Are we moving?
        move = self.header.get("MOVE").value
        if move is None:  # we don't know...
            self.debug("flight_status: no movement info")
            return FLIGHT.UNKNOWN
        if move < AUTOSTART_THRESHOLD:
            if self.chocked:
                return FLIGHT.ON_BLOCK
            else:
                if self.last_stop is None:
                    self.last_stop = self.system_now_datetime
                    self.debug("flight_status: stopped")
                return FLIGHT.STOPPED
        # Yes we are moving...
        if self.last_stop is not None:
            self.debug("flight_status: started moving")
            self.last_stop = None
        # Are we in the air?
        elev = self.header.get("ABGL").value
        if elev is None or elev < TAKEOFF_ELEV:
            return FLIGHT.MOVING_ON_GROUND
        # Yes we are in the air...
        if not self.had_air_time:
            self.had_air_time = True
            self.debug("flight_status: air time")

        # Additional: Are we taking of or landing?
        # @todo: possible dynamic adjustment of FDR frequency:
        #        less in cruise, more close to the ground
        self.add_elev(self.system_now_datetime, elev)
        r, e = self.vertical_lr()
        t = self.elevs[-1][0] - self.elevs[0][0]
        self.debug(f"flight_status: vertical regression: {round(r, 2)} m/s ({round(r*196.85039, 0)} ft/m) (delta t={round(t, 2)} secs, {REG_LEN} pts), err={round(e, 2)}")
        if elev < LANDING_ELEV and r < 0.0:
            self.debug("flight_status: landing")
            # self.frequency = 1.0
        elif self.estimated_state == FLIGHT.MOVING_ON_GROUND and elev > TAKEOFF_ELEV and r > 0.0:
            self.debug("flight_status: takeoff")
            # self.frequency = 5.0
        self.last_agl = elev
        return FLIGHT.IN_AIR

    @estimated_state.setter
    def estimated_state(self, new_state: FLIGHT):
        def was(e: FLIGHT):
            return self.estimated_state == e

        if self._estimated_state == new_state:
            return

        zulu = self.simulator_zulu_datetime.replace(microsecond=0) # .isoformat().replace('+00:00', 'Z')

        if was(FLIGHT.UNKNOWN) or new_state == FLIGHT.UNKNOWN:
                self.debug(f"estimated_state: {self._estimated_state.name} => {new_state.name} (at {zulu})")
                self._estimated_state = new_state
                return

        if new_state == FLIGHT.ON_BLOCK:
            if was(FLIGHT.UNKNOWN):
                self._estimated_state = new_state
            elif was(FLIGHT.STOPPED) or was(FLIGHT.MOVING_ON_GROUND):
                if self.had_air_time:
                    self.oooi[OOOI.IN] = zulu
                    self.debug(f"000I: IN at {zulu}", force=True)
                else:
                    self.debug("estimated_state: back on block")
            else:
                self.debug("estimated_state: on block without being stopped")

        elif new_state == FLIGHT.STOPPED:
            if was(FLIGHT.ON_BLOCK):
                self.chocks_removed = zulu
                self.debug("estimated_state: removed chocks")
            elif was(FLIGHT.MOVING_ON_GROUND):
                if self.had_air_time:
                    self.debug("estimated_state: had air time, stopped, may be parked? tentative IN")
                    self.oooi[OOOI.IN] = zulu
                    self.debug(f"000I: IN at {zulu} (unsure)", force=True)
                    self.oooi_notes[OOOI.IN] = "not on blocks, may be stopped on taxiway or apron?"
                else:
                    self.debug("estimated_state: stopped")

        elif new_state == FLIGHT.MOVING_ON_GROUND:
            if was(FLIGHT.IN_AIR):  # landed
                self.oooi[OOOI.ON] = zulu
                self.debug(f"000I: ON at {zulu}", force=True)
            elif was(FLIGHT.ON_BLOCK) or was(FLIGHT.STOPPED) and not self.had_air_time:
                if was(FLIGHT.ON_BLOCK):
                    self.chocks_removed = zulu
                if self.oooi[OOOI.OUT] is None:
                    self.oooi[OOOI.OUT] = zulu
                    self.debug(f"000I: OUT at {zulu}", force=True)

        elif new_state == FLIGHT.IN_AIR:
            self.had_air_time = True
            if was(FLIGHT.MOVING_ON_GROUND):  # take-off
                self.oooi[OOOI.OFF] = zulu
                self.debug(f"000I: OFF at {zulu})", force=True)
            else:
                self.debug("estimated_state: got in air without on ground movement?")

        self.debug(f"estimated_state: {self._estimated_state.name} => {new_state.name} (at {zulu})")
        self._estimated_state = new_state

    def add_elev(self, dt: datetime, alt: float):
        # (timestamp, elevation)
        self.elevs.append((dt.timestamp(), alt))
        if len(self.elevs) > REG_LEN:
            self.elevs = self.elevs[-10:]

    def vertical_lr(self) -> float:
        # linear regression on last altitude checkpoints
        if len(self.elevs) < 3:
            return 0.0
        x = [a[0] for a in self.elevs]
        mx = sum(x)/len(x)
        y = [a[1] for a in self.elevs]
        my = sum(y)/len(y)
        nx2 = sum([(a[0]-mx)*(a[0]-mx) for a in self.elevs])
        ny2 = sum([(a[1]-my)*(a[1]-my) for a in self.elevs])
        nxy = sum([(a[0]-mx)*(a[1]-my) for a in self.elevs])
        r2 = ny2 / (len(self.elevs) - 2)
        r = math.sqrt(r2)
        return nxy / math.sqrt(nx2*ny2) if nx2 != 0.0 and ny2 != 0.0 else 0.0, r

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

    @property
    def system_now_datetime(self) -> datetime:
        return datetime.now().astimezone().replace(microsecond=0)

    def debug(self, message, force: bool = False):
        # ideal message is function_name: message
        if self.trace or force:
            print(f"{self.Info}::{message}")

    #
    # XPPYTHON INTERFACE
    #
    def XPluginStart(self) -> tuple[str, str, str]:
        self.debug("XPluginStart: starting..")

        if len(missing_modules) > 0:
            try:
                xp_pip.load_packages(missing_modules, "Loading missing modules", "Modules loaded.\nCheck for errors, and RESTART X-Plane.")
                self.debug(f"XPluginEnable: loaded packages {missing_modules}", force=True)
            except Exception as e:
                self.debug(f"XPluginEnable: could not load packages {missing_modules}: {e}", force=True)

        for d in self.header.values():
            d.init()

        for d in self.fdr_data:
            d.init()

        # Install plugin in X-Plane
        self.fdrCmdRef = xp.createCommand(FDR_RESET_COMMAND, FDR_RESET_COMMAND_DESC)
        xp.registerCommandHandler(self.fdrCmdRef, self.fdrCmd, 1, None)
        if self.fdrCmdRef is not None:
            self.debug("XPluginStart: command registered")
        else:
            self.debug("XPluginStop: command not registered")

        self.menuIdx = xp.appendMenuItemWithCommand(xp.findPluginsMenu(), FDR_MENU, self.fdrCmdRef)
        if self.menuIdx is None or (self.menuIdx is not None and self.menuIdx < 0):
            self.debug("XPluginStart: menu not added")
        else:
            xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 1)
            self.debug("XPluginStart: menu added")

        self.debug("XPluginStart: ..started")
        return self.Name, self.Sig, self.Desc

    def XPluginStop(self):
        self.debug("XPluginStop: stopping..")

        if self.fdrCmdRef:
            xp.unregisterCommandHandler(self.fdrCmdRef,
                                        self.fdrCmd,
                                        1, None)
            self.fdrCmdRef = None
            self.debug("XPluginStop: command unregistered")
        else:
            self.debug("XPluginStop: command not unregistered")

        if self.menuIdx is not None and self.menuIdx >= 0:
            oldidx = self.menuIdx
            xp.removeMenuItem(xp.findPluginsMenu(), self.menuIdx)
            self.menuIdx = None
            self.debug("XPluginStop: menu removed")
        else:
            self.debug("XPluginStop: menu not removed")

        self.debug("XPluginStop: ..stopped")
        pass

    def XPluginEnable(self) -> int:
        self.debug("XPluginEnable: enabling..")
        self.load_preferences()
        if AUTOSTART:
            self.start_supervisor()
        self.debug("XPluginEnable: ..enabled")
        self._enabled = True
        return 1

    def XPluginDisable(self):
        self.stop_recording()
        self.close_fdr_file()
        if AUTOSTART:
            self.stop_supervisor()
        self.debug("XPluginDisable: disabled")
        self._enabled = False

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        if inMessage != xp.MSG_PLANE_LOADED:
            return
        if not self._enabled:
            return

        self.debug("XPluginReceiveMessage: PLANE_LOADED", force=True)
        acfpath = self.header.get("ACFT").value
        if acfpath is not None and acfpath == self.last_acf:
            return
        self.load_acf_preferences()

    def fdrCmd(self, commandRef, phase: int, refCon: Any):
        if not self._enabled:
            self.debug("fdrCmd: not enabled", force=True)
            return 1

        if phase != 0:
            return 1

        if self.file is None:  # toggle ON
            outfile = self.open_fdr_file()
            self.start_recording()
            self.debug(f"fdrCmd: FDR started manually, saving FDR{self.version} into {outfile}", force=True)
        else:  # toggle OFF
            self.stop_recording()
            self.close_fdr_file()
            self.debug("fdrCmd: FDR stopped manually", force=True)
        return 1

    #
    # PREFERENCES
    #
    def install_preferences(self, newprefs: dict) -> bool:
        desc = newprefs.get("description")
        if desc is not None:
            self.debug(f"install_preferences: installing {desc}..", force=True)
        self.frequency = abs(newprefs.get("frequency", WRITE_FREQUENCY))  # no per frame request
        self.report_frequency = max(newprefs.get("report_frequency", REPORT_FREQUENCY), REPORT_FREQUENCY)  # set to 0 to ignore
        self.version = newprefs.get("fdr_version", FDR_VERSION)
        if self.version not in [3, 4]:
            self.version = FDR_VERSION
        self.arch = newprefs.get("fdr_arch", FDR_ARCH)
        if self.arch not in [FDR_ARCH, "IBM"]:
            self.arch = FDR_ARCH
        custom_chocks = newprefs.get("chocks")
        if custom_chocks is not None:
            if self.custom_chocks is None or custom_chocks != self.custom_chocks.dataref:
                self.custom_chocks = FDRData("CHOK", dataref=custom_chocks)
                self.custom_chocks.init()
                self.debug(f"install_preferences: using custom chocks dataref {custom_chocks}", force=True)
        else:
            self.debug("install_preferences: using default chocks dataref")
            self.custom_chocks = None

        # Add optional datarefs
        opts = newprefs.get("fdr_optional", {})
        if len(opts) > 0:
            if len(self.fdr_optional) > 1:
                self.debug(f"install_preferences: uninstalling {len(self.fdr_optional)} optional datarefs", force=True)
            self.fdr_optional = []
            for d in opts:
                callback = d.get("callback")
                if callback is not None:
                    del d["callback"]
                f = FDRData(**d)
                if callback is not None:
                    if len(callback) < CB_LEN:
                        self.debug(f"install_preferences: eval callback {callback}", force=True)
                        setattr(f, HIDDEN_CB_SRC, callback)
                        f.callback = eval(callback, {}, {})
                    else:
                        self.debug("install_preferences: callback too long, not installed", force=True)
                f.init()
                self.fdr_optional.append(f)
            self.debug(f"install_preferences: added {len(self.fdr_optional)} datarefs to monitor", force=True)

        # Add information datarefs
        opts = newprefs.get("fdr_info", {})
        if len(opts) > 0:
            if len(self.fdr_info) > 1:
                self.debug(f"uninstalling {len(self.fdr_info)} info datarefs", force=True)
            self.fdr_info = []
            for d in opts:
                callback = d.get("callback")
                if callback is not None:
                    del d["callback"]
                f = FDRData(**d)
                if callback is not None:
                    if len(callback) < CB_LEN:
                        self.debug(f"eval callback {callback}", force=True)
                        setattr(f, HIDDEN_CB_SRC, callback)
                        f.callback = eval(callback, {}, {})
                    else:
                        self.debug("install_preferences: callback too long", force=True)
                f.init()
                self.fdr_info.append(f)
            self.debug(f"install_preferences: added {len(self.fdr_info)} info datarefs", force=True)

        self.prefs = newprefs
        if desc is not None:
            self.debug(f"..{desc} installed", force=True)
        return True

    def load_acf_preferences(self) -> bool:
        try:
            acfpath = self.header.get("ACFT").value
            if acfpath is not None and acfpath == self.last_acf:
                self.debug("load_acf_preferences: aircraft preference file already loaded")
                return True
            if acfpath is not None:
                acffile = os.path.join(xp.getSystemPath(), acfpath)
                acffile = os.path.join(os.path.dirname(acffile), FDR_PREFERENCE_FILE)
                if os.path.exists(acffile):  # try aircraft-specific pref
                    self.debug(f"load_acf_preferences: aircraft preference file found at {acffile}", force=True)
                    with open(acffile, "r") as fp:
                        prefs = yaml.load(fp)
                    # with open(acffile.replace("yaml", "toml"), "rb") as fp:
                    #     test = tomllib.load(fp)
                    #     self.debug(f"TOML >>> {test}")
                    if len(prefs) > 0:  # cleanly install prefs
                        was_started = False
                        if self.file is not None:  # close old one
                            was_started = True
                            self.stop_recording()
                            self.close_fdr_file()
                            self.debug("load_acf_preferences: FDR stopped for old preferences", force=True)
                        self.install_preferences(prefs)
                        self.last_acf = acfpath
                        if was_started: # open new one
                            outfile = os.path.join(xp.getSystemPath(), "Output", "fdr")
                            if not os.path.isdir(outfile):
                                os.makedirs(outfile)
                            outfile = self.open_fdr_file()
                            self.start_recording()
                            self.debug(f"load_acf_preferences: FDR started with new preferences, saving FDR{self.version} into {outfile}", force=True)

                    self.debug("load_acf_preferences: aircraft preference file loaded")
                    return True
                else:
                    self.debug(f"load_acf_preferences: no aircraft preference file {acffile}")
        except Exception as e:
            self.debug(f"load_acf_preferences: exception: {e}", force=True)
        return False

    def load_preferences(self) -> bool:
        if self.load_acf_preferences():
            # self.debug(f"load_preferences: already loaded")
            return True  # do not load global preferences
        preffile = os.path.join(xp.getSystemPath(), "Output", "preferences", FDR_PREFERENCE_FILE)
        if os.path.exists(preffile):
            self.debug(f"load_preferences: preference file found at {preffile}", force=True)
            try:
                with open(preffile, "r") as fp:
                    prefs = yaml.load(fp)
                self.install_preferences(prefs)
                self.debug("load_acf_preferences: preference file loaded")
                return True
            except Exception as e:
                self.debug(f"load_preferences: exception: {e}", force=True)
                self.prefs = {}
                return False

        self.debug(f"load_preferences: no preference file {preffile}")
        return False

    #
    # SUPERVISON (auto-start/stop FDR, runs infrequently)
    #
    @property
    def supervisor_running(self) -> bool:
        return self.supervisorFL is not None

    def supervisor(self, elapsedSinceLastCall, elapsedTimeSinceLastFlightLoop, counter, inRefcon):
        try:
            self.estimated_state = self.flight_status
            if self.estimated_state in [FLIGHT.MOVING_ON_GROUND, FLIGHT.IN_AIR] and not self.recorder_running:  # toggle ON
                self.debug("supervisor: move detected, starting FDR..", force=True)
                outfile = os.path.join(xp.getSystemPath(), "Output", "fdr")
                if not os.path.isdir(outfile):
                    os.makedirs(outfile)
                outfile = self.open_fdr_file()
                self.start_recording()
                self.debug(f"supervisor: ..started, saving FDR{self.version} into {outfile}", force=True)
                # else:
                #     self.debug("supervisor: file aready open?", force=True)
            else:  # stop after a 10 minute continuous stopped time out?
                tdiff = self.how_long_stopped()
                if tdiff > AUTOSTOP_THRESHOLD:
                    self.debug(f"supervisor: stopped for {tdiff} seconds, stopping FDR..", force=True)
                    if self.file is not None:
                        self.stop_recording()
                        self.close_fdr_file()
                        self.debug("supervisor: ..FDR stopped", force=True)
                    else:
                        self.debug("supervisor: file aready closed?", force=True)
        except Exception as e:
            self.debug(f"supervisor: exception: {e}", force=True)
        return AUTOSTART_FREQUENCY

    def start_supervisor(self):
        if self.supervisorFL is None:
            self.supervisorFL = xp.createFlightLoop(callback=self.supervisor, phase=xp.FlightLoop_Phase_AfterFlightModel, refCon=self.refSupervisor)
            xp.scheduleFlightLoop(self.supervisorFL, AUTOSTART_FREQUENCY, 1)
            self.debug("start_supervisor: started", force=True)

    def stop_supervisor(self):
        if self.supervisorFL is not None:
            xp.destroyFlightLoop(self.supervisorFL)
            self.supervisorFL = None
        self.debug("stop_supervisor: stopped", force=True)

    #
    # FDR (runs as needed)
    #
    def open_fdr_file(self) -> str:
        outdir = os.path.join(xp.getSystemPath(), "Output", "fdr")
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        outfile = os.path.join(outdir, f"fdr{self.simulator_zulu_datetime.strftime("%Y%m%d%H%M%S")}.fdr")
        self.file = open(outfile, "w")
        return outfile

    def close_fdr_file(self):
        if self.file is not None:
            self.end_situation()
            self.file.close()
            self.file = None

    def start_situation(self):
        if self.file is None:
            return
        self.estimated_state = self.flight_status
        print(f"\nCOMM, INFO Flight state {self.estimated_state.name}", file=self.file)
        lat = self.fdr_data_by_name.get("latitude").value
        lon = self.fdr_data_by_name.get("longitude").value
        alt = self.header.get("ABGL").value
        hdg = self.fdr_data_by_name.get("heading").value
        spd = self.header.get("MOVE").value
        print(f"COMM, INFO lat={lat}, lon={lon}, alt={alt}, hdg={hdg}, speed={spd}", file=self.file)
        print(f"COMM, INFO supervisor={AUTOSTART_FREQUENCY} recorder={self.frequency}", file=self.file)
        print(f"COMM, INFO custom_chocks={self.custom_chocks.dataref if self.custom_chocks is not None else 'none'}", file=self.file)

        # FDR Info
        if len(self.fdr_info) > 0:
            for d in self.fdr_info:
                if d.dref is None:
                    self.debug(f"start_situation: dataref {d} not found", force=True)
                    print(f"COMM, INFO dataref {d} not found", file=self.file)
                    continue
                print(f"COMM, INFO {d.name}: {d.dataref}={d.value}", file=self.file)

    def end_situation(self):
        if all([t is None for t in self.oooi.values()]):
            print("COMM, OOOI ----", file=self.file)
            self.debug("OOOI ----")
            return
        for o in OOOI:
            t = self.oooi[o]
            c = self.oooi_notes[o]
            self.debug(f"OOOI {o.name} {t}" + (f" ({c})" if c is not None else ""), force=True)
            if t is not None:
                print(f"COMM, OOOI {o.name} {t}" + (f" ({c})" if c is not None else ""), file=self.file)

    def csv_header_line(self):
        print(f"{FDR_ARCH[0]}\r{self.version}\n", file=self.file)  # note A may not be visible on Apple computers because of simple carriage return after it (no new line)

        # Script info, use local time
        print(f"COMM, created by {SCRIPT_NAME} rel. {VERSION} on {self.system_now_datetime.isoformat()}\n", file=self.file)

        # FDR Meta data
        print(f"ACFT, {self.header.get('ACFT').value}", file=self.file)
        print(f"TAIL, {self.header.get('TAIL').value}", file=self.file)
        print(f"DATE, {self.simulator_zulu_datetime.strftime("%m/%d/%Y")}", file=self.file)  # MM/DD/YYYY
        print(f"PRES, {round(self.header.get('SEAL').value, 2)}", file=self.file)
        print(f"DISA, {round(self.header.get('DISA').value[0], 2)}", file=self.file)
        print(f"WIND, {int(self.header.get('WDIR').value)}," +
                   f" {round(self.header.get('WSPD').value, 2)}", file=self.file)

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

        # Additional comments
        self.start_situation()

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

    @property
    def recorder_running(self) -> bool:
        return self.file is not None and self.recorderFL is not None

    def record(self, elapsedSinceLastCall, elapsedTimeSinceLastFlightLoop, counter, inRefcon):
        try:
            if self.file is not None:
                self.file.write(self.csv_data_line())
                self.writes = self.writes + 1
                self.file.flush()
                if self.report_frequency > 0 and self.writes % self.report_frequency == 0:
                    self.debug(f"loop: {self.writes} events since {self.start_time.replace(microsecond=0).isoformat()}", force=True)
            else:
                self.debug("loop: no fdr file", force=True)
        except Exception as e:
            self.debug(f"record: exception: {e}", force=True)

        return self.frequency

    def start_recording(self):
        if self.file is not None:
            self.start_time = self.simulator_zulu_datetime
            self.last_stop = None
            self.writes = 0
            self.csv_header_line()
            if self.recorderFL is None:
                self.recorderFL = xp.createFlightLoop(callback=self.record, phase=xp.FlightLoop_Phase_AfterFlightModel, refCon=self.refRecorder)
                xp.scheduleFlightLoop(self.recorderFL, self.frequency, 1)
                xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 2)
                st = self.simulator_zulu_datetime.isoformat()
                print(f"COMM, start recording on {self.system_now_datetime.isoformat()} (sim time={st})\n", file=self.file)
                self.debug(f"start_recording: started at {self.start_time.isoformat()}")
        else:
            self.debug("start_recording: no file, not started")

    def stop_recording(self):
        if self.recorderFL is not None:
            xp.destroyFlightLoop(self.recorderFL)
            xp.checkMenuItem(xp.findPluginsMenu(), self.menuIdx, 1)
            self.recorderFL = None
            if self.file is not None:
                print(f"\n\nCOMM, end recording on {self.system_now_datetime.isoformat()} ({self.writes} writes)", file=self.file)
                print(f"COMM, created by {SCRIPT_NAME} rel. {VERSION} on {self.system_now_datetime.isoformat()}\n", file=self.file)
        self.debug(f"stop_recording: stopped at {self.start_time.isoformat()}")

