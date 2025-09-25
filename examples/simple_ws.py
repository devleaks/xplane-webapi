import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import logging
import time
from typing import Any

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")


ws = xpwebapi.ws_api(host="192.168.1.141", port=8080)  # defaults to v2 for Websocket

print(ws.ws_url)


def dataref_monitor(dataref: str, value: Any):
    print(f"{dataref}={value}")


def command_active_monitor(command: str, active: bool):
    print(f"{command}={active}")


ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=dataref_monitor)
ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_COMMAND_ACTIVE, callback=command_active_monitor)

ws.connect()
ws.wait_connection()

###

dataref = ws.dataref("sim/cockpit2/clock_timer/local_time_seconds")
ws.monitor_dataref(dataref)

arrdrefall = ws.dataref("sim/weather/region/wind_altitude_msl_m") # does not change a lot when not moving
ws.monitor_dataref(arrdrefall)

arrdref1 = ws.dataref("sim/weather/aircraft/wind_direction_degt[0]")
ws.monitor_dataref(arrdref1)

ws.monitor_command_active(ws.command("sim/map/show_current"))

print("\n\nplease activate map in X-Plane with sim/map/show_current (usually key stroke 'm')\n")


ws.start(release=True)  # release means function will return, otherwise blocks inside function until all threads are terminated.

sometime = 60  # seconds
print(f"waiting {sometime} before terminating")
time.sleep(sometime)

print("terminating..")
ws.stop()
print("..disconnecting..")
ws.disconnect()
print("..terminated")
