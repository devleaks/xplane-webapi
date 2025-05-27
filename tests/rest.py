import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from typing import Any

import xpwebapi

# REST API
api = xpwebapi.rest_api(host="192.168.1.140", port=8080, api_version="v2")  # defaults: host="127.0.0.1", port=8086, api="/api", use_cache=False

# options: no_cache, version

print(api.capabilities)

api.set_api_version(api_version="v2")

dataref = api.dataref("dataref/path")

print(dataref)

# dataref.value = 6
# print(dataref)
# dataref.write()

# print(dataref)
# dataref/path
# id=12345
# type=int
# writable=True

# sim/map/show_current
mapview = api.command("sim/map/show_current")
command = api.command("toliss_airbus/lightcommands/BeaconToggle")

print(command)

command.execute()
mapview.execute()
