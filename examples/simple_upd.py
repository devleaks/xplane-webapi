import os
import sys
import logging
import time

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")


# UDP API
beacon = xpwebapi.beacon()
beacon.start_monitor()
while not beacon.receiving_beacon:
    print("waiting for beacon")
    time.sleep(2)
xp = xpwebapi.udp_api(beacon=beacon)

xp.monitor_dataref(xp.dataref(path="sim/flightmodel/position/indicated_airspeed"))
xp.monitor_dataref(xp.dataref(path="sim/flightmodel/position/latitude"))

while True:
    values = xp.read_monitored_dataref_values()
    print(values)
    time.sleep(2)
