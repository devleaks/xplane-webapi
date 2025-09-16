"""Landing Rating

Extrernal (to X-Plane) application to detect OOOI ACARS message changes and generate appropriate message.

Notes:
Runway where aircraft should land is called TARGET RUNWAY.
Landing monitoring starts when aircraft below ALT_LOW (=150m AGL).
Monitoring stops when ground speed < SPEED_SLOW (=15 m/S ~= 40km/h)

"""

import logging
import os
import sys
import math
import csv
import threading
from enum import StrEnum
from datetime import datetime, timezone
from typing import Dict, Tuple, List, Any
from dataclasses import dataclass

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi
from kml import to_kml

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# ###############################
# Utility function
#
R = 6371000  # Radius of third rock from the sun, in metres
FT = 12 * 0.0254  # 1 FOOT = 12 INCHES
NAUTICAL_MILE = 1.852  # Nautical mile in meters 6076.118ft=1nm
MS_2_FPM = 196.850
M_2_FT = 3.2808
G = 9.80665


def now() -> datetime:
    return datetime.now(timezone.utc)


# Geo essentials
#
def angle_to_360(alfa):
    beta = alfa % 360
    if beta < 0:
        beta = beta + 360
    return beta


def haversine(lat1: float, lat2: float, lon1: float, lon2: float) -> float:  # in radians.
    dlat, dlon = lat2 - lat1, lon2 - lon1
    return math.pow(math.sin(dlat / 2), 2) + math.cos(lat1) * math.cos(lat2) * math.pow(math.sin(dlon / 2), 2)


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:  # in degrees.
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    lon1, lon2 = math.radians(lon1), math.radians(lon2)
    a = haversine(lat1, lat2, lon1, lon2)
    return 2 * R * math.asin(math.sqrt(a))  # in m


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    t = math.atan2(y, x)
    brng = angle_to_360(math.degrees(t))  # in degrees
    return brng


def destination(lat: float, lon: float, brngDeg: float, d: float) -> Tuple[float, float]:
    # From lat, lon, move d meters heading brngDeg
    lat = math.radians(lat)
    lon = math.radians(lon)
    brng = math.radians(brngDeg)
    r = d / R

    lat2 = math.asin(math.sin(lat) * math.cos(r) + math.cos(lat) * math.sin(r) * math.cos(brng))
    lon2 = lon + math.atan2(
        math.sin(brng) * math.sin(r) * math.cos(lat),
        math.cos(r) - math.sin(lat) * math.sin(lat2),
    )
    return (math.degrees(lat2), math.degrees(lon2))


def point_in_polygon(point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
    # this will do. We do very local geometry (5000m around current location)
    # pt is [x,y], pol is [[x,y],...]; should be "closed", pol[0] == pol[-1].
    pt = point
    pol = polygon
    inside = False
    for i in range(len(pol)):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % len(pol)]
        if not min(y0, y1) < pt[1] <= max(y0, y1):
            continue
        if pt[0] < min(x0, x1):
            continue
        cur_x = x0 if x0 == x1 else x0 + (pt[1] - y0) * (x1 - x0) / (y1 - y0)
        inside ^= pt[0] > cur_x
    return inside


# Line = {start, end}, start, end are point
# Point = {lat, lon}
@dataclass
class Point:
    lat: float
    lon: float


@dataclass
class Line:
    start: Point
    end: Point


@dataclass
class Runway:
    id: int
    airport_ref: int
    airport_ident: str
    length_ft: float
    width_ft: float
    surface: str
    lighted: int
    closed: int
    le_ident: str
    le_latitude_deg: float
    le_longitude_deg: float
    le_elevation_ft: float
    le_heading_degT: float
    le_displaced_threshold_ft: float
    he_ident: str
    he_latitude_deg: float
    he_longitude_deg: float
    he_elevation_ft: float
    he_heading_degT: float
    he_displaced_threshold_ft: float
    cached_bbox = []

    def __str__(self) -> str:
        return f"{self.airport_ident} {self.le_ident}/{self.he_ident}"

    def name(self, orient: str = "") -> str:
        if orient == "":
            return str(self)
        if orient.startswith("e"):
            return f"{self.airport_ident} {self.le_ident}"
        return f"{self.airport_ident} {self.he_ident}"

    def values(self, orient: str) -> Tuple[float, float, float, float, float]:
        # lat, log, elev, heading, displaced_threshold
        # lat, log, alt, hdg, disp = runway.values(orient="le")
        if orient.startswith("e"):
            return self.le_latitude_deg, self.le_longitude_deg, self.le_elevation_ft, self.le_heading_degT, self.le_displaced_threshold_ft
        return self.he_latitude_deg, self.he_longitude_deg, self.he_elevation_ft, self.he_heading_degT, self.he_displaced_threshold_ft

    @property
    def bbox(self):
        if len(self.cached_bbox) > 0:
            return self.cached_bbox

        def val(instr: str) -> float:
            return 0 if instr == "" else float(instr)

        lat1, lon1 = self.le_latitude_deg, self.le_longitude_deg
        lat2, lon2 = self.he_latitude_deg, self.he_longitude_deg
        brgn = bearing_deg(lat1, lon1, lat2, lon2)  # bearing 1 -> 2
        if self.width_ft == NOT_SET:
            self.width_ft = 100   # forced default, 30m wide
        halfwidth = (self.width_ft / M_2_FT) / 2

        # Displaced threshold
        # Backup le point
        if self.le_displaced_threshold_ft != NOT_SET:
            m = self.le_displaced_threshold_ft / M_2_FT
            nlat1, nlon1 = destination(lat1, lon1, brgn + 180, m)
            lat1 = nlat1
            lon1 = nlon1

        # Move forward he point
        if self.he_displaced_threshold_ft != NOT_SET:
            m = self.he_displaced_threshold_ft / M_2_FT
            nlat2, nlon2 = destination(lat2, lon2, brgn, m)
            lat2 = nlat2
            lon2 = nlon2

        bbox = []
        lat, lon = destination(lat1, lon1, brgn + 90, halfwidth)
        bbox.append((lat, lon))
        lat, lon = destination(lat1, lon1, brgn - 90, halfwidth)
        bbox.append((lat, lon))
        lat, lon = destination(lat2, lon2, brgn - 90, halfwidth)
        bbox.append((lat, lon))
        lat, lon = destination(lat2, lon2, brgn + 90, halfwidth)
        bbox.append((lat, lon))
        bbox.append(bbox[0])
        self.cached_bbox = bbox
        return self.cached_bbox

    def inside(self, lat: float, lon: float) -> bool:
        return point_in_polygon(point=(lat, lon), polygon=self.bbox)

