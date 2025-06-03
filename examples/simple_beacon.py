import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi


beacon = xpwebapi.beacon()


def callback(connected: bool):
    print("X-Plane beacon " + ("detected" if connected else "not detected"))
    if beacon.connected:  # !!beacon defined before
        print(beacon.find_ip())
        print("same host:", beacon.same_host())


beacon.set_callback(callback)

beacon.connect()
time.sleep(10)
beacon.disconnect()
