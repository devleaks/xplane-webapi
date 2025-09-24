"""OOOI Monitor

Extrernal (to X-Plane) application to detect OOOI ACARS message changes and generate appropriate message.
"""

import logging
import os
import sys
import argparse
from datetime import datetime, timedelta, timezone
from enum import Enum, StrEnum
from typing import Dict, Any, Tuple

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import humanize
import xpwebapi

from xpwsapp import XPWSAPIApp

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


version = "1.0.0"


class DATAREFS(StrEnum):
    GROUND_SPEED = "sim/flightmodel2/position/groundspeed"
    AGL = "sim/flightmodel/position/y_agl"
    TRACKING = "sim/cockpit2/gauges/indicators/ground_track_mag_pilot"  # The ground track of the aircraft in degrees magnetic
    HEADING = "sim/cockpit2/gauges/indicators/compass_heading_deg_mag"  # Indicated heading of the wet compass, in degrees.
    DAYS = "sim/time/local_date_days"
    ZULU_SECS = "sim/time/zulu_time_sec"


class OOOI(Enum):
    OUT = "off-block"  # When the aircraft leaves the gate or parking position
    OFF = "takeoff"  # When the aircraft takes off from the runway
    ON = "landing"  # When the aircraft lands on the destination runway
    IN = "on-block"  # When the aircraft arrives at the gate or parking position


class PHASE(Enum):
    ON_BLOCK = "on blocks"
    TAXI_OUT = "taxi out"
    ON_HOLD = "on hold"
    TAKEOFF_ROLL = "takeoff"
    FLYING = "air"
    LANDING_ROLL = "landing"
    TAXI_IN = "taxi in"