def mkLine(lat1: float, lon1: float, lat2: float, lon2: float):
    return Line(Point(lat1, lon1), Point(lat2, lon2))


def line_intersect(line1: Line, line2: Line) -> Point | None:
    # Finds intersection of line1 and line2. Returns Point() of intersection or None.
    # !! Source code copied from GeoJSON code where coordinates are (longitude, latitude).
    x1 = line1.start.lon
    y1 = line1.start.lat
    x2 = line1.end.lon
    y2 = line1.end.lat
    x3 = line2.start.lon
    y3 = line2.start.lat
    x4 = line2.end.lon
    y4 = line2.end.lat
    denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
    numeA = (x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)
    numeB = (x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)

    if denom == 0:
        if numeA == 0 and numeB == 0:
            return None
        return None

    uA = numeA / denom
    uB = numeB / denom

    if uA >= 0 and uA <= 1 and uB >= 0 and uB <= 1:
        x = x1 + uA * (x2 - x1)
        y = y1 + uA * (y2 - y1)
        # return [x, y]  # x is longitude, y is latitude.
        return Point(lat=y, lon=x)
    return None


# nearest_point_to_lines(p=Point(lat, lon), lines=[mkLine(lat1, lon1, lat2, lon2)])
# def nearest_point_to_lines(p: Point, lines: List[Line]) -> Tuple[Point | None, float]:
#     # First the nearest point to a collection of lines.
#     # Lines is an array if Line()
#     # Returns the point and and distance to it.
#     dist = math.inf
#     for line in lines:
#         d1 = distance(p.lat, p.lon, line.start.lat, line.start.lon)
#         d2 = distance(p.lat, p.lon, line.end.lat, line.end.lon)
#         dl = max(d1, d2) * 2
#         brng = bearing_deg(line.start.lat, line.start.lon, line.end.lat, line.end.lon)
#         brng += 90  # perpendicular
#         lat1,lon1 = destination(p.lat, p.lon, brng, dl)
#         brng -= 180  # perpendicular
#         lat2,lon2 = destination(p.lat, p.lon, brng, dl)
#         perpendicular = Line(Point(lat1,lon1), Point(lat2,lon2))
#         loni, lati = line_intersect(perpendicular, line)
#         if loni is not None and lati is not None:
#             d = distance(p.lat, p.lon, lati, loni)
#             if d < dist:
#                 dist = d
#             return (Point(lati, loni), dist)
#     return (None, dist)


def nearest_point_to_line(p: Point, line: Line) -> Tuple[Point | None, float]:
    d1 = distance(p.lat, p.lon, line.start.lat, line.start.lon)
    d2 = distance(p.lat, p.lon, line.end.lat, line.end.lon)
    dl = max(d1, d2)
    brng = bearing_deg(line.start.lat, line.start.lon, line.end.lat, line.end.lon)
    brng += 90  # perpendicular
    lat1, lon1 = destination(p.lat, p.lon, brng, dl)
    brng -= 180  # perpendicular
    lat2, lon2 = destination(p.lat, p.lon, brng, dl)
    perpendicular = Line(Point(lat1, lon1), Point(lat2, lon2))
    intersect = line_intersect(perpendicular, line)
    return (intersect, distance(p.lat, p.lon, intersect.lat, intersect.lon)) if intersect is not None else (None, 0)


# Cleanup procedure
def min_info(r):
    def empty(c):
        return c is None or c == ""

    le = True
    for c in ["le_latitude_deg", "le_longitude_deg"]:
        if empty(r.get(c)):
            le = False
    if not le:
        for c in ["he_latitude_deg", "he_longitude_deg"]:
            if empty(r.get(c)):
                return False  # no le, no he, not usable
    return not empty(r.get("le_heading_degT")) or not empty(r.get("le_heading_degT"))


NOT_SET = 99999


