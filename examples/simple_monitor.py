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

DATAREFS = [
    "sim/cockpit2/clock_timer/local_time_seconds",
    "sim/flightmodel/position/latitude",
    "sim/flightmodel/position/longitude"
]

COMMANDS = [
    "sim/map/show_current"
]

def dataref_monitor(dataref: str, value: Any):
    print(f"{dataref}={value}")

def command_active_monitor(command: str, active: bool):
    print(f"{command}={active}")


ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=dataref_monitor)
ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_COMMAND_ACTIVE, callback=command_active_monitor)

ws.connect()
ws.wait_connection()

###
for d in DATAREFS:
    dataref = ws.dataref(d)
    ws.monitor_dataref(dataref)

for c in COMMANDS:
    command = ws.command(c)
    ws.monitor_command_active(command)

ws.start(release=True)

sometime = 60  # seconds
print(f"waiting {sometime} before terminating")
time.sleep(sometime)

print("terminating..")
ws.stop()
print("..disconnecting..")
ws.disconnect()
print("..terminated")
