"""Set of optional dataref to record in addition to the mandatory ones.

Note: This is a python set of strings (Set[str]).

List all datarefs to monitor in the FDR.

In this simple demonstration FDR there is not check that the dataref exists and/or is valid.
A warning is issued, no more. In case of warning, play back of FDR file may not work.

"""
from fdr import FDRData

FDR_OPTIONAL = [
    FDRData(name="ground_speed", dataref="sim/flightmodel/position/groundspeed", dtype="float", unit="m/s"),
    FDRData(name="true_air_speed", dataref="sim/flightmodel/position/true_airspeed", dtype="float", unit="m/s"),
    FDRData(name="vspeed", dataref="sim/cockpit2/gauges/indicators/vvi_fpm_pilot", dtype="float", unit="ft/min"),
    FDRData(name="tracking", dataref="sim/cockpit2/gauges/indicators/ground_track_true_pilot", dtype="float", unit="°T"),
]