# Thresholds
#
EPOCH = datetime(year=1970, month=1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

STOPPED_SPEED_MARGIN = 0.1
TAXI_SPEED_MARGIN = 20  # 11m/s = 40 km/h
ROLL_SPEED_MARGIN = 50  # 50m/s = 97knt
AIR_SPEED_MARGIN = 50  # 72m/s = 140knt, should be in air...
ALT_MARGIN = 5  # meters, significant altitude difference, we're climbing/descending
ALT_THRESHOLD_UP = 30  # above that AGL, we're taking off
ALT_THRESHOLD_DOWN = 10  # below that AGL, we're landing
MIN_FLIGHT_TIME = 120
AIR_AGL_MARGIN = 30  # meters
HOLD_MAX_TIME = 300  # secs, 5 minutes
ALWAYS_FOUR = False  # show always 4 values like EBCI/EBBR OUT/1644 OFF/---- ON/---- IN/---- [ETA/nnnn]
ETA_REMINDER = 600  # secs, 10 minutes


def now() -> datetime:
    return datetime.now(timezone.utc)


class OOOIManager(XPWSAPIApp):

    def __init__(self, api, departure: str, arrival: str, callsign: str, logon: str, station: str, eta: datetime | None = None) -> None:
        XPWSAPIApp.__init__(self, api=api)

        self.departure = departure
        self.arrival = arrival
        self.callsign = callsign
        self.station = station
        self.logon = logon
        self.eta: datetime | None = None
        self.last_eta = now()

        self.first: Dict[str, Any] = {}
        self.last: Dict[str, Any] = {}

        self.speed_trend = 0
        self.alt_trend = 0
        self.last_stop = None
        self.current_state: PHASE | None = None

        self.current_oooi: OOOI | None = None
        self.all_oooi: Dict[OOOI, datetime] = {}

        # debug
        self._onblock = False

    def set_api(self, api):
        self.ws = api
        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}
        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)

    def start(self):
        pass

    def stop(self):
        pass

    def loop(self):
        pass

    @property
    def oooi(self) -> OOOI | None:
        return self.current_oooi

    @oooi.setter
    def oooi(self, report: OOOI | Tuple[OOOI, datetime]):
        # Changes OOOI and set timestamp to supplied value if any
        newoooi = report if type(report) is OOOI else report[0]
        if self.current_oooi is None or self.current_oooi != newoooi:
            self.current_oooi = newoooi
            self.all_oooi[newoooi] = now() if type(report) is OOOI else report[1]
        self.report()

    def no_value(self, oooi: OOOI):
        self.all_oooi[oooi] = EPOCH

    def has_value(self, oooi: OOOI) -> bool:
        return self.all_oooi.get(oooi, EPOCH) != EPOCH

    @property
    def inited(self) -> bool:
        return len([d for d in self.first if d is not None]) == len(DATAREFS)

    @property
    def pushback(self) -> bool:
        if not self.inited:
            return False
        h = self.first.get(DATAREFS.HEADING)
        t = self.first.get(DATAREFS.TRACKING)
        if h > 270 and t < 90:
            t = t + 360
        elif h < 90 and t > 270:
            h = h + 360
        return abs(h - t) > 40  # we are not moving in the direction of the heading of the aircraft

    def set_eta(self, eta: datetime):
        # when we get one...
        first = self.eta is None
        self.eta = eta
        logger.info(f"eta {self.eta.replace(second=0, microsecond=0)}")
        if not first:
            self.report()
            self.last_eta = now()

    def get_dataref_names(self) -> set:
        return [d.value for d in DATAREFS]

    def dataref_value(self, dataref: str):
        dref = self.datarefs.get(dataref)
        return dref.value if dref is not None else 0

    @property
    def sim_time(self) -> datetime:
        days = self.dataref_value(DATAREFS.DAYS)
        secs = self.dataref_value(DATAREFS.ZULU_SECS)
        return datetime.now(timezone.utc).replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days, seconds=secs)

    def report(self, display: bool = True) -> str:
        """Build short string with all values, displays it on console

        Returns:
            str: string with all values
        """
        def strfdelta(tdelta):
            ret = ""
            if tdelta.days > 0:
                ret = f"{tdelta.days} d "
            h, rem = divmod(tdelta.seconds, 3600)
            ret = ret + f"{h:02d}"
            m, s = divmod(rem, 60)
            ret = ret + f"{m:02d}{s:02d}:"
            return ret

        TIME_FMT = "%H%M"

        def pt(ts: datetime | None):
            if ts is None:
                return "----"
            if ts == EPOCH:
                return "...?"
            return ts.strftime(TIME_FMT)

        report = f"{self.departure}/{self.arrival}"
        off_set = False
        if self.all_oooi.get(OOOI.OUT) is not None:
            report = report + f" OUT/{pt(self.all_oooi.get(OOOI.OUT))}"
        else:
            report = report + " OUT/----"
        if self.all_oooi.get(OOOI.OFF) is not None:
            report = report + f" OFF/{pt(self.all_oooi.get(OOOI.OFF))}"
        else:
            report = report + " OFF/----"
            off_set = True

        if self.all_oooi.get(OOOI.ON) is not None:
            report = report + f" ON/{pt(self.all_oooi.get(OOOI.ON))}"

            if self.all_oooi.get(OOOI.IN) is not None:
                report = report + f" IN/{pt(self.all_oooi.get(OOOI.IN))}"
            else:
                report = report + " IN/----"
                if self.eta is not None and self.eta > self.all_oooi.get(OOOI.ON):  # ETA after landing might be ETA "at the gate"
                    report = report + f" ETA/{pt(self.eta)}"
        else:
            if not off_set or ALWAYS_FOUR:
                report = report + " ON/----"
                if ALWAYS_FOUR:
                    report = report + " IN/----"
            if self.eta is not None:
                report = report + f" ETA/{pt(self.eta)}"

        time_info = ""
        if self.all_oooi.get(OOOI.OFF) is not None and self.all_oooi.get(OOOI.ON) is not None:
            flight_time = self.all_oooi.get(OOOI.ON) - self.all_oooi.get(OOOI.OFF)
            time_info = f"flight time: {strfdelta(flight_time)}"
        if self.all_oooi.get(OOOI.OUT) is not None and self.all_oooi.get(OOOI.IN) is not None:
            block_time = self.all_oooi.get(OOOI.IN) - self.all_oooi.get(OOOI.OUT)
            if time_info != "":
                time_info = time_info = ", "
            time_info = time_info + f"block time: {strfdelta(block_time)}"

        if display:
            logger.info(report)
            if time_info != "":
                logger.info(time_info)
        return report

    def acars_report(self) -> Dict:
        return {"from": self.callsign, "to": self.station, "acars_type": "progress", "packet": self.report()}

    # def both_engine_off(self):
    #     return True

    def inital_state(self):
        if self.inited:
            return
        for d in DATAREFS:
            if d not in self.first or self.first.get(d) is None:
                v = self.dataref_value(d)
                if v is not None:
                    self.first[d] = v
                    self.last[d] = v
                    logger.debug(f"first value for {d}={v}")
        if not self.inited:
            return

        logger.debug("all dataref values received at least once, determining initial state..")

        # We have a first value for all variables, try to determine initial state
        speed = self.first.get(DATAREFS.GROUND_SPEED)
        agl = self.first.get(DATAREFS.AGL)
        # 1. Are we in the air?
        if agl > AIR_AGL_MARGIN and speed > AIR_SPEED_MARGIN:
            logger.debug("we are in the air")
            self.current_state = PHASE.FLYING
            logger.debug(f"speed {round(speed, 2)} > {AIR_SPEED_MARGIN}, alt {round(agl, 2)} > {AIR_AGL_MARGIN}, assuming {PHASE.FLYING.value}")
            logger.debug("no off-block time, no take-off time")
            self.no_value(OOOI.OUT)
            self.no_value(OOOI.OFF)
            self.oooi = (OOOI.OFF, EPOCH)
            self.show_values(f"..initialized ({self.current_state})", first=True)
            return
        else:  # 2. We are on the ground.
            logger.debug("we are on the ground")

            # 2.1 Are we moving?
            if speed < STOPPED_SPEED_MARGIN:
                self.set_last_stop()
                logger.debug("we are stopped")
                self.current_state = PHASE.ON_BLOCK
                logger.debug(f"speed {round(speed, 2)} < {STOPPED_SPEED_MARGIN}, assuming {PHASE.ON_BLOCK.value}")
                self.report()
                self.show_values(f"..initialized ({self.current_state})", first=True)
                return
            if agl < AIR_AGL_MARGIN and speed < TAXI_SPEED_MARGIN:
                logger.debug("we are taxiing")
                self.current_state = PHASE.TAXI_OUT
                logger.debug(f"speed {round(speed, 2)} < {TAXI_SPEED_MARGIN}, assuming {PHASE.TAXI_OUT.value}, no off-block time")
                self.oooi = (OOOI.OUT, EPOCH)
                self.show_values(f"..initialized ({self.current_state})", first=True)
                return
            if speed > ROLL_SPEED_MARGIN:
                logger.debug("we are rolling fast")
                if self.speed_trend is not None:
                    if self.speed_trend > 0:
                        self.current_state = PHASE.TAKEOFF_ROLL
                        logger.debug(f"speed {round(speed, 2)} > {ROLL_SPEED_MARGIN}, assuming {PHASE.TAKEOFF_ROLL.value}")
                        self.oooi = (OOOI.OUT, EPOCH)  # we're moving, but haven't taken off yet
                    elif self.speed_trend <= 0:
                        self.current_state = PHASE.LANDING_ROLL
                        logger.debug(f"speed {round(speed, 2)} > {ROLL_SPEED_MARGIN}, assuming {PHASE.LANDING_ROLL.value}")
                        self.no_value(OOOI.OUT)
                        self.no_value(OOOI.OFF)
                        self.oooi = OOOI.ON

        self.show_values(f"..initialized ({self.current_state})", first=True)

    def show_values(self, welcome: str = "", first: bool = False):
        values = self.first if first else self.last
        logger.debug(f"{welcome}\n{'\n'.join([f'{d} = {values[d]}' for d in values])}")

    def set_last_stop(self, force: bool = False):
        if self.last_stop is None or force:
            logger.debug("setting last stop")
            self.last_stop = now()

    def how_long_waiting(self, mark: bool = False):
        if self.last_stop is None:
            if mark:
                self.last_stop = now()
            return 0
        howlong = now() - self.last_stop
        if mark:
            self.last_stop = now()
        return howlong.seconds

    def dataref_changed(self, dataref, value):
        self.datarefs[dataref].value = value

        if dataref not in self.get_dataref_names():
            return  # not for me, should never happen

        if not self.inited:
            self.inital_state()
            return

        # For each state, check if there is a change:
        speed = self.last[DATAREFS.GROUND_SPEED]
        if dataref == DATAREFS.GROUND_SPEED:
            diff = speed - value
            if abs(diff) > STOPPED_SPEED_MARGIN:
                self.speed_trend = -1 if diff < 0 else 1
            else:
                self.speed_trend = 0
            speed = value  # update

        if self.oooi is None:
            if self.current_state == PHASE.ON_BLOCK:
                if self.oooi is None:
                    if speed > STOPPED_SPEED_MARGIN:  # we were ON_BLOCK, we are now moving... (may be strong wind?)
                        logger.debug("set state to OOOI.OUT")
                        self.oooi = OOOI.OUT
                    else:
                        if not self._onblock:
                            self._onblock = True
                            logger.debug("No OOOI, not moving, we're on block")

        alt = self.last[DATAREFS.AGL]
        if dataref == DATAREFS.AGL:
            diff = alt - value
            if abs(diff) > ALT_MARGIN:
                self.alt_trend = -1 if diff < 0 else 1
            else:
                self.alt_trend = 0
            alt = value

        if self.oooi == OOOI.OUT:  # we no longer at the gate/parked
            if dataref == DATAREFS.AGL:
                alt_diff = alt - self.last.get(DATAREFS.AGL)  # we took off, shoukd also check speed >> max_taxi_speed (~=60 km/h)
                if alt_diff > ALT_THRESHOLD_UP or alt > ALT_THRESHOLD_UP:
                    logger.debug(f"we climb, we're OFF ({alt}, {alt_diff})")
                    self.oooi = OOOI.OFF
            if dataref == DATAREFS.GROUND_SPEED:
                if speed < STOPPED_SPEED_MARGIN:  # we're stopped, may be we were taxiing IN when we assumed we were taxiing out...
                    if self.how_long_waiting() < HOLD_MAX_TIME:
                        self.set_last_stop()
                        logger.debug(
                            f"waiting less than {humanize.naturaltime(HOLD_MAX_TIME)}, assuming {PHASE.ON_HOLD.value}, arrived at {self.last_stop}"
                        )  # less than 5 minutes on same spot, we assume it is a HOLD.
                    else:
                        logger.info(
                            f"waiting more than {humanize.naturaltime(HOLD_MAX_TIME)}, assuming {PHASE.ON_BLOCK.value} {humanize.naturaldelta(HOLD_MAX_TIME)}, stopped since {self.last_stop}"
                        )
                        self.oooi = (OOOI.ON, self.last_stop)
                else:
                    self.last_stop = None

        if self.oooi == OOOI.OFF:  # we're flying
            if dataref == DATAREFS.AGL:
                alt = value
                if alt < ALT_THRESHOLD_DOWN:
                    reftime = now()
                    takeoff_time = self.all_oooi.get(OOOI.OFF)
                    if takeoff_time is not None:
                        flight_time = reftime - takeoff_time
                        logger.debug(f"we flew {flight_time.seconds}")
                        if flight_time.seconds < MIN_FLIGHT_TIME:  # did we stay in the air 2 minutes at least? May be we crashed?
                            logger.warning(f"we flew less than {MIN_FLIGHT_TIME} seconds, no ON time")
                    else:
                        logger.warning("no take off reference time, assuming we landed")
                    self.oooi = OOOI.ON

        if self.oooi == OOOI.ON:  # We're back on the ground
            if dataref == DATAREFS.GROUND_SPEED:
                speed = value
                if speed < STOPPED_SPEED_MARGIN:  # we're stopped
                    reftime = now()
                    landing_time = self.all_oooi.get(OOOI.ON)
                    if landing_time is not None:
                        taxi_time = reftime - landing_time
                        # are both engine off?
                        if taxi_time.seconds > HOLD_MAX_TIME:  # and self.both_engine_off():
                            logger.debug(f"we are stopped, we taxied in for {round(taxi_time.seconds)} secs., assuming we stopped at gate")
                            self.oooi = OOOI.IN
                    else:
                        logger.warning("no landing reference time, assuming we stopped at gate")
                        self.oooi = OOOI.IN

        if (now() - self.last_eta).seconds > ETA_REMINDER:  # display report every ETA_REMINDER to show 1. it's alive, 2. ETA has not changed
            self.report()
            self.last_eta = now()

        self.last[dataref] = value

    def terminate(self):
        ws.unmonitor_datarefs(datarefs=self.datarefs, reason=self.name)
        self.ws.disconnect()

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
    app = OOOIManager(api, departure="EBCI", arrival="EBBR", callsign="BEL034", logon="none", station="EBJA")
    app.set_eta(now() + timedelta(minutes=30))
    try:
        app.run()
    except KeyboardInterrupt:
        logger.warning("terminating..")
        app.terminate()
        logger.warning("..terminated")