def float_all(r):
    for c in [
        "id",
        "airport_ref",
        "lighted",
        "closed",
    ]:
        v = r.get(c)
        r[c] = int(v) if v is not None and v != "" else NOT_SET

    for c in [
        "length_ft",
        "width_ft",
        "le_latitude_deg",
        "le_longitude_deg",
        "le_elevation_ft",
        "le_heading_degT",
        "le_displaced_threshold_ft",
        "he_latitude_deg",
        "he_longitude_deg",
        "he_elevation_ft",
        "he_heading_degT",
        "he_displaced_threshold_ft",
    ]:
        v = r.get(c)
        r[c] = float(v) if v is not None and v != "" else NOT_SET
    return Runway(**r)


# ###############################
# Utility
#
# Thresholds
#
ALT_LOW = 150  # above that altitude, we do nothing
SPEED_SLOW = 15  # m/s, below that ground speed, we do nothing
CLOSE_AIRPORT = 40000  # 80km
REPORTING_DELAY = 20  # seconds

# Thresholds may vary with aircraft model...
RATINGS = [
    (150, "Kiss landing"),
    (180, "Smooth landing"),
    (240, "Firm landing"),
    (600, "Uncomfortable landing"),
    (830, "Hard landing, requires inspection"),
    (math.inf, "Severe hard landing, damage likely"),
]


class STATE(StrEnum):
    FAR = "Far"  # flying and above 1000m
    ALT1000M = "at or under ALT1000M"  # [300-1000], must have a short list of runways in sight
    ALT300M = "at or under ALT300M"  # [150-300], must have a target runway
    CLOSE = f"at or under ALT_LOW(~{ALT_LOW}m)"  # monitoring
    ON_RUNWAY = "on runway"  # over or on the runway, monitoring
    GROUNDED = "on the ground, not on runway"  # on the ground, not on runway


class EVENT(StrEnum):
    APPROACH = "Approch"  # over or on the runway
    ENTER_RWY = "Enter runway"  # over or on the runway
    TOUCHDOWN = "Touchdown"
    FRONTGEAR = "Front wheel on ground"
    SLOWDOWN = "Slowed down"  # deceleration over
    EXIT_RWY = "Exit runway"


# ###############################
# Data
#
class DREFS(StrEnum):
    ACF_ICAO = "sim/aircraft/view/acf_ICAO"
    ACF_TAILNUM = "sim/aircraft/view/acf_tailnum"
    FNRML_GEAR = "sim/flightmodel/forces/fnrml_gear"
    ELEVATION = "sim/flightmodel/position/elevation"
    INDICATED_AIRSPEED = "sim/flightmodel/position/indicated_airspeed"
    LATITUDE = "sim/flightmodel/position/latitude"
    LOCAL_VY = "sim/flightmodel/position/local_vy"
    LONGITUDE = "sim/flightmodel/position/longitude"
    Y_AGL = "sim/flightmodel/position/y_agl"
    TIRE_VERTICAL_DEFLECTION_MTR = "sim/flightmodel2/gear/tire_vertical_deflection_mtr"
    TRUE_PHI = "sim/flightmodel2/position/true_phi"
    TRUE_PSI = "sim/flightmodel2/position/true_psi"
    TRUE_THETA = "sim/flightmodel2/position/true_theta"
    TOTAL_FLIGHT_TIME_SEC = "sim/time/total_flight_time_sec"
    # My specifics
    GROUND_TRACK = "sim/cockpit2/gauges/indicators/ground_track_mag_pilot"
    GROUND_SPEED = "sim/flightmodel/position/groundspeed"  # m/s
    # ToLiss specifics
    GEARSTRUTCOMPRESSDIST_M = "AirbusFBW/GearStrutCompressDist_m"
    IASCAPT = "AirbusFBW/IASCapt"
    VLS_VALUE = "toliss_airbus/pfdoutputs/general/VLS_value"


