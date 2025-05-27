# Python wrapper for X-Plane Web API

## Usage of REST API

```python
import xpwebapi

# REST API
api = xpwebapi.rest_api(host="192.168.1.140", port=8080, api_version="v2")  # defaults: host="127.0.0.1", port=8086, api="/api", use_cache=False

# options: no_cache, version

print(api.capabilities)

api.set_api_version(api_version="v2")

dataref = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
print(dataref)
# sim/cockpit2/clock_timer/local_time_seconds=42

mapview = api.command("sim/map/show_current")
mapview.execute()
```

## Usage of Websocket API

```python
import xpwebapi

ws = xpwebapi.ws_api(host="192.168.1.140", port=8080)  # defaults to v2 for Websocket

def dataref_monitor(dataref: str, value: Any):
    print(f"dataref updated: {dataref}={value}")

def command_active_monitor(command: str, active: bool):
    print(f"command activated: {command}={active}")

ws.on_dataref_update = dataref_monitor
ws.on_command_active = command_active_monitor

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

time.sleep(10)

print("terminating..")
ws.stop()
print("..disconnecting..")
ws.disconnect()
print("..terminated")
```
