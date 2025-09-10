import os
import sys
import logging

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")


# REST API

print("xpwebapi version", xpwebapi.version)

api = xpwebapi.rest_api(
    host="192.168.1.140", port=8080, api_version="v2"
)  # defaults: host="127.0.0.1", port=8086, api="/api", api_version="v1", use_cache=False

# options: no_cache, version

print(api.capabilities)

d1 = api.dataref("sim/cockpit2/clock_timer/local_time_hours")
d2 = api.dataref("sim/cockpit2/clock_timer/zulu_time_hours")

dm = api.datarefs_meta(datarefs=[d1, d2])

print(dm)

# sim/map/show_current
c1 = api.command("sim/map/show_current")
c2 = api.command("sim/operation/toggle_weather_map")

cm = api.commands_meta(commands=[c1, c2])

print(cm)
