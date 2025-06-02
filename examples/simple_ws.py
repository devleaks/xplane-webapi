import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import logging
import time
from typing import Any

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")


ws = xpwebapi.ws_api(host="192.168.1.140", port=8080)  # defaults to v2 for Websocket

print(ws.ws_url)


def dataref_monitor(dataref: str, value: Any):
    print(f"{dataref}={value}")


def command_active_monitor(command: str, active: bool):
    print(f"{command}={active}")


ws.on_dataref_update = dataref_monitor
ws.on_command_active = command_active_monitor

ws.connect()
ws.wait_connection()

###

dataref = ws.dataref("sim/cockpit2/clock_timer/local_time_seconds")
ws.monitor_dataref(dataref)

ws.monitor_command_active(ws.command("sim/map/show_current"))

print("\n\nplease activate map in X-Plane with sim/map/show_current (usually key stroke 'm')\n")

ws.start(release=True)

time.sleep(10)

print("terminating..")
ws.stop()
print("..disconnecting..")
ws.disconnect()
print("..terminated")
