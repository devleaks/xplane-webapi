---
title: Usage
---

# Usage

## Connection lifecycle

Use context managers for REST clients so the underlying HTTP session is closed even when a request fails.

```python
import xpwebapi


with xpwebapi.rest_api(host="127.0.0.1", port=8086, api_version="v2") as api:
    print(api.capabilities)

    clock = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
    print(api.dataref_value(clock))
```

Async REST clients follow the same pattern with `async with`.

```python
import asyncio

import xpwebapi


async def main() -> None:
    async with xpwebapi.async_rest_api(api_version="v2") as api:
        clock = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
        value = await api.dataref_value(clock)
        print(value)


asyncio.run(main())
```

When creating many short-lived synchronous REST API objects, opt in to shared HTTP connection pooling. Instances with matching pool configuration reuse the same underlying `httpx.Client`; the shared client closes after the last pooled API instance is closed.

```python
import xpwebapi


first = xpwebapi.rest_api(
    api_version="v2",
    pool_connections=True,
    max_connections=8,
    max_keepalive_connections=4,
    keepalive_expiry=30.0,
    timeout=5.0,
)
second = xpwebapi.rest_api(
    api_version="v2",
    pool_connections=True,
    max_connections=8,
    max_keepalive_connections=4,
    keepalive_expiry=30.0,
    timeout=5.0,
)

try:
    print(first.capabilities)
    clock = second.dataref("sim/cockpit2/clock_timer/local_time_seconds")
    print(second.dataref_value(clock))
finally:
    first.close()
    second.close()
```

For WebSocket and UDP clients, explicitly stop monitoring/listener threads before disconnecting when you do not use a context manager.

```python
import xpwebapi


ws = xpwebapi.ws_api(api_version="v2")
try:
    ws.connect()
    ws.wait_connection()
    ws.start(release=True)
finally:
    ws.stop()
    ws.disconnect()
```

## Monitoring datarefs

WebSocket monitoring is callback-driven. Register the callback, connect, subscribe to the datarefs, then start the listener.
Use `monitor_datarefs()` when subscribing to more than one dataref; it sends one WebSocket `dataref_subscribe_values` request for all newly monitored datarefs instead of one request per dataref.
The matching `unmonitor_datarefs()` helper batches unsubscribe requests for datarefs whose monitor count reaches zero.
Selected array elements that share the same dataref id are grouped into one request with an index list.

```python
from typing import Any

import xpwebapi


def dataref_monitor(dataref: str, value: Any) -> None:
    print(f"{dataref}={value}")


ws = xpwebapi.ws_api(api_version="v2")
ws.add_callback(
    cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE,
    callback=dataref_monitor,
)

ws.connect()
ws.wait_connection()

datarefs = [
    ws.dataref("sim/cockpit2/clock_timer/local_time_seconds"),
    ws.dataref("sim/flightmodel/position/latitude"),
    ws.dataref("sim/flightmodel/position/longitude"),
]
ws.monitor_datarefs(datarefs=datarefs, reason="example")
ws.start(release=True)
```

UDP monitoring uses the X-Plane beacon to discover the simulator before subscribing.

```python
from typing import Any

import xpwebapi


def dataref_monitor(dataref: str, value: Any) -> None:
    print(f"{dataref}={value}")


beacon = xpwebapi.beacon()
beacon.start_monitor()
beacon.wait_for_beacon()

udp = xpwebapi.udp_api(beacon=beacon)
udp.add_callback(callback=dataref_monitor)
udp.monitor_dataref(udp.dataref("sim/flightmodel/position/indicated_airspeed"))
udp.start(release=True)
```

## Executing commands

Create a command object from the API instance that will execute it. REST and UDP calls return immediate success/failure values; WebSocket command execution can return a queued request id.

```python
import xpwebapi


with xpwebapi.rest_api(api_version="v2") as api:
    mapview = api.command("sim/map/show_current")
    result = mapview.execute()
    print(result)
```

Long-running commands can pass an explicit duration when the transport supports it.

```python
import xpwebapi


with xpwebapi.ws_api(api_version="v2") as ws:
    ws.connect()
    ws.wait_connection()

    brakes = ws.command("sim/flight_controls/brakes_toggle_max")
    request_id = ws.execute_command(brakes, duration=0.5)
    print(request_id)
```

## REST API

```python
import xpwebapi


with xpwebapi.rest_api(api_version="v2") as api:
    print(api.capabilities)

    dataref = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
    print(dataref)

    mapview = api.command("sim/map/show_current")
    mapview.execute()
```

## Async REST API

```python
import asyncio

import xpwebapi


async def main() -> None:
    async with xpwebapi.async_rest_api(api_version="v2") as api:
        dataref = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
        value = await api.dataref_value(dataref)
        print(value)

        mapview = api.command("sim/map/show_current")
        await api.execute_command(mapview)


asyncio.run(main())
```

## WebSocket API

```python
from typing import Any

import xpwebapi


def dataref_monitor(dataref: str, value: Any) -> None:
    print(f"dataref updated: {dataref}={value}")


def command_active_monitor(command: str, active: bool) -> None:
    print(f"command activated: {command}={active}")


ws = xpwebapi.ws_api(api_version="v2")
ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=dataref_monitor)
ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_COMMAND_ACTIVE, callback=command_active_monitor)

ws.connect()
ws.wait_connection()

dataref = ws.dataref("sim/cockpit2/clock_timer/local_time_seconds")
ws.monitor_dataref(dataref)
ws.monitor_command_active(ws.command("sim/map/show_current"))

ws.start(release=True)
```

## UDP API

```python
from typing import Any

import xpwebapi


def dataref_monitor(dataref: str, value: Any) -> None:
    print(f"{dataref}={value}")


beacon = xpwebapi.beacon()
beacon.start_monitor()
beacon.wait_for_beacon()

udp = xpwebapi.udp_api(beacon=beacon)
udp.add_callback(callback=dataref_monitor)

mapview = udp.command("sim/map/show_current")
udp.execute_command(mapview)

udp.monitor_dataref(udp.dataref(path="sim/flightmodel/position/indicated_airspeed"))
udp.monitor_dataref(udp.dataref(path="sim/flightmodel/position/latitude"))
udp.start(release=True)
```
