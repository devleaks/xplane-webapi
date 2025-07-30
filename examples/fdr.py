import os
import sys
import logging
import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import xpwebapi

FORMAT = "[%(asctime)s] %(levelname)s %(threadName)s %(filename)s:%(funcName)s:%(lineno)d: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt="%H:%M:%S")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)


# ACFT, Aircraft/Laminar Research/Lancair Evolution/N844X.acf
# TAIL, N844X
# DATE, 01/18/2023
# PRES, 30.01
# DISA, 0
# WIND, 270,15
HEADER = {
    "sim/aircraft/view/acf_relative_path",
    "sim/aircraft/view/acf_tailnum",
    "sim/cockpit2/clock_timer/current_month",
    "sim/cockpit2/clock_timer/current_day",
    "sim/weather/barometer_current_inhg",
    "sim/weather/barometer_sealevel_inhg",
    "sim/weather/aircraft/wind_now_direction_degt",
    "sim/weather/aircraft/wind_now_speed_msc"  # 1 m/s = 1,94384449 knt
}

# They MUST BE the ZULU time, then the longitude, latitude, altitude in feet, magnetic heading in degrees, then pitch and roll in degrees.
FDR_DATA = {
    "sim/cockpit2/clock_timer/zulu_time_hours",
    "sim/cockpit2/clock_timer/zulu_time_minutes",
    "sim/cockpit2/clock_timer/zulu_time_seconds",
    "sim/flightmodel/position/longitude",
    "sim/flightmodel/position/latitude",
    "sim/cockpit/pressure/cabin_altitude_actual_ft",
    "sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot",
    "sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot",
    "sim/cockpit2/gauges/indicators/roll_electric_deg_pilot",
}

FDR_OPTIONAL = {
    "sim/flightmodel/misc/g_total",
}


FILENAME = "out.fdr"

class FDR:

    def __init__(self, api) -> None:
        self.ws = api
        self.header_ok = False
        self.header = {}
        self.lines = []
        self.file = None
        self.datarefs = {}
        self.writes = 0
        self.last_seconds = -1
        self.init()

    def init(self):
        self.datarefs = {path: self.ws.dataref(path) for path in self.get_dataref_names()}
        self.ws.add_callback(cbtype=xpwebapi.CALLBACK_TYPE.ON_DATAREF_UPDATE, callback=self.dataref_changed)

    def start(self):
        ws.connect()
        ws.wait_connection()
        ws.monitor_datarefs(datarefs=self.datarefs, reason="Flight data recorder")
        ws.start()

    def get_dataref_names(self) -> set:
        return HEADER | FDR_DATA | FDR_OPTIONAL

    def print_header(self):
        with open(FILENAME, "w") as fp:
            print("A\r", end="", file=fp)
            print("4", file=fp)
            print(f"ACFT, {self.header.get('sim/aircraft/view/acf_relative_path')}", file=fp)
            tail = self.header.get('sim/aircraft/view/acf_tailnum')
            tail = tail.rstrip(b"\x00")
            print(f"TAIL, {tail}", file=fp)
            print(f"DATE, {self.header.get('sim/cockpit2/clock_timer/current_month')}/{self.header.get('sim/cockpit2/clock_timer/current_day')}/2025", file=fp)
            print(f"PRES, {round(self.header.get('sim/weather/barometer_sealevel_inhg'), 2)}", file=fp)
            print("DISA, 0", file=fp)
            print(f"WIND, {int(self.header.get('sim/weather/aircraft/wind_now_direction_degt'))}, {round(self.header.get('sim/weather/aircraft/wind_now_speed_msc') * 1.94384449, 2)}", file=fp)
            print("", file=fp)
            print("COMM, Optional datarefs", file=fp)
            for d in FDR_OPTIONAL:
                print(f"DREF, {d}  1.0 // comment:", file=fp)
            print("", file=fp)
            optional = ", ".join(FDR_OPTIONAL)
            if optional != "":
                optional = ", " + optional
            print("COMM, Time, Longitude, Latitude, AltMSL, HDG, Pitch, Roll" + optional, file=fp)
            print("", file=fp)

        print("FDR header ok")

    def print_line(self) -> str:
        ts = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S.%f")
        lat = self.datarefs.get("sim/flightmodel/position/latitude").value
        lon = self.datarefs.get("sim/flightmodel/position/longitude").value
        alt = self.datarefs.get("sim/cockpit/pressure/cabin_altitude_actual_ft").value
        mag = self.datarefs.get("sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot").value
        pitch = self.datarefs.get("sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot").value
        roll = self.datarefs.get("sim/cockpit2/gauges/indicators/roll_electric_deg_pilot").value
        base = f"{ts}, {lon}, {lat}, {alt}, {mag}, {pitch}, {roll}"
        optional = ""
        for d in FDR_OPTIONAL:
            dref = self.datarefs.get(d)
            optional = optional + f", {dref.value}"
        return base + optional + "\n"

    def dataref_changed(self, dataref, value):
        self.datarefs[dataref].value = value
        if not self.header_ok:
            if dataref in HEADER:
                self.header[dataref] = value
                self.header_ok = len([d for d in self.header if d is not None]) == len(HEADER)
                if self.header_ok:
                    self.print_header()
                    # writing buffered lines
                    self.file = open(FILENAME, "a")
                    for l in self.lines:
                        self.writes = self.writes + 1
                        self.file.write(l)
                    print(f"FDR {len(self.lines)} buffered lines written")
                    self.lines = []
                return
            # buffering lines while header not written
            if dataref == "sim/cockpit2/clock_timer/zulu_time_seconds":
                self.last_seconds = value
                self.lines.append(self.print_line())
            return
        if dataref == "sim/cockpit2/clock_timer/zulu_time_seconds" and self.last_seconds != value:
            self.file.write(self.print_line())
            self.writes = self.writes + 1
            self.file.flush()

    def terminate(self):
        if self.file is not None:
            self.file.close()
            self.file = None
        ws.register_bulk_dataref_value_event(datarefs=self.datarefs, on=False)
        self.ws.disconnect()


if __name__ == "__main__":
    ws = xpwebapi.ws_api(host="192.168.1.141", port=8080)
    fdr = FDR(ws)
    try:
        fdr.start()
    except:
        logger.warning("terminating..", exc_info=True)
        fdr.terminate()
