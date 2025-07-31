"""Set of optional dataref to record in addition to the mandatory ones.

Note: This is a python set of strings (Set[str]).

List all datarefs to monitor in the FDR.

In this simple demonstration FDR there is not check that the dataref exists and/or is valid.
A warning is issued, no more. In case of warning, play back of FDR file may not work.

"""

FDR_OPTIONAL = {
    "sim/flightmodel/misc/g_total",
}
