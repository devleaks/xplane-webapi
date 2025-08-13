import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import logging

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")


# REST API

print("xpwebapi version", xpwebapi.version)

api = xpwebapi.rest_api(host="192.168.1.141", port=8080, api_version="v2")  # defaults: host="127.0.0.1", port=8086, api="/api", use_cache=False

# options: no_cache, version

print(api.capabilities)

api.set_api_version(api_version="v2")

dataref = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
print(dataref)

# fails:
print("error 'not a websocket api' is expected")
dataref.monitor()

# # dataref.value = 6
# # print(dataref)
# # dataref.write()

mapview = api.command("sim/map/show_current")
mapview.execute()

# fails:
print("error 'not a websocket api' is expected")
mapview.monitor()
