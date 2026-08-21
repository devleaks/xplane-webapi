import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi

print("xpwebapi version", xpwebapi.version)
api = xpwebapi.rest_api()
print(api.capabilities)
api.set_api_version(api_version="v2")

types_dref = api.dataref("sim/cockpit2/tcas/targets/icao_type")
value = types_dref.get_string_value(encoding="ascii", nullval=" ")
types = [value[i:i+8].strip() for i in range(0, len(value), 8)]
lats = api.dataref("sim/cockpit2/tcas/targets/position/lat").value
lons = api.dataref("sim/cockpit2/tcas/targets/position/lon").value
alts = api.dataref("sim/cockpit2/tcas/targets/position/ele").value
hdgs = api.dataref("sim/cockpit2/tcas/targets/position/psi").value

for i in range(1,64):
    if types[i] != "":
        ok = os.path.exists(f"/Users/pierre/Developer/fs/x-dispatch/public/aircraft-shapes/{types[i]}.svg")
        print(i, types[i], ok, lons[i], lats[i], alts[i], hdgs[i])
