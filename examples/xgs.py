"""Landing Rating

Extrernal (to X-Plane) application to detect OOOI ACARS message changes and generate appropriate message.
"""

import logging
import os
import sys
import math
import csv
import threading
from enum import StrEnum
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, List, Any
from dataclasses import dataclass

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi

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


def mkLine(lat1: float, lon1: float, lat2: float, lon2: float):
    return Line(Point(lat1, lon1), Point(lat2, lon2))


def line_intersect(line1: Line, line2: Line) -> Tuple[float, float] | None:
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
        return (y, x)
    return None


# nearest_point_to_lines(p=Point(lat, lon), lines=[mkLine(lat1, lon1, lat2, lon2)])
def nearest_point_to_lines(p: Point, lines: List[Line]) -> Tuple[Tuple[float, float] | None, float]:
    # First the nearest point to a collection of lines.
    # Lines is an array if Line()
    # Returns the point and and distance to it.
    nearest = None
    dist = math.inf
    for line in lines:
        d1 = distance(p, line.start)
        d2 = distance(p, line.end)
        dl = max(d1, d2)
        brng = bearing(line.start, line.end)
        brng += 90  # perpendicular
        p1 = destination(p, brng, dl)
        brng -= 180  # perpendicular
        p2 = destination(p, brng, dl)
        perpendicular = Line(p1, p2)
        intersect = line_intersect(perpendicular, line)
        if intersect:
            d = distance(p, intersect)
            if d < dist:
                dist = d
                nearest = intersect
    return [nearest, distance]


# Utility
#
class dotdict(dict):
    """dot.notation access to dictionary attributes"""

    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


class STATES(StrEnum):
    FAR = "Far"
    FT3000 = "At or under FT3000"
    FT1000 = "At or under FT1000"
    LOW = "At or under ALT_FAR(~150m)"
    OVERRWY = "Over the runway"
    TOUCHDOWN = "Touchdown"
    FRONTWHEEL = "Front wheel on ground"
    EXITRWY = "Exit runway on ground"
    EXIT = "No longer over runway"


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


# ###############################
# Thresholds
#
ALT_FAR = 150  # above that altitude, we do nothing
CLOSE_AIRPORT = 80000  # 80km
# Thresholds may vary with aircraft model...
RATINGS = [
    (150, "Kiss landing"),
    (180, "Smooth landing"),
    (240, "Firm landing"),
    (600, "Uncomfortable landing"),
    (830, "Hard landing, requires inspection"),
    (math.inf, "Severe hard landing, damage likely"),
]


def all_info(r):
    def empty(c):
        return c is None or c == ""

    for c in ["le_latitude_deg", "le_longitude_deg", "he_latitude_deg", "he_longitude_deg"]:
        if empty(r.get(c)):
            return False
    return not empty(r.get("le_heading_degT")) or not empty(r.get("le_heading_degT"))


def float_all(r):
    for c in [
        "le_latitude_deg",
        "le_longitude_deg",
        "he_latitude_deg",
        "he_longitude_deg",
        "width_ft",
        "le_elevation_ft",
        "le_heading_degT",
        "le_displaced_threshold_ft",
        "he_elevation_ft",
        "he_heading_degT",
        "he_displaced_threshold_ft",
    ]:
        v = r.get(c)
        if v is not None and v != "":
            r[c] = float(v)
    return r


