"""Conversion utility functions.

Why doesn't airline business use MKSA?
There are only 3 countries in the world that are still officially using the imperial system: The United States of America, Myanmar, and Liberia.
"""

from typing import Tuple


########################################
# Units, etc
#
FT = 12 * 0.0254  # 1 foot = 12 inches = 0.3048m
NAUTICAL_MILE = 1.852  # Nautical mile in meters 6076.118ft=1nm. Easy.


def sign(x: float | int):
    # why does this function not exists in python?
    return -1 if x < 0 else (0 if abs(x) == 0 else 1)  # -0 is not 0.


class convert:
    @staticmethod
    def dms_to_dd(degrees, minutes, seconds, direction) -> float:
        dd = float(degrees) + float(minutes) / 60 + float(seconds) / (60 * 60)
        return dd if direction in ("N", "E") else dd * -1

    @staticmethod
    def cifp_alt_in_ft(s: str) -> int | None:
        """Convert altitude as specified in ARINC424 to int.
        Altitude can be 12345 or FL250, or -1234 if below sea level.
        Always 5 characters, unused char should be space. Can be "  123" or "123  ".
        """
        s = s.strip()
        if s == "":
            return None
        if s.startswith("FL"):
            return int(s[2:]) * 100
        return int(s)

    @staticmethod
    def cifp_alt_in_fl(alt: float) -> str:
        if alt > 15000 and alt == (100 * int(alt / 100)):
            return f"FL{int(alt/100)}"
        return f"{alt}"

    @staticmethod
    def cifp_speed(s: str) -> int | None:
        """Convert speed in ARINC424 to float."""
        s = s.strip()
        if s == "":
            return None
        return int(s)

    @staticmethod
    def m_to_nm(m: float) -> float:
        """
        Convert meter to nautical miles

        :param      m:    { parameter_description }
        :type       m:    { type_description }

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        return m / NAUTICAL_MILE

    @staticmethod
    def meters_to_feet(m: float) -> float:
        """
        Convert meter to feet

        :param      m:    { parameter_description }
        :type       m:    { type_description }

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        return m / FT

    @staticmethod
    def meters_to_fl(m: float, rounding: int = -1) -> int:
        """
        Convert meter to feet

        :param      m:    { parameter_description }
        :type       m:    { type_description }

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        r = (m / FT) / 100
        if rounding != -1:
            r = rounding * round(r / rounding)
        return int(r)

    @staticmethod
    def fl_to_meters(fl: float) -> float:
        """
        Convert meter to feet

        :param      m:    { parameter_description }
        :type       m:    { type_description }

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        return fl * 100 * FT

    @staticmethod
    def feet_to_meters(ft: float) -> float:
        """
        Convert feet to meters

        :param      f:    { parameter_description }
        :type       f:    { type_description }

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        return ft * FT

    @staticmethod
    def kmh_to_kn(kmh: float) -> float:
        """
        Convert kilometer per hours into knots

        :param      kmh:  The kilometers per hour
        :type       kmh:  { type_description }

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        return kmh / NAUTICAL_MILE

    @staticmethod
    def ms_to_kn(ms: float, r: int | None = None) -> float:
        """
        Convert meters per second into knots

        :param      ms:  The meters per second
        :type       kmh:  { type_description }

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        s = convert.kmh_to_kn(kmh=convert.ms_to_kmh(ms))
        if r is not None:
            s = round(s, r)
        return s

    @staticmethod
    def kmh_to_ms(kmh: float) -> float:
        """
        Convert kilometer per hours into meters/second

        float kmh: speed in kilometers per hour

        float:    speed in meters per second
        """
        return kmh / 3.6

    @staticmethod
    def ms_to_kmh(ms: float) -> float:
        return ms * 3.6

    @staticmethod
    def kn_to_kmh(kn: float) -> float:
        return kn * NAUTICAL_MILE

    @staticmethod
    def kn_to_ms(kn: float) -> float:
        return convert.kmh_to_ms(kn * NAUTICAL_MILE)

    @staticmethod
    def ms_to_fpm(ms: float, r: int | None = None) -> float:
        s = convert.meters_to_feet(ms * 60)
        if r is not None:
            s = round(s, r)
        return s

    @staticmethod
    def fpm_to_ms(fpm: float) -> float:
        return convert.feet_to_meters(fpm / 60)

    @staticmethod
    def km_to_nm(km: float) -> float:
        return km / NAUTICAL_MILE

    @staticmethod
    def nm_to_km(nm: float) -> float:
        return nm * NAUTICAL_MILE

    @staticmethod
    def nm_to_meters(nm: float) -> float:
        return nm * NAUTICAL_MILE * 1000

    @staticmethod
    def fl_to_m(fl: int) -> float:
        return fl * FT / 100

    @staticmethod
    def mach_to_speeds(mach: float, altitude: int = 30000) -> Tuple[float, float, float]:
        mph_machconvert = mach * 660
        kmh_machconvert = mach * 1062
        knots_machconvert = mach * 573

        if altitude >= 40000:
            mph_machconvert = mach * 660
            kmh_machconvert = mach * 1062
            knots_machconvert = mach * 573

        elif altitude >= 35000:
            mph_machconvert = mach * 664
            kmh_machconvert = mach * 1069
            knots_machconvert = mach * 577

        elif altitude >= 30000:
            mph_machconvert = mach * 679
            kmh_machconvert = mach * 1093
            knots_machconvert = mach * 590

        elif altitude >= 25000:
            mph_machconvert = mach * 693
            kmh_machconvert = mach * 1116
            knots_machconvert = mach * 602

        elif altitude >= 20000:
            mph_machconvert = mach * 707
            kmh_machconvert = mach * 1138
            knots_machconvert = mach * 614

        elif altitude >= 15000:
            mph_machconvert = mach * 721
            kmh_machconvert = mach * 1161
            knots_machconvert = mach * 627

        elif altitude >= 10000:
            mph_machconvert = mach * 735
            kmh_machconvert = mach * 1182
            knots_machconvert = mach * 638

        elif altitude >= 0:
            mph_machconvert = mach * 762
            kmh_machconvert = mach * 1223
            knots_machconvert = mach * 660

        else:
            mph_machconvert = mach * 660
            kmh_machconvert = mach * 1062
            knots_machconvert = mach * 573

        return (kmh_machconvert, knots_machconvert, mph_machconvert)

    @staticmethod
    def mach_to_kmh(mach: float, altitude: int = 30000) -> float:
        """
        Convert MACH speed to ground speed for different altitude ranges.
        Altitude should be supplied in feet ASL.
        Returns kilometers per hour.

        :param      mach:      The mach
        :type       mach:      float
        :param      altitude:  The altitude
        :type       altitude:  int

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        c = convert.mach_to_speeds(mach, altitude)
        return c[0]

    @staticmethod
    def mach_to_ms(mach: float, altitude: int = 30000) -> float:
        """
        Convert MACH speed to ground speed for different altitude ranges.
        Altitude should be supplied in feet ASL.
        Returns kilometers per hour.

        :param      mach:      The mach
        :type       mach:      float
        :param      altitude:  The altitude
        :type       altitude:  int

        :returns:   { description_of_the_return_value }
        :rtype:     { return_type_description }
        """
        c = convert.mach_to_speeds(mach, altitude)
        return c[0] / 3.6