class LandingRatingMonitor:

    def __init__(self, api) -> None:
        self.name = "xgs"  # !
        self.ws = api

        # Runways
        self._all_runways = []
        fn = os.path.join(os.path.dirname(__file__), "runways.csv")
        if os.path.exists(fn):
            with open(fn) as fp:
                self._all_runways = [float_all(r) for r in csv.DictReader(fp) if min_info(r)]
                logger.debug(f"loaded {len(self._all_runways)} runways")
        else:
            logger.warning(f"local airport runway information file not found {fn}")
        self._runways_shortlist = []

        # Target
        self.runway = None
        self.runway_orient = ""  # le/he
        self._runway_ahead = False
        self._on_target_runway = False

        # Monitored datarefs
        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}

        # Remeber dataref values
        self.first: Dict[str, Any] = {}
        self.last: Dict[str, Any] = {}

        self.snapshots: Dict[EVENT, Tuple] = {}

        # Working variables
        self._currently_on_runway = None
        self._state = STATE.GROUNDED
        self._ensure = {}
        self._last_grounded = False  # False = in air
        self._air_time = False
        self._bouncing = False
        self._positions = []
        self._vspeeds = []
        self._display_g = (1.0, 1.0)
        self.result = None

        # Install process
        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)

    def start(self):
        ws.connect()
        ws.wait_connection()
        ws.monitor_datarefs(datarefs=self.datarefs, reason=self.name)
        ws.start()

    @property
    def inited(self) -> bool:
        return len([d for d in self.first if d is not None]) == len(DREFS)

    @property
    def state(self) -> STATE:
        """Monitoring state"""
        return self._state

    @state.setter
    def state(self, state: STATE):
        """Change monitoring state and reports it"""
        if self._state != state:
            self._state = state
            logger.info(f"monitoring state is now {self.state}")

    @property
    def last_grounded(self) -> bool:
        """Monitoring state"""
        return self._last_grounded

    @last_grounded.setter
    def last_grounded(self, grounded: bool):
        """Change monitoring state and reports it"""
        if self._last_grounded != grounded:
            self._last_grounded = grounded
            logger.info(f"grounded {self._last_grounded}")

    def get_dataref_names(self) -> set:
        return DREFS

    def dataref_value(self, dataref: str):
        dref = self.datarefs.get(dataref)
        return dref.value if dref is not None else 0

    def inital_state(self):
        if self.inited:
            return
        for d in DREFS:
            if d not in self.first or self.first.get(d) is None:
                v = self.dataref_value(d)
                if v is not None:
                    self.first[d] = v
                    self.last[d] = v
                    # logger.debug(f"first value for {d}={v}")
        if not self.inited:
            return

        # self.show_values("inited", first=True)

        logger.debug("all dataref values received at least once, determining initial state..")
        # We try to dertermine the over state of the monitor

        self._air_time = True
        self.shortlist_closest_runways()

        if self.dataref_value(DREFS.Y_AGL) > 1000:
            self.state = STATE.CLOSE
            logger.info(f".. state is {self.state}")  # this is the initial value
            return

        self.target_runway_ahead()

        if self.dataref_value(DREFS.Y_AGL) > 300:
            self.state = STATE.ALT1000M
            logger.info(f".. state is {self.state}")  # this is the initial value
            return

        if self.dataref_value(DREFS.Y_AGL) > ALT_LOW:
            self.state = STATE.ALT300M
            logger.info(f".. state is {self.state}")  # this is the initial value
            return

        if self.on_the_ground():
            self.last_grounded = True
            self._air_time = False
            self.shortlist_closest_runways(max_distance=5000)  # 5000m might be short on very large airport like LFPG
            rwy = self.on_runway()
            if rwy is not None:
                orient = self.closest_orient(rwy)
                self.set_target_runway(rwy, orient=orient)
                self.state = STATE.ON_RUNWAY
            else:
                self.state = STATE.GROUNDED
            moving = ", stopped"
            gs = self.dataref_value(DREFS.GROUND_SPEED)
            self._last_fast = gs > SPEED_SLOW
            if gs > 1:
                moving = ", moving"
                if self._last_fast:
                    moving = moving + " fast"
            logger.info(f".. state is {self.state}{moving}")  # this is the initial value
            return

        if self.dataref_value(DREFS.Y_AGL) > 0:
            self.state = STATE.CLOSE
            logger.info(f".. state is {self.state}")  # this is the initial value

    def show_values(self, welcome: str = "", first: bool = False):
        values = self.first if first else self.last
        logger.debug(f"{welcome}\n{'\n'.join([f'{d} = {values[d]}' for d in values])}")

    def on_the_ground(self) -> bool:
        value = self.dataref_value(DREFS.GEARSTRUTCOMPRESSDIST_M)
        if value is not None and type(value) is list:  # fetches whole array
            if value[2] > 0.01:
                # logger.debug(f"gear compress: {value[1] }, {value[2] }")
                return True
            if value[1] > 0.01:
                if EVENT.FRONTGEAR not in self.snapshots:
                    self.snapshot(EVENT.FRONTGEAR)
                return True
        value = self.dataref_value(DREFS.FNRML_GEAR)
        # if value != 0:
        #     logger.debug(f"gear normal: {value}")
        return value != 0

    def ensure_below(self, what: str, threshold: float, value: float, count: int) -> int:
        if what not in self._ensure:
            self._ensure[what] = 0
        if value <= threshold:
            self._ensure[what] = self._ensure[what] + 1
        else:
            self._ensure[what] = 0
        if self._ensure[what] == count:
            return 0
        elif self._ensure[what] > threshold:
            return 1
        return -1

    def dataref_changed(self, dataref, value):
        """Record changes and adjust STATE

        Based on the value of the dataref that has changed we determine a STATE.

        Args:
            dataref ([type]): [description]
            value ([type]): [description]
        """
        self.datarefs[dataref].value = value

        if dataref not in self.get_dataref_names():
            return  # not for me, should never happen

        if not self.inited:
            self.inital_state()
            return

        if dataref == DREFS.Y_AGL:  # altitude AGL

            if value > 1000:
                self._air_time = True
                self.last_grounded = False
                self.state = STATE.FAR
                self.last[dataref] = value
                return

            if 300 < value <= 1000:
                self._air_time = True
                if self.ensure_below("alt1000", threshold=1000, value=value, count=20) == 0:
                    self.state = STATE.ALT1000M
                    if len(self._runways_shortlist) == 0:
                        self.shortlist_closest_runways(report=True)
                        if len(self._runways_shortlist) == 0:
                            logger.warning("below 1000m and no short list")
                        else:
                            s = set([d.airport_ident for d in self._runways_shortlist])
                            logger.info(f"airport short list {', '.join(s)}")

            if ALT_LOW < value <= 300:
                self.last_grounded = False
                self._air_time = True
                if self.ensure_below("alt300", threshold=300, value=value, count=20) == 0:
                    self.state = STATE.ALT300M
                    self.shortlist_closest_runways(max_distance=10000)
                    if len(self._runways_shortlist) == 0:
                        logger.warning("below 300m and no short list")
                    self.target_runway_ahead(ahead=10000)
                    if self.runway is None:
                        logger.warning("below 300m and no target runway")

            if value <= ALT_LOW and not self.on_the_ground():
                self._air_time = True
                if self.ensure_below("altlow", threshold=ALT_LOW, value=value, count=20) == 0:
                    if EVENT.APPROACH not in self.snapshots:
                        self.snapshot(EVENT.APPROACH)
                    self.state = STATE.CLOSE
                    self.shortlist_closest_runways()
                    if len(self._runways_shortlist) == 0:
                        logger.warning(f"below {ALT_LOW}m and no short list")
                    self.target_runway_ahead(ahead=10000)
                    if self.runway is None:
                        logger.warning(f"below {ALT_LOW}m and no target runway")
                    logger.info(f"below {ALT_LOW}m, monitoring started..")

            self.last[dataref] = value
            return

        on_runway = False
        if dataref in [DREFS.LATITUDE, DREFS.LONGITUDE]:
            on_runway = self.on_runway()

        if self.state == STATE.CLOSE and dataref in [DREFS.LATITUDE, DREFS.LONGITUDE]:
            if not self._on_target_runway and self.on_target_runway():  # compare old and new value, on_target_runway will set _on_target_runway to latest eval
                self.snapshot(EVENT.ENTER_RWY)  # ground speed less than 50km/h, brake is ok, we can exit runway
                self.state = STATE.ON_RUNWAY

        if self.state == STATE.ON_RUNWAY and dataref in [DREFS.LATITUDE, DREFS.LONGITUDE]:
            if self._on_target_runway and not self.on_target_runway():  # compare old and new value, on_target_runway will set _on_target_runway to latest eval
                self.snapshot(EVENT.EXIT_RWY)  # ground speed less than 50km/h, brake is ok, we can exit runway
                logger.info("exit target runway")
                if self.result is None:
                    result = threading.Timer(REPORTING_DELAY, self.report)  # give time to further slow down in case of speedy exit
                    result.start()
                    logger.info("preparing report..")
                if EVENT.SLOWDOWN in self.snapshots:
                    logger.info("..monitoring ended")
                if self.on_the_ground():
                    self.state = STATE.GROUNDED
                else:
                    # should check alt and ground speed
                    self.state = STATE.CLOSE  # go-around?

        if dataref == DREFS.GROUND_SPEED:  # position
            if self.last_grounded and self._last_fast:
                if value < SPEED_SLOW and not EVENT.SLOWDOWN in self.snapshots:
                    self.snapshot(EVENT.SLOWDOWN)  # ground speed less than 50km/h, brake is ok, we can exit runway
                    self._last_fast = False
                    self.last[dataref] = value
                    logger.info("deceleration completed")
                    if self.result is None:
                        result = threading.Timer(REPORTING_DELAY, self.report)  # give time to further slow down in case of speedy exit
                        result.start()
                        logger.info("preparing report..")
                    if EVENT.EXIT_RWY in self.snapshots:
                        logger.info("..monitoring ended")
            self._last_fast = value > SPEED_SLOW

        if self.state in [STATE.CLOSE, STATE.ON_RUNWAY]:
            self.monitor_landing()

        # Save new value as last one
        self.last[dataref] = value

    def monitor_landing(self):
        """Based on STATE and dataref values we monitor the landing parameters"""
        self.record_vspeed()
        self.record_position()
        self.on_target_runway()

        grounded = self.on_the_ground()
        if grounded and not self.last_grounded:  # Touched down
            self.snapshot(EVENT.TOUCHDOWN)
            self.last_grounded = True
        elif self.last_grounded and not grounded:
            if not self._bouncing:
                logger.debug("bouncing detected")
                self._bouncing = True

    def closest_orient(self, rwy: Runway) -> str:
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)
        dle = distance(lat, lon, rwy.le_latitude_deg, rwy.le_longitude_deg)
        dhe = distance(lat, lon, rwy.he_latitude_deg, rwy.he_longitude_deg)
        return "le" if dle <= dhe else "he"

    def record_position(self):
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)
        alt = self.dataref_value(DREFS.Y_AGL)
        self._positions.append((now(), lat, lon, alt))

    def record_vspeed(self):
        vs = self.dataref_value(DREFS.LOCAL_VY)
        tt = self.dataref_value(DREFS.TRUE_THETA)
        val = vs * math.cos(tt * 0.0174533)  # vs projected vertically
        ts = now()

        if len(self._vspeeds) < 2:
            self._vspeeds.append([ts, vs, tt, val, 1, 1])
            return

        # compute G (as derivative of vertical speed)
        vs0 = val
        vs1 = self._vspeeds[-1][3]
        vs2 = self._vspeeds[-2][3]
        t10 = (self._vspeeds[-1][0] - ts).total_seconds()
        t20 = (self._vspeeds[-2][0] - ts).total_seconds()
        t21 = (self._vspeeds[-2][0] - self._vspeeds[-1][0]).total_seconds()
        g = 1.0 + (-vs2 * t21 / (t10 * t20) + vs1 / t10 - vs1 / t21 + vs0 * t10 / (t21 * t20)) / G

        # compute G low pass filtered
        g_lp = 1
        LP = 5
        if len(self._vspeeds) > (LP + 1):
            total = 0
            for i in range(2, LP+1):
                total = total + self._vspeeds[-i][4] * (self._vspeeds[-i + 1][0] - self._vspeeds[-i][0]).total_seconds()
            g_lp = total / (self._vspeeds[-1][0] - self._vspeeds[-LP][0]).total_seconds()

        # 0=timestamp, 1=vertical speed, 2=true_theta, 3=value, 4=g, 5=g low pass
        self._vspeeds.append([ts, vs, tt, val, g, g_lp])

        if 0 < self.since_touchdown < 10:  # keep min and max smoothed values
            self._display_g = (min(self._display_g[0], g_lp), max(self._display_g[1], g_lp))

        # if self.dataref_value(DREFS.Y_AGL) < 10 and self.dataref_value(DREFS.GROUND_SPEED) > 60:
        #     print(f"{self._vspeeds[-1][0].strftime('%S.%f')}, vs={round(vs,2)} g={round(g, 2)} lpg={round(g_lp, 2)}")

    def on_target_runway(self) -> bool:
        if self.runway is None:
            logger.warning("no target runway")
            return False
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)
        inside = self.runway.inside(lat, lon)

        if not self._on_target_runway and inside:
            logger.debug(f"entering target runway {self.runway}")
        elif self._on_target_runway and not inside:
            logger.debug(f"exiting target runway {self._currently_on_runway}")

        self._on_target_runway = inside
        return self._on_target_runway

    def snapshot(self, event: EVENT):
        if event in self.snapshots:
            logger.warning(f"snapshot {event} already taken")
            return
        distthr = -1
        logger.debug(f"snapshot {event} around index {len(self._vspeeds)}, ts={now().isoformat()}")
        if self.runway is not None:
            lat = self.dataref_value(DREFS.LATITUDE)
            lon = self.dataref_value(DREFS.LONGITUDE)
            rlat = 0
            rlon = 0
            if self.runway_orient == "he":
                rlat = self.runway.he_latitude_deg
                rlon = self.runway.he_longitude_deg
            else:
                rlat = self.runway.le_latitude_deg
                rlon = self.runway.le_longitude_deg
            distthr = distance(lat, lon, rlat, rlon)
        vspeed = self._vspeeds[-1] if len(self._vspeeds) > 0 else None
        self.snapshots[event] = (now(), distthr, {d: self.dataref_value(d) for d in DREFS}, vspeed)
        logger.debug(f"snapshot {event} taken")

    @property
    def since_touchdown(self) -> float:
        if EVENT.TOUCHDOWN not in self.snapshots:
            return -1
        return (now() - self.snapshots[EVENT.TOUCHDOWN][0]).seconds

    def shortlist_closest_runways(self, max_distance: float = CLOSE_AIRPORT, report: bool = False):
        # Preselect all airports in the vicinity of the aircraft (out of 44000 airports)
        # Short list is updated every ~10 minutes when aircraft is below 6000ft/2km
        # Finer scans in the short list (~20 airports, ~70 runways) will occur very fast.
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)

        def dist(rwy) -> bool:
            close = False
            if rwy.le_latitude_deg != NOT_SET:
                d = distance(lat, lon, rwy.le_latitude_deg, rwy.le_longitude_deg)
                close = d < max_distance
            if not close and rwy.he_latitude_deg != NOT_SET:
                d = distance(lat, lon, rwy.he_latitude_deg, rwy.he_longitude_deg)
                close = d < max_distance
            return close

        self._runways_shortlist = [r for r in self._all_runways if dist(r)]
        if report:
            logger.info(f"short-listed {len(self._runways_shortlist)} runways within {max_distance}m")
        logger.debug([str(r) for r in self._runways_shortlist])

    def set_target_runway(self, runway: Runway, orient: str, distance: float | None = None):
        self.runway = runway
        self.runway_orient = orient
        dist = ""
        if distance is not None:
            dist = f" at {round(distance)}m"
        logger.info(f"new target runway {runway.name(orient=orient)}{dist}")

    def target_runway_ahead(self, adjust: bool = True, ahead: float = 20000.0):
        # To be run perriodically
        # Make a bounding box of length ahead (meters) and 10% of ahead wide, in direction of tracking.
        # Threshold should be in bbox.
        #
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)
        tracking = self.dataref_value(DREFS.GROUND_TRACK)
        ahead_bbox = []
        halfwidth = ahead / 20
        latb, lonb = destination(lat, lon, tracking + 90, halfwidth)
        ahead_bbox.append((latb, lonb))
        latb, lonb = destination(lat, lon, tracking - 90, halfwidth)
        ahead_bbox.append((latb, lonb))
        lat2, lon2 = destination(lat, lon, tracking, ahead)
        latb, lonb = destination(lat2, lon2, tracking - 90, halfwidth)
        ahead_bbox.append((latb, lonb))
        latb, lonb = destination(lat2, lon2, tracking + 90, halfwidth)
        ahead_bbox.append((latb, lonb))
        ahead_bbox.append(ahead_bbox[0])

        closest_rwy = None
        closest_dist = math.inf
        orient = ""
        ahead = False
        for runway in self._runways_shortlist:
            if runway.le_latitude_deg != NOT_SET:
                d = distance(lat, lon, runway.le_latitude_deg, runway.le_longitude_deg)
                ahead = point_in_polygon((runway.le_latitude_deg, runway.le_longitude_deg), ahead_bbox)
                if d < closest_dist:
                    closest_dist = d
                    closest_rwy = runway
                    orient = "le"
                # logger.debug(f"{runway}({orient}) at {round(d)}m, ahead={ahead}")
            if runway.he_latitude_deg != NOT_SET:
                d = distance(lat, lon, runway.he_latitude_deg, runway.he_longitude_deg)
                ahead = point_in_polygon((runway.he_latitude_deg, runway.he_longitude_deg), ahead_bbox)
                if d < closest_dist:
                    closest_dist = d
                    closest_rwy = runway
                    orient = "he"
                # logger.debug(f"{runway}({orient}) at {round(d)}m, ahead={ahead}")
        if closest_rwy is not None:
            if (self.runway is None or adjust) and self.runway != closest_rwy:
                self.set_target_runway(runway=closest_rwy, orient=orient, distance=closest_dist)
                if ahead:
                    logger.debug(f"{self.runway} is ahead")
                else:
                    logger.warning(f"target runway threshold {self.runway}({orient}) is not ahead")
            else:
                if self.runway is None and adjust:
                    logger.warning("no target runway threshold")
        else:
            if adjust:
                logger.warning(f"no target runway threshold found in list {[str(r) for r in self._runways_shortlist]}")

    def on_runway(self) -> Runway | None:
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)
        rwys = list(filter(lambda r: r.inside(lat, lon), self._runways_shortlist))

        if len(rwys) > 0:
            if self._currently_on_runway is None:
                self._currently_on_runway = rwys[0]
                logger.info(f"enter runway {self._currently_on_runway}")
            elif self._currently_on_runway not in rwys:
                logger.info(f"exit runway {self._currently_on_runway}")
                self._currently_on_runway = None
            if len(rwys) > 1:
                logger.warning(f"currently on more than one runway ({[str(r) for r in rwys]}), {rwys[0]} returned")
                if self._currently_on_runway is None:
                    self._currently_on_runway = rwys[0]
                    logger.info(f"enter runway {self._currently_on_runway}")
            return rwys[0]

        # not on any runway...
        if self._currently_on_runway is not None:
            logger.info(f"exit runway {self._currently_on_runway}")
            self._currently_on_runway = None
        return None

    def report(self):
        def to_kmh(kt: float) -> float:
            return round(kt * 1.852, 1)

        def to_ms(kt: float) -> float:
            return round(kt * 0.5144444, 1)

        def to_kt(ms: float) -> float:
            return round(ms * 1.943844, 1)

        def to_fpm(ms: float) -> float:
            return round(ms * MS_2_FPM)

        def snap_dataref_value(s, dref: DREFS):
            return s[2][dref]

        logger.info("\n")
        logger.info("--- LANDING PERFORMANCE REPORT")

        if not self._air_time:
            logger.info("no air time.")
            logger.info("--- END REPORT\n")
            return

        if self.runway is None:
            logger.info("no target runway.")
            logger.info("--- END REPORT\n")
            return

        # Approach speed
        snapa = self.snapshots.get(EVENT.APPROACH)
        if snapa is not None:
            alt = snap_dataref_value(snapa, DREFS.Y_AGL)
            speed = snap_dataref_value(snapa, DREFS.INDICATED_AIRSPEED)
            logger.info(
                f"Approach speed at {round(snapa[1])}m from runway: alt={round(alt)}, speed={round(speed, 1)}kt, {to_kmh(speed)}km/h, {to_ms(speed)}m/s"
            )
        else:
            logger.info("no approach information")

        # Alt/speed over runway edge
        snapi = self.snapshots.get(EVENT.ENTER_RWY)
        if snapi is not None:
            alt = snap_dataref_value(snapi, DREFS.Y_AGL)
            speed = snap_dataref_value(snapi, DREFS.INDICATED_AIRSPEED)
            logger.info(
                f"Approach speed entering runway ({round(snapi[1])}m from edge): alt={round(alt)}, speed={round(speed, 1)}kt, {to_kmh(speed)}km/h, {to_ms(speed)}m/s"
            )
        else:
            logger.info("no fly over runway, no target runway entry")

        # Alt/speed on touch down
        snapt = self.snapshots.get(EVENT.TOUCHDOWN)
        d0 = 0
        t0 = 0
        if snapt is not None:
            alt = snap_dataref_value(snapt, DREFS.Y_AGL)
            speed = snap_dataref_value(snapt, DREFS.INDICATED_AIRSPEED)
            t0 = snapt[0]
            d0 = snapt[1]
            logger.info(
                f"Touchdown at {snapt[0].strftime('%H:%M:%S')}Z, {round(snapt[1])}m from runway edge: alt={round(alt)}, speed={round(speed, 1)}kt, {to_kmh(speed)}km/h, {to_ms(speed)}m/s"
            )

            dist = ""
            lat, log, alt, hdg, disp = self.runway.values(orient=self.runway_orient)
            if disp != NOT_SET:
                disp_lat, disp_lon = destination(lat, lon, brngDeg=hdg, d=disp)
                d = distance(lat, lon, disp_lat, disp_lon)
                dist = f" at {round(d)}m from threshold"

            offcenter = ""
            acf_lat = snap_dataref_value(snapt, DREFS.LATITUDE)
            acf_lon = snap_dataref_value(snapt, DREFS.LONGITUDE)
            middle = Line(
                start=Point(self.runway.le_latitude_deg, self.runway.le_longitude_deg), end=Point(self.runway.he_latitude_deg, self.runway.he_longitude_deg)
            )

            point, distoff = nearest_point_to_line(Point(acf_lat, acf_lon), middle)
            offcenter = f", {round(distoff,1)}m off-center line"
            if self.runway.inside(acf_lat, acf_lon):
                logger.info(f"Touchdown on runway{dist}{offcenter}")
            #
            # deviation from center line
            #
            vspeed = snapt[3]  # 0=timestamp, 1=vertical speed, 2=true_theta, 3=value, 4=g, 5=g low pass
            if vspeed is not None and len(vspeed) > 5:
                vs = abs(vspeed[1])
                vs_fpm = to_fpm(vs)
                i = 0
                while abs(vs_fpm) > RATINGS[i][0] and i < len(RATINGS):
                    i = i + 1
                logger.info(f"{RATINGS[i][1]}")
                logger.info(f"Vy: {vs_fpm} fpm, {round(vs, 2)} m/s, 𝛉 {round(vspeed[2], 2)}°, 𝛗 {round(vspeed[3], 1)}°")
                logger.info(f"G:  {round(vspeed[4], 2)}, smoothed: {round(vspeed[5], 2)}")
                logger.info(f"G display: {self._display_g}")
        else:
            logger.info("no touch down detected")

        snapf = self.snapshots.get(EVENT.FRONTGEAR)
        if snapf is not None:  # this is "optional", and for ToLiss aircrafts mainly
            speed = snap_dataref_value(snapf, DREFS.INDICATED_AIRSPEED)
            logger.info(f"Front wheel touchdown {round(snapf[1])}m from runway edge: speed={round(speed, 1)}kt, {to_kmh(speed)}km/h, {to_ms(speed)}m/s")

        snaps = self.snapshots.get(EVENT.SLOWDOWN)
        if snaps is not None:
            speed = snap_dataref_value(snaps, DREFS.GROUND_SPEED)
            breaking = ""
            if snapt is not None:
                d1 = snaps[1] - d0
                breaking = f", braking distance {round(d1)}m"
            logger.info(
                f"Slow speed ({SPEED_SLOW}m/s) at {round(snaps[1])}m from runway edge: speed={to_kt(speed)}kt, {round(speed, 1)}m/s{breaking}"
            )
        else:
            logger.info(f"no deceleration to slower speed {SPEED_SLOW}m/s detected")

        snape = self.snapshots.get(EVENT.EXIT_RWY)
        if snape is not None:
            speed = snap_dataref_value(snape, DREFS.GROUND_SPEED)
            rwybusy = ""
            if snapt is not None:
                t1 = (snape[0] - t0).seconds
                rwybusy = f", on/over runway for {round(t1)}secs"
            logger.info(f"Exit runway at {snape[0].strftime('%H:%M:%S')}Z{rwybusy}")
            alt = snap_dataref_value(snape, DREFS.Y_AGL)
            gs = snap_dataref_value(snape, DREFS.GROUND_SPEED)
            if alt > 5 and gs > 50:
                logger.info(f"possible runway fly over ({'with' if snapt is not None else 'without'} touch down)")
        else:
            logger.info("no exit of runway detected")

        logger.info("--- END REPORT\n")

        self.save()
        self.reset()

    def save(self):
        with open("vs.csv", "w") as fp:
            i = 0
            for f in self._vspeeds:
                print(f"{i},{f[0].timestamp()},"+','.join([str(v) for v in f[1:]]), file=fp)
                i = i + 1
        logger.info("vspeeds written in vs.csv")

        with open("path.kml", "w") as fp:
            fp.write(to_kml(self._positions, airport={"lat": self.runway.he_latitude_deg, "lon": self.runway.he_longitude_deg}))
        logger.info("flight path in path.kml")

        logger.info("monitor state saved")

    def reset(self):
        self.first = {}
        self.last = {}
        self.snapshots = {}
        # Working variables
        self._currently_on_runway = None
        self._state = STATE.GROUNDED
        self._ensure = {}
        self._last_grounded = False  # False = in air
        self._air_time = False
        self._bouncing = False
        self._positions = []
        self._vspeeds = []
        self._display_g = (1.0, 1.0)
        logger.info("monitor was reset")

    def terminate(self):
        ws.unmonitor_datarefs(datarefs=self.datarefs, reason=self.name)
        self.ws.disconnect()


if __name__ == "__main__":
    ws = xpwebapi.ws_api()
    xgs = LandingRatingMonitor(ws)
    try:
        xgs.start()
    except KeyboardInterrupt:
        logger.warning("terminating..")
        xgs.terminate()
        logger.warning("..terminated")
