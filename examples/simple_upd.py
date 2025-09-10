import os
import sys
import logging
from typing import Any

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")


def dataref_monitor(dataref: str, value: Any):
    print(f"{dataref}={value}")


# UDP API
beacon = xpwebapi.beacon()
beacon.start_monitor()
beacon.wait_for_beacon(report=True)  # blocks until beacon is detected

xp = xpwebapi.udp_api(beacon=beacon)

xp.add_callback(callback=dataref_monitor)

xp.monitor_dataref(xp.dataref(path="sim/flightmodel/position/indicated_airspeed"))
xp.monitor_dataref(xp.dataref(path="sim/flightmodel/position/latitude"))

xp.start()

# Manual alternate:
#
# while True:
#     values = xp.read_monitored_dataref_values()
#     print(values)
#     time.sleep(2)
