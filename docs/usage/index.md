---
# Python wrapper for X-Plane Web API

## Usage of REST API

```python
import xpwebapi

# assuming both app and simulator on same host computer
api = xpwebapi.rest_api()

print(api.capabilities)
# {'api': {'versions': ['v1', 'v2', 'v3']}, 'x-plane': {'version': '12.2.1'}}

api.set_api_version(api_version="v2")

dataref = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
print(dataref)
# sim/cockpit2/clock_timer/local_time_seconds=42

mapview = api.command("sim/map/show_current")
mapview.execute()
```

## Usage of Websocket API

```python
from xpwebapi import ws_api, CALLBACK_TYPE

ws = ws_api()

# Callback function when dataref value changes
def dataref_monitor(dataref: str, value: Any):
    print(f"dataref updated: {dataref}={value}")

ws.add_callback(cbtype=CALLBACK_TYPE.DATAREF_UPDATE, callback=dataref_monitor)

# Callback function when command gets executed in simulator
def command_active_monitor(command: str, active: bool):
    print(f"command activated: {command}={active}")

ws.add_callback(cbtype=CALLBACK_TYPE.COMMAND_ACTIVE, callback=command_active_monitor)

# Let's go
ws.connect()
ws.wait_connection() # blocks until X-Plane is reachable

dataref = ws.dataref("sim/cockpit2/clock_timer/local_time_seconds")
ws.monitor_dataref(dataref)
# alternative:
# dataref.monitor()

ws.monitor_command_active(ws.command("sim/map/show_current"))
# alternative:
# command = ws.command("sim/map/show_current")
# command.monitor()

ws.start(release=True)

time.sleep(30) #secs

print("terminating..")
ws.stop()
print("..disconnecting..")
ws.disconnect()
print("..terminated")
```

## Usage of UDP API

```
import time
from typing import Any
import xpwebapi

# Callback function when dataref value changes
def dataref_monitor(dataref: str, value: Any):
    print(f"{dataref}={value}")

# UDP API
beacon = xpwebapi.beacon()
beacon.start_monitor()
beacon.wait_for_beacon()

xp = xpwebapi.udp_api(beacon=beacon)

# In the case of UDP, there are no different types of callbacks
# just for dataref value changes
xp.add_callback(callback=dataref_monitor)

mapview = xp.command("sim/map/show_current")
xp.execute_command(mapview)

xp.monitor_dataref(xp.dataref(path="sim/flightmodel/position/indicated_airspeed"))
xp.monitor_dataref(xp.dataref(path="sim/flightmodel/position/latitude"))

xp.start()

```
