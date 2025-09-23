"""Earth-based geometry helper function and classes

    With possible GeoJSON output, to send to geojson.io
"""

import math
from dataclasses import dataclass

from typing import List, Tuple, Dict


R = 6378000  # Radius of third rock from the sun, in metres


def angle_to_360(alfa: float) -> float:
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


def destination(lat: float, lon: float, bearing_deg: float, d: float) -> Tuple[float, float]:
    # From lat, lon, move d meters heading bearing_deg
    lat = math.radians(lat)
    lon = math.radians(lon)
    brng = math.radians(bearing_deg)
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

    def geoson(self) -> Dict:
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "coordinates": [self.lon, self.lat],
                "type": "Point",
            },
        }


@dataclass
class Line:
    start: Point
    end: Point

    def geoson(self) -> Dict:
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "coordinates": [[self.start.lon, self.start.lat], [self.end.lon, self.end.lat]],
                "type": "LineString",
            },
        }


def mkLine(lat1: float, lon1: float, lat2: float, lon2: float) -> Line:
    return Line(start=Point(lat1, lon1), end=Point(lat2, lon2))


@dataclass
class Polygon:
    points: List[Point]

    def geoson(self) -> Dict:
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "coordinates": [[(l.lon, l.lat) for l in self.points]],
                "type": "Polygon",
            },
        }


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


class GeoJSONIO:
    # Simple text/dict manipulation to present geographic geometries in GeoJSON for display on geojson.io.
    # Later: Add coloring

    def __init__(self):
        self.collection = []

    def add(self, feature: dict):
        self.collection.append(feature)

    def feature_collection(self) -> dict:
        return {
            "type": "FeatureCollection",
            "features": self.collection,
        }

    @staticmethod
    def point(lat: float, lon: float):
        # "properties": {
        #   "marker-color": "#e32400",
        #   "marker-size": "medium",
        #   "marker-symbol": "circle"
        # },
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "coordinates": [lon, lat],
                "type": "Point",
            },
        }

    @staticmethod
    def line(lat1: float, lon1: float, lat2: float, lon2: float):
        # "properties": {
        #   "stroke": "#ff40ff",
        #   "stroke-width": 2,
        #   "stroke-opacity": 1
        # },
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "coordinates": [[lon1, lat1], [lon2, lat2]],
                "type": "LineString",
            },
        }

    @staticmethod
    def polygon(points: List[Tuple[float, float]]):
        # "properties": {
        #   "stroke": "#fffb00",
        #   "stroke-width": 2,
        #   "stroke-opacity": 1,
        #   "fill": "#0433ff",
        #   "fill-opacity": 0.5
        # },
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "coordinates": [[(p[1], p[0]) for p in points]],
                "type": "Polygon",
            },
        }
