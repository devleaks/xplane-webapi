import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import logging
import json
from datetime import datetime

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)


HEADER = {
    "sim/version/xplane_internal_version",
    "sim/aircraft/view/acf_ICAO",
    "sim/aircraft/engine/acf_num_engines",
    "sim/aircraft/view/acf_tailnum",
    "sim/aircraft/weight/acf_m_empty",
    "sim/aircraft/weight/acf_m_max",
}

FDR_DATA = {
    "sim/cockpit2/gauges/indicators/wind_heading_deg_mag",
    "sim/cockpit2/gauges/indicators/wind_speed_kts",
    "sim/cockpit2/temperature/outside_air_temp_degc",
    "sim/time/total_flight_time_sec",
    "sim/time/zulu_time_sec",
    "sim/time/is_in_replay",
    "sim/time/paused",
    "sim/time/total_running_time_sec",
    "sim/flightmodel/position/latitude",
    "sim/flightmodel/position/longitude",
    "sim/flightmodel/position/groundspeed",
    "sim/cockpit2/gauges/indicators/heading_vacuum_deg_mag_pilot",
    "sim/cockpit2/gauges/indicators/radio_altimeter_height_ft_pilot",
    "sim/flightmodel/misc/h_ind",
    "sim/flightmodel/position/vh_ind_fpm",
    "sim/flightmodel/position/indicated_airspeed",
    "sim/flightmodel/misc/machno",
    "sim/flightmodel/position/true_theta",
    "sim/flightmodel/position/true_phi",
    "sim/flightmodel/position/alpha",
    "sim/flightmodel/misc/g_total",
    "sim/flightmodel/position/hpath",
    "sim/flightmodel/position/magnetic_variation",
    "sim/flightmodel/engine/ENGN_running",
    "sim/flightmodel/engine/ENGN_thro",
    "sim/cockpit2/engine/indicators/power_watts[0]",
    # "sim/cockpit2/engine/indicators/power_watts",
    "sim/cockpit2/controls/left_brake_ratio",
    "sim/cockpit2/controls/right_brake_ratio",
    "sim/cockpit2/controls/parking_brake_ratio",
    "sim/cockpit2/controls/gear_handle_down",
    "sim/cockpit2/controls/yoke_pitch_ratio",
    "sim/cockpit2/controls/yoke_roll_ratio",
    "sim/cockpit2/controls/yoke_heading_ratio",
    "sim/cockpit2/controls/flap_ratio",
    "sim/cockpit2/controls/speedbrake_ratio",
    "sim/cockpit/autopilot/autopilot_mode",
    "sim/flightmodel/weight/m_total",
    "sim/flightmodel/weight/m_fuel_total",
    "sim/cockpit2/pressurization/indicators/cabin_altitude_ft",
    "sim/cockpit2/pressurization/indicators/cabin_vvi_fpm",
    "sim/cockpit2/radios/indicators/nav1_nav_id",
    "sim/cockpit/radios/nav1_course_degm",
    "sim/cockpit/radios/nav1_slope_degt",
    "sim/cockpit/radios/nav1_dme_dist_m",
    "sim/cockpit/radios/nav1_hdef_dot",
    "sim/cockpit/radios/nav1_vdef_dot",
    "sim/cockpit/electrical/beacon_lights_on",
    "sim/cockpit/electrical/landing_lights_on",
    "sim/cockpit/electrical/nav_lights_on",
    "sim/cockpit/electrical/strobe_lights_on",
    "sim/cockpit/electrical/taxi_light_on",
    "sim/flightmodel/controls/ail_trim",
    "sim/flightmodel/controls/rud_trim",
    "sim/flightmodel/controls/slatrat",
    "sim/flightmodel/position/elevation",
    "sim/flightmodel/position/latitude",
    "sim/flightmodel/position/local_vx",
    "sim/flightmodel/position/local_vy",
    "sim/flightmodel/position/local_vz",
    "sim/flightmodel/position/local_x",
    "sim/flightmodel/position/local_y",
    "sim/flightmodel/position/local_z",
    "sim/flightmodel/position/longitude",
    "sim/flightmodel/position/phi",
    "sim/flightmodel/position/psi",
    "sim/flightmodel/position/theta",
    "sim/flightmodel2/controls/flap1_deploy_ratio",
    "sim/flightmodel2/controls/flap2_deploy_ratio",
    "sim/flightmodel2/controls/speedbrake_ratio",
    "sim/flightmodel2/controls/wingsweep_ratio",
    "sim/flightmodel2/engines/throttle_used_ratio",
    "sim/flightmodel2/gear/deploy_ratio",
}


class FDR:

    def __init__(self, api) -> None:
        self.header_ok = False
        self.header = {}
        self.lines = []
        self.file = None
        self.datarefs = {}
        self.init()

    def init(self):
        self.datarefs = {path: ws.dataref(path) for path in self.get_dataref_names()}
        ws.on_dataref_update = self.dataref_changed
        ws.register_bulk_dataref_value_event(datarefs=self.datarefs, on=True)
        ws.connect()
        ws.start()

    def get_dataref_names(self) -> set:
        return HEADER | FDR_DATA

    def dataref_changed(self, path, value):
        ts = datetime.now().timestamp()
        if not self.header_ok:
            if path in HEADER:
                self.header[path] = value
                self.header_ok = len(self.header) == len(HEADER)
                if self.header_ok:
                    with open("out.fdr", "w") as fp:
                        json.dump(self.header, fp)
                    self.file = open("out.fdr", "  a")
                    for l in self.lines:
                        self.file.write(l)
                    self.lines = []
                return
            self.lines.append(f"{ts},{path},{value}")
            return
        self.file.write(f"{ts},{path},{value}")

    def terminate(self):
        self.file.close()
        self.ws.disconnect()


if __name__ == "__main__":
    ws = xpwebapi.ws_api(host="192.168.1.140", port=8080)
    try:
        fdr = FDR(ws)
    except:
        logger.warning("terminating..", exc_info=True)
        fdr.close()