class LandingRatingMonitor:

    def __init__(self, api) -> None:
        self.name = "xgs"  # !
        self.ws = api

        # All airports
        self._all_runways = []
        fn = os.path.join(os.path.dirname(__file__), "runways.csv")
        if os.path.exists(fn):
            with open(fn) as fp:
                self._all_runways = [float_all(r) for r in csv.DictReader(fp) if all_info(r)]
                logger.debug(f"loaded {len(self._all_runways)} runways")
        else:
            logger.warning(f"local airport runway information file not found {fn}")
        self._runways_shortlist = []

        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}

        self.eta: datetime | None = None

        self.first: Dict[str, Any] = {}
        self.last: Dict[str, Any] = {}
        self.landing_data = dotdict()

        self.airport = {}
        self.runway = {}
        self.runway_orient = ""  # le/he
        self.runway_ahead = False
        self.target = []  # lat, log of closest threshold
        self.runway_bbox = []
        self.runway_bbox_red = []
        self._last_inout = False  # False = Out
        self._last_grounded = False  # False = in air
        self._positions = []

        self.speed_trend = 0
        self.alt_trend = 0

        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)
        self.list_lock = threading.RLock()

    def start(self):
        ws.connect()
        ws.wait_connection()
        ws.monitor_datarefs(datarefs=self.datarefs, reason=self.name)
        ws.start()

    @property
    def inited(self) -> bool:
        return len([d for d in self.first if d is not None]) == len(DREFS)

    def set_eta(self, eta: datetime):
        # when we get one...
        self.eta = eta
        logger.info(f"eta {self.eta.replace(second=0, microsecond=0)}")

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
                    logger.debug(f"first value for {d}={v}")
        if not self.inited:
            return
        # Init some landing data
        self.landing_data["nose_wheel_td_dist"] = 0.0
        self.landing_data["toliss_vls"] = 0.0

        logger.debug("all dataref values received at least once, determining initial state..")
        self.show_values("inited", first=True)

    def show_values(self, welcome: str = "", first: bool = False):
        values = self.first if first else self.last
        logger.debug(f"{welcome}\n{'\n'.join([f'{d} = {values[d]}' for d in values])}")

    def on_the_ground(self) -> bool:
        value = self.dataref_value(DREFS.GEARSTRUTCOMPRESSDIST_M)
        if value is not None and type(value) is list:  # fetches whole array
            if value[1] > 0.01 or value[2] > 0.01:
                return True
        value = self.dataref_value(DREFS.FNRML_GEAR)
        return value != 0

    def dataref_changed(self, dataref, value):
        def ensure_restricted_list():
            if self.runway is None:  # a bit late to do it now, but we need it...
                self.target_runway_ahead()

        self.datarefs[dataref].value = value

        if dataref not in self.get_dataref_names():
            return  # not for me, should never happen

        if not self.inited:
            self.inital_state()
            return

        if len(self._runways_shortlist) == 0:
            self.closest_airport_list()

        if dataref == DREFS.Y_AGL:  # altitude AGL

            # DEBUG
            ensure_restricted_list()  # a bit late to do it now, but we need it...
            self.target_runway_ahead(ahead=10000)

            if value > 1000:
                self.state = STATES.FT3000
                self.last[dataref] = value
                ensure_restricted_list()  # a bit late to do it now, but we need it...
                return
            if value > 300:
                self.state = STATES.FT1000
                self.last[dataref] = value
                ensure_restricted_list()  # a bit late to do it now, but we need it...
                return
            if value > ALT_FAR:
                self.last[dataref] = value
                return
            self.state = STATES.LOW
            ensure_restricted_list()  # a bit late to do it now, but we need it...
            self.target_runway_ahead(ahead=10000)
            self.record_vspeed()
            grounded = self.on_the_ground()
            if not self._last_grounded and grounded:  # Touched down
                self.last[dataref] = value
                self.snapshot("touchdown")
                self._last_grounded = grounded
                logger.debug("touchdown")

        if dataref in [DREFS.LATITUDE, DREFS.LONGITUDE]:  # position
            self.record_position()

        if dataref == DREFS.GROUND_SPEED:  # position
            if self._last_grounded:
                if value < 15:  # 15 m/s ~= 54 km/h ~= 30knt
                    self.last[dataref] = value
                    self.snapshot("less40")  # ground speed less than 50km/h, brake is ok, we can exit runway

        # Save new value as last one
        self.last[dataref] = value

    def record_position(self):
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)
        alt = self.dataref_value(DREFS.Y_AGL)
        self._positions.append((now(), lat, lon, alt))

    def record_vspeed(self):
        vs = self.dataref_value(DREFS.LOCAL_VY)
        tt = self.dataref_value(DREFS.TRUE_THETA)
        val = vs * math.cos(tt * 0.0174533)
        ts = now()

        if len(self._vpseeds) < 2:
            self._vpseeds.append([ts, vs, tt, val, 1, 1])

        # TODO: May be we can just record raw data here and compute G/G(LP) after?
        #
        # compute G (as derivative of vertical speed)
        h10 = self._vpseeds[-1][0] - ts
        h20 = self._vpseeds[-2][0] - ts
        h21 = self._vpseeds[-2][0] - self._vpseeds[-1][0]
        p2 = val
        p1 = self._vpseeds[-1][3]
        p0 = self._vpseeds[-2][3]
        g = 1.0 + (-p0 * h21 / (h10 * h20) + p1 / h10 - p1 / h21 + p2 * h10 / (h21 * h20)) / G

        self._vpseeds[-1][4] = g
        g_lp = 1
        self._vpseeds.append([ts, vs, tt, val, g, g_lp])
        # compute G low pass filtered
        LP = 5
        if len(self._vpseeds) > LP:
            total = 0
            for i in range(2, LP):  # LP+1?
                total = total + self._vpseeds[-i][3] * (self._vpseeds[-i + 1][0] - self._vpseeds[-i][0])
            g_lp = total / (self._vpseeds[-LP][0] - self._vpseeds[-1][0])
            self._vpseeds[-2][5] = g_lp
        logger.debug(f"{self._vpseeds[-1]}, g={g}, g_lp={g_lp}")

    def record(self, name: str, value):
        self.landing_data[name] = value

    def snapshot(self, name: str):
        distthr = -1
        if self.runway is not None:
            lat = self.datarefs.get(DREFS.LATITUDE)
            lon = self.datarefs.get(DREFS.LONGITUDE)
            distthr = distance(lat, lon, self.runway[f"{self.runway_orient}_latitude_deg"], self.runway[f"{self.runway_orient}_longitude_deg"])
        self.snapshot.append((name, now(), distthr, {d: self.dataref_value(d) for d in DREFS}))

    def closest_airport_list(self):
        # Preselect all airports in the vicinity of the aircraft (out of 44000 airports)
        # Short list is updated every ~10 minutes when aircraft is below 6000ft/2km
        # Finer scans in the short list (~20 airports, ~70 runways) will occur very fast.
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)

        def dist(rwy) -> bool:
            close = False
            if "le_latitude_deg" in rwy and rwy["le_latitude_deg"] != "":
                d = distance(lat, lon, rwy["le_latitude_deg"], rwy["le_longitude_deg"])
                close = d < CLOSE_AIRPORT
            if not close and "he_latitude_deg" in rwy and rwy["he_latitude_deg"] != "":
                d = distance(lat, lon, rwy["he_latitude_deg"], rwy["he_longitude_deg"])
                close = d < CLOSE_AIRPORT
            return close

        with self.list_lock:
            self._runways_shortlist = [r for r in self._all_runways if dist(r)]
        logger.debug(f"loaded {len(self._runways_shortlist)} runways within {CLOSE_AIRPORT}m")
        logger.debug([f'{r["airport_ident"]}:{r["le_ident"]}/{r["he_ident"]}' for r in self._runways_shortlist])

    def target_runway_ahead(self, adjust: bool = True, ahead: float = 20000.0):
        # To be run perriodically
        # Make a bounding box of length ahead (meters) and 10% of ahead wide, in direction of tracking.
        # Threshold should be in bbox.
        #
        lat = self.dataref_value(DREFS.LATITUDE)
        lon = self.dataref_value(DREFS.LONGITUDE)
        tracking = self.dataref_value(DREFS.GROUND_TRACK)
        ahead_bbox = []
        halfwidth = ahead / 40
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
        pos = None
        with self.list_lock:
            for runway in self._runways_shortlist:
                if "le_latitude_deg" in runway:
                    d = distance(lat, lon, runway["le_latitude_deg"], runway["le_longitude_deg"])
                    if d < closest_dist:
                        closest_dist = d
                        closest_rwy = runway
                        pos = "le"
                if "he_latitude_deg" in runway:
                    d = distance(lat, lon, runway["he_latitude_deg"], runway["he_longitude_deg"])
                    if d < closest_dist:
                        closest_dist = d
                        closest_rwy = runway
                        pos = "he"
        if closest_rwy is not None:
            inbbox = point_in_polygon((runway[f"{pos}_latitude_deg"], runway[f"{pos}_longitude_deg"]), ahead_bbox)
            logger.debug(
                f"closest_rwy runway threshold at {round(closest_dist)}m ({closest_rwy['airport_ident']}, {closest_rwy['le_ident']}/{closest_rwy['he_ident']}, {pos}, ahead={inbbox})"
            )
            d = distance(closest_rwy["le_latitude_deg"], closest_rwy["le_longitude_deg"], closest_rwy["he_latitude_deg"], closest_rwy["he_longitude_deg"])
            logger.debug(f"runway length {round(d)}m")

            logger.info("new target runway threshold adjusted")
            if self.runway is None or adjust:
                self.runway = closest_rwy
                self.runway_orient = pos
                self.runway_ahead = inbbox
                self.mk_bbox()
            else:
                logger.warning("new target runway threshold not adjusted")
        else:
            logger.warning(f"no target runway threshold found in list {self.closest_airport_list}")

    def mk_bbox(self):
        def val(instr: str) -> float:
            return 0 if instr == "" else float(instr)

        runway = self.runway
        lat1, lon1 = runway["le_latitude_deg"], runway["le_longitude_deg"]
        lat2, lon2 = runway["he_latitude_deg"], runway["he_longitude_deg"]
        brgn = bearing_deg(lat1, lon1, lat2, lon2)  # bearing 1 -> 2
        halfwidth = (runway["width_ft"] / M_2_FT) / 2
        self.runway_bbox = []
        lat, lon = destination(lat1, lon1, brgn + 90, halfwidth)
        self.runway_bbox.append((lat, lon))
        lat, lon = destination(lat1, lon1, brgn - 90, halfwidth)
        self.runway_bbox.append((lat, lon))
        lat, lon = destination(lat2, lon2, brgn - 90, halfwidth)
        self.runway_bbox.append((lat, lon))
        lat, lon = destination(lat2, lon2, brgn + 90, halfwidth)
        self.runway_bbox.append((lat, lon))
        self.runway_bbox.append(self.runway_bbox[0])
        # could make a reduced bbox with le_displaced_threshold_ft, he_displaced_threshold_ft
        if val(runway["le_displaced_threshold_ft"]) > 0:
            lat1, lon1 = destination(lat1, lon1, brgn, runway["le_displaced_threshold_ft"])
        if val(runway["he_displaced_threshold_ft"]) > 0:
            lat2, lon2 = destination(lat2, lon2, -brgn, runway["he_displaced_threshold_ft"])
        self.runway_bbox_red = []
        lat, lon = destination(lat1, lon1, brgn + 90, halfwidth)
        self.runway_bbox_red.append((lat, lon))
        lat, lon = destination(lat1, lon1, brgn - 90, halfwidth)
        self.runway_bbox_red.append((lat, lon))
        lat, lon = destination(lat2, lon2, brgn - 90, halfwidth)
        self.runway_bbox_red.append((lat, lon))
        lat, lon = destination(lat2, lon2, brgn + 90, halfwidth)
        self.runway_bbox_red.append((lat, lon))
        self.runway_bbox_red.append(self.runway_bbox_red[0])

    def on_runway(self, lat: float, lon: float, reduced: bool = False) -> bool:
        if self.runway_bbox is not None and len(self.runway_bbox) == 4:
            return point_in_polygon(lat, lon, self.runway_bbox_red) if reduced else point_in_polygon(lat, lon, self.runway_bbox)
        logger.warning("no bounding box")
        return False

    def runway_details(self):
        if self.runway is None:
            logger.warning("no runway")
            return
        # length, width, material, orientation
        logger.info(self.runway)

    def touchdown_position(self):
        # Relative to
        lat = 1
        lon = 1
        if not self.on_runway(lat, lon):
            logger.warning("not on runway")
            # print report off-runway
            touchdown_dist = 0  # from target threshold
            offcenter = 0  # meters, negative for left side of runway centerline
            return
        # 1 Relative to threshold, runway length, etc.
        alt_on_threshold = 0
        touchdown_dist = 0
        front_wheel_dist = -1  # if available
        less40_dist = 0  # less than 40km/h, landing track remaining

        # 2 Lateral: Relative to center line
        offcenter = 0  # meters, negative for left side of runway centerline

        # tracking vs. runway orientation
        tracking = 0

    def distance_to_thresholds(self) -> Tuple[float, float]:
        if self.runway is None:
            return (-1, -1)
        lat = self.datarefs.get(DREFS.LATITUDE)
        lon = self.datarefs.get(DREFS.LONGITUDE)
        runway = self.runway
        dl = distance(lat, lon, runway["le_latitude_deg"], runway["le_longitude_deg"])
        dh = distance(lat, lon, runway["he_latitude_deg"], runway["he_longitude_deg"])
        return (dl, dh)

    def report(self):
        SEP = ",   "  # " / "
        landing = self.landing_data

        logger.info(f"Vy: {landing.vspeed * MS_2_FPM:.0f} fpm{SEP}{landing.vspeed:.2f} m/s{SEP}𝛉 {landing.theta:.1f}°{SEP}𝛗 {landing.phi:.1f}°")
        i = 0
        while abs(landing.vspeed) > RATINGS[i][0] and i < len(RATINGS):
            i = i + 1
        logger.info(f"Rating: {RATINGS[i][1]}")
        if landing.ias > 0:
            if landing.toliss_vls > 0:
                logger.info(f"IAS{SEP}VLS: {landing.ias * landing.acf_ias_conv:.0f}{SEP}{landing.toliss_vls:.0f} {landing.acf_ias_unit}")
            else:
                logger.info(f"IAS: {landing.ias * landing.acf_ias_conv:.0f} {landing.acf_ias_unit}")
        logger.info(f"G:  {landing.G:.2f}")
        if landing.dist > 0:
            logger.info(f"Threshold {landing.rwy.arpt.icao}{SEP}{landing.rwy.ends[landing.rwy_end].id}")
            logger.info(f"Above:    {landing.cross_height * M_2_FT} ft{SEP}{landing.cross_height} m")
            if landing.toliss_strut_compress_dr:
                logger.info(f"Main wheel TD: {landing.dist * M_2_FT} ft{SEP}{landing.dist} m")
            else:
                logger.info(f"Distance:      {landing.dist * M_2_FT} ft{SEP}{landing.dist} m")
            if landing.nose_wheel_td_dist > 0:
                logger.info(f"Nose wheel TD: {landing.nose_wheel_td_dist * M_2_FT} ft{SEP}{landing.nose_wheel_td_dist} m")
            logger.info(f"from CL      : {landing.cl_delta * M_2_FT} ft{SEP}{landing.cl_delta} m{SEP}{landing.cl_angle:.1f}°")
        else:
            logger.info("not on a runway")

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
