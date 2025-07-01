import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi


beacon = xpwebapi.beacon()


def callback(connected: bool, beacon_data: xpwebapi.BeaconData, same_host: bool):
    print("X-Plane beacon " + ("detected" if connected else "not detected"))
    if connected:  # !!beacon defined before
        print(beacon_data)
        print("same host:", same_host)


beacon.set_callback(callback)

beacon.start_monitor()
sometime = 10  # secs
print(f"attempting {sometime} seconds")
time.sleep(sometime)
beacon.stop_monitor()
