""" Creates KML 3D flight path for visualisation in Google Earth or alike: [description]
"""
import simplekml

def to_kml(path: list, airport: dict, name: str = "Flight Path", desc: str = "Landing Flight Path") -> str:
    # coords = [ts, lat, lon, alt]
    kml = simplekml.Kml(open=1, name="Flight Path", description=f"Landing Flight Path")
    ls = kml.newlinestring(name=name, description=desc)

    ls.coords = [(p[2], p[1], p[3]) for p in path]

    ls.altitudemode = simplekml.AltitudeMode.relativetoground

    ls.extrude = 1
    ls.style.linestyle.color = simplekml.Color.yellow
    ls.style.linestyle.width = 4
    ls.style.polystyle.color = "80ffff00"  # a,b,g,r

    if len(airport) > 0:
        ls.lookat.gxaltitudemode = simplekml.GxAltitudeMode.relativetoseafloor
        ls.lookat.latitude = airport.get("lat")
        ls.lookat.longitude = airport.get("lon")
        ls.lookat.range = 70000
        ls.lookat.heading = 0
        ls.lookat.tilt = 70

    return kml.kml(format=True)


# Possible and easy to animate with TimeStamp added to each segment.
