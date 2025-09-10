"""OOOI Monitor

Extrernal (to X-Plane) application to detect OOOI ACARS message changes and generate appropriate message.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from time import ctime
from enum import Enum, StrEnum
from typing import Dict, Any

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import humanize
import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class DREFS(StrEnum):
    GROUND_SPEED = "sim/flightmodel2/position/groundspeed"
    AGL = "sim/flightmodel/position/y_agl"
    TRACKING = "sim/cockpit2/gauges/indicators/ground_track_mag_pilot"  # The ground track of the aircraft in degrees magnetic
    HEADING = "sim/cockpit2/gauges/indicators/compass_heading_deg_mag"  # Indicated heading of the wet compass, in degrees.

LANDING_EVALUATION_DATAREFS = {
    "sim/aircraft/view/acf_ICAO",
    "sim/aircraft/view/acf_tailnum",
    "sim/flightmodel/forces/fnrml_gear",
    "sim/flightmodel/position/elevation",
    "sim/flightmodel/position/indicated_airspeed",
    "sim/flightmodel/position/latitude",
    "sim/flightmodel/position/local_vy",
    "sim/flightmodel/position/longitude",
    "sim/flightmodel/position/y_agl",
    "sim/flightmodel2/gear/tire_vertical_deflection_mtr",
    "sim/flightmodel2/position/true_phi",
    "sim/flightmodel2/position/true_psi",
    "sim/flightmodel2/position/true_theta",
    "sim/time/total_flight_time_sec",
    # ToLiss specifics
    "AirbusFBW/GearStrutCompressDist_m",
    "AirbusFBW/IASCapt",
    "toliss_airbus/pfdoutputs/general/VLS_value",
}


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
ALT_MARGIN = 20  # ft
ALT_THRESHOLD_UP = 30
ALT_THRESHOLD_DOWN = 10
MIN_FLIGHT_TIME = 120
AIR_AGL_MARGIN = 30  # meters
HOLD_MAX_TIME = 300  # secs, 5 minutes
ALWAYS_FOUR = False  # show always 4 values like EBCI/EBBR OUT/1644 OFF/---- ON/---- IN/----
ETA_REMINDER = 600 # secs, 10 minutes

def now() -> datetime:
    return datetime.now(timezone.utc)


class OOOIManager:

    def __init__(self, api, departure: str, arrival: str, callsign: str, logon: str, station: str, eta: datetime | None = None) -> None:
        self.name = "OOOI"
        self.ws = api

        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}

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
        self.cnt = 0

        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)

    def start(self):
        ws.connect()
        ws.wait_connection()
        ws.monitor_datarefs(datarefs=self.datarefs, reason=self.name)
        ws.start()

    @property
    def oooi(self) -> OOOI | None:
        return self.current_oooi

    @oooi.setter
    def oooi(self, report: OOOI):
        if self.current_state == report:
            return  # no change
        self.current_oooi = report
        # self.all_oooi[report] = now()
        self.report()

    def change_oooi(self, oooi: OOOI, ts: datetime | None = None):
        if ts is None:
            ts = now()
        self.all_oooi[oooi] = ts
        if self.oooi is None or self.oooi != oooi:
            self.oooi = oooi
            # self.show_values(str(oooi))
            self.report()
        else:
            logger.warning("change to same value?")

    def no_value(self, oooi: OOOI):
        self.all_oooi[oooi] = EPOCH

    def has_value(self, oooi: OOOI) -> bool:
        return self.all_oooi.get(oooi, EPOCH) != EPOCH

    @property
    def inited(self) -> bool:
        return len([d for d in self.first if d is not None]) == len(DREFS)

    @property
    def pushback(self) -> bool:
        if not self.inited:
            return False
        h = self.first.get(DREFS.HEADING)
        t = self.first.get(DREFS.TRACKING)
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
        return [d.value for d in DREFS]

    def dataref_value(self, dataref: str):
        dref = self.datarefs.get(dataref)
        return dref.value if dref is not None else 0

    @property
    def sim_time(self) -> datetime:
        days = self.dataref_value("sim/time/local_date_days")
        secs = self.dataref_value("sim/time/zulu_time_sec")
        return datetime.now(timezone.utc).replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days, seconds=secs)

    def report(self, display: bool = True) -> str:
        """Build short string with all values, displays it on console

        Returns:
            str: string with all values
        """
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
                if self.eta is not None and self.eta > self.all_oooi.get(OOOI.ON):  # ETA after landing might be ETA "at the gate"
                    report = report + f" ETA/{pt(self.eta)}"
                else:
                    report = report + " IN/----"
        else:
            if self.eta is not None:
                report = report + f" ETA/{pt(self.eta)}"
            else:
                if not off_set or ALWAYS_FOUR:
                    report = report + " ON/----"
                if ALWAYS_FOUR:
                    report = report + " IN/----"
        if display:
            logger.info(report)
        return report

    def acars_report(self) -> Dict:
        return {"from": self.callsign, "to": self.station, "acars_type": "progress", "packet": self.report()}

    # def both_engine_off(self):
    #     return True

    def inital_state(self):
        if self.inited:
            return
        for d in DREFS:
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
        speed = self.first.get(DREFS.GROUND_SPEED)
        agl = self.first.get(DREFS.AGL)
        # 1. Are we in the air?
        if agl > AIR_AGL_MARGIN and speed > AIR_SPEED_MARGIN:
            logger.debug("we are in the air")
            self.current_state = PHASE.FLYING
            logger.debug(f"speed {round(speed, 2)} > {AIR_SPEED_MARGIN}, alt {round(agl, 2)} > {AIR_AGL_MARGIN}, assuming {PHASE.FLYING.value}")
            logger.debug("no off-block time, no take-off time")
            self.no_value(OOOI.OUT)
            self.no_value(OOOI.OFF)
            self.change_oooi(OOOI.OFF, EPOCH)
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
                self.change_oooi(OOOI.OUT, EPOCH)
                self.show_values(f"..initialized ({self.current_state})", first=True)
                return
            if speed > ROLL_SPEED_MARGIN:
                logger.debug("we are rolling fast")
                if self.speed_trend is not None:
                    if self.speed_trend > 0:
                        self.current_state = PHASE.TAKEOFF_ROLL
                        logger.debug(f"speed {round(speed, 2)} > {ROLL_SPEED_MARGIN}, assuming {PHASE.TAKEOFF_ROLL.value}")
                        self.change_oooi(OOOI.OUT, EPOCH)  # we're moving, but haven't taken off yet
                    elif self.speed_trend <= 0:
                        self.current_state = PHASE.LANDING_ROLL
                        logger.debug(f"speed {round(speed, 2)} > {ROLL_SPEED_MARGIN}, assuming {PHASE.LANDING_ROLL.value}")
                        self.no_value(OOOI.OUT)
                        self.no_value(OOOI.OFF)
                        self.change_oooi(OOOI.ON)

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
        speed = self.last[DREFS.GROUND_SPEED]
        if dataref == DREFS.GROUND_SPEED:
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
                        self.change_oooi(OOOI.OUT)
                    else:
                        if not self._onblock:
                            self._onblock = True
                            logger.debug("No OOOI, not moving, we're on block")

        alt = self.last[DREFS.AGL]
        if dataref == DREFS.AGL:
            diff = alt - value
            if abs(diff) > ALT_MARGIN:
                self.alt_trend = -1 if diff < 0 else 1
            else:
                self.alt_trend = 0
            alt = value

        if self.oooi == OOOI.OUT:  # we no longer at the gate/parked
            if dataref == DREFS.AGL:
                if self.cnt % 20:
                    self.cnt = self.cnt + 1
                    logger.debug("current state is OOOI.OUT")
                alt_diff = alt - self.last.get(AGL)  # we took off, shoukd also check speed >> max_taxi_speed (~=60 km/h)
                if alt_diff > ALT_THRESHOLD_UP or alt > ALT_THRESHOLD_UP:
                    logger.debug(f"we climb, we're OFF ({alt}, {alt_diff})")
                    self.change_oooi(OOOI.OFF)
                else:
                    if self.cnt % 20:
                        self.cnt = self.cnt + 1
                        logger.debug(f"we're on the ground ({alt}, {alt_diff})")
            if dataref == DREFS.GROUND_SPEED:
                if speed < STOPPED_SPEED_MARGIN:  # we're stopped, may be we were taxiing IN when we assumed we were taxiing out...
                    if self.cnt % 20:
                        self.cnt = self.cnt + 1
                        logger.debug("current state is OOOI.OUT")
                    if self.how_long_waiting() < HOLD_MAX_TIME:
                        self.set_last_stop()
                        logger.debug(
                            f"waiting less than {humanize.naturaltime(HOLD_MAX_TIME)}, assuming {PHASE.ON_HOLD.value}, arrived at {self.last_stop}"
                        )  # less than 5 minutes on same spot, we assume it is a HOLD.
                    else:
                        logger.info(
                            f"waiting more than {humanize.naturaltime(HOLD_MAX_TIME)}, assuming {PHASE.ON_BLOCK.value} {humanize.naturaldelta(HOLD_MAX_TIME)}, stopped since {self.last_stop}"
                        )
                        self.change_oooi(OOOI.ON, self.last_stop)
                else:
                    if self.cnt % 20:
                        self.cnt = self.cnt + 1
                        logger.debug("we're taxiing out")
                    self.last_stop = None

        if self.oooi == OOOI.OFF:  # we're flying
            if dataref == DREFS.AGL:
                alt = value
                if alt < ALT_THRESHOLD_DOWN:
                    if self.cnt % 20:
                        self.cnt = self.cnt + 1
                        logger.debug("we're lower than 30m, we're ON")
                    reftime = now()
                    takeoff_time = self.all_oooi.get(OOOI.OFF)
                    if takeoff_time is not None:
                        flight_time = reftime - takeoff_time
                        logger.debug(f"we flew {flight_time.seconds}")
                        if flight_time.seconds < MIN_FLIGHT_TIME:  # did we stay in the air 2 minutes at least? May be we crashed?
                            logger.warning(f"we flew less than {MIN_FLIGHT_TIME} seconds, no ON time")
                    else:
                        logger.warning("no take off reference time, assuming we landed")
                    self.change_oooi(OOOI.ON)

        if self.oooi == OOOI.ON:  # We're back on the ground
            if dataref == DREFS.GROUND_SPEED:
                if self.cnt % 20:
                    self.cnt = self.cnt + 1
                    logger.debug(f"current state is OOOI.ON ({dataref}={round(value, 1)})")
                speed = value
                if speed < STOPPED_SPEED_MARGIN:  # we're stopped
                    reftime = now()
                    landing_time = self.all_oooi.get(OOOI.ON)
                    if landing_time is not None:
                        taxi_time = reftime - landing_time
                        # are both engine off?
                        if taxi_time.seconds > HOLD_MAX_TIME:  # and self.both_engine_off():
                            logger.debug(f"we are stopped, we taxied in for {round(taxi_time.seconds)} secs., assuming we stopped at gate")
                            self.change_oooi(OOOI.IN)
                    else:
                        logger.warning("no landing reference time, assuming we stopped at gate")
                        self.change_oooi(OOOI.IN)

        if (now() - self.last_eta).seconds > ETA_REMINDER:  # display report every ETA_REMINDER to show 1. it's alive, 2. ETA has not changed
            self.report()
            self.last_eta = now()

        self.last[dataref] = value

    def terminate(self):
        ws.unmonitor_datarefs(datarefs=self.datarefs, reason=self.name)
        self.ws.disconnect()


if __name__ == "__main__":
    ws = xpwebapi.ws_api()
    oooi = OOOIManager(ws, departure="EBCI", arrival="EBBR", callsign="BEL034", logon="none", station="EBJA")
    try:
        oooi.set_eta(now() + timedelta(minutes=30))
        oooi.start()
    except KeyboardInterrupt:
        logger.warning("terminating..")
        oooi.terminate()
        logger.warning("..terminated")
