import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi


beacon = xpwebapi.beacon()


def callback(connected: bool):
    print("reachable" if connected else "unreachable")
    if beacon.connected:  # !!beacon defined before
        print(beacon.find_ip())
        print("same host:", beacon.same_host())


beacon.set_callback(callback)
beacon.connect()
