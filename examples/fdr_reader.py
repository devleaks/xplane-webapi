import sys
import json
from datetime import datetime, timedelta, timezone
from pprint import pprint
from traceback import print_exc

from PI_fdr import FDRData  # used in eval(), FDRData is a @dataclass

HEADER_KEYWORDS = [
  "ACFT",
  "TAIL",
  "TIME",
  "DATE",
  "PRES",
  "TEMP",
  "WIND",
  "DISA",
]

DATA_KEYWORDS = [
  "COMM",
  "DREF",
  "CALI",
  "WARN",
  "TEXT",
  "MARK",
  "EVNT",
  "DATA",
]

def clean(s: str) -> tuple:
  SEP = ","
  a = [b.strip() for b in s.split(SEP)]
  return a[0], SEP.join(a[1:]), s[s.index(SEP)+1:].strip()


class FDRReader:

  def __init__(self, filename: str = "out.fdr") -> None:
    self.filename = filename
    self.fdr_version = 0

    with open(self.filename) as fp:
      self.lines = [l.strip() for l in fp.readlines()]

    self.basedate = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone()
    self.meta = {k: list() for k in DATA_KEYWORDS}
    self.units = []
    self.header = []
    self.data = []
    self._last_ts = None
    self.fdr_data = {}

  @property
  def duration(self) -> timedelta:
    if len(self.data) > 1:
      return datetime.strptime(self.data[-1][0].strip(), "%H:%M:%S.%f") - datetime.strptime(self.data[0][0].strip(), "%H:%M:%S.%f")
    return timedelta(0)

  @property
  def length(self) -> int:
    return len(self.data)

  @property
  def has_fdrdata(self) -> bool:
    return len(self.fdr_data) > 0

  def parse(self) -> bool:
    #
    # ACFT, Aircraft/Airbus/ToLiss A321/a321.acf
    # TAIL, OO-PMA
    # DATE, 7/29/2025
    # PRES, 30.0
    # DISA, 0
    # WIND, 270, 2.61
    #
    header_out = False

    if self.lines[0] != "A":
      print(f"invalid X-Plane FDR file ({self.lines[0]})")
      return False

    if self.lines[1] not in ["3", "4"]:
      print(f"invalid X-Plane FDR file version ({self.lines[1]})")
      return False

    self.fdr_version = int(self.lines[1])
    print(f"FDR data format version {self.fdr_version}")

    i = 2
    data_index = 1
    while i < len(self.lines):
      if len(self.lines[i]) == 0:
        i += 1
        continue

      currline = self.lines[i]
      k, data, text = clean(currline)

      if k in HEADER_KEYWORDS:
        if k in self.meta:
          print(f"warning: header keyword {k} value overwritten {self.meta[k]} -> {currline[5:].strip()}")
        self.meta[k] = text
        i += 1
        continue
      elif k in DATA_KEYWORDS and k != "DATA":
        if k == "COMM":
          if text.startswith("FDRData("):
            try:
              print(text)
              fdrdata = eval(text)
              fdrdata.data_index = data_index
              data_index += 1
              self.fdr_data[fdrdata.name] = fdrdata
              # print(t)
            except:
              print("failed to eval(), skipped", text)
              print_exc()
            i += 1
            continue
        self.meta[k].append((self._last_ts, text))
        i += 1
        continue

      # else, probably data...
      # if first data encounted, hope last comment was column headings
      if not header_out and len(self.meta["COMM"]) > 0:
        if self.has_fdrdata:
          self.header = ["UTC Time"] + list(self.fdr_data.keys())
        else:
          self.header = [l.strip() for l in self.meta["COMM"][-1][1].split(",")]
        print(f"Header {', '.join(self.header)}")
        header_out = True

      if self.fdr_version == 3 and k == "DATA":
        self.data.append([l.strip() for l in data.split(",")])
      else:
        self.data.append([l.strip() for l in currline.split(",")])
      ts = datetime.strptime(self.data[-1][0].strip(), "%H:%M:%S.%f")
      self._last_ts = ts.replace(tzinfo=timezone.utc, day=self.basedate.day, month=self.basedate.month, year=self.basedate.year)
      i += 1

    if self.has_fdrdata:
    #   print(f"FDRData for {', '.join(self.fdr_data)}")
      if len(self.header) - 1 != len(self.fdr_data):
        print(f"Header column vs FDRData mismatch {len(self.header) - 1}/{len(self.fdr_data)}")

    if "DATE" in self.meta:
      self.basedate = datetime.strptime(self.meta["DATE"], "%m/%d/%Y").astimezone(tz=timezone.utc)
      print("Date:", self.basedate.isoformat())

    return True

  def properties(self, data) -> dict:
    props = {}
    for dref, v in zip(self.header[1:], data):
      if self.has_fdrdata:
        meta = self.fdr_data[dref]
        if meta.dtype == "int":
          props[dref] = int(float(v))
        elif meta.dtype == "float":
          props[dref] = float(v)
        else:
          props[dref] = v
      else:
        props[dref] = v
    return props # {self.header[i]: float(data[i].strip()) for i in range(1, len(data))}

  def to_geojson(self, outfile: str, altitude: bool = False, all_properties: bool = False):
    # Assumes all data are float except first one that is a timestamp
    # TS is datetime.now(datetime.UTC).strftime("%H:%M:%S.%f, ")
    features = []
    lines = []
    feature_index = 0
    for row in self.data:
      # coordinates
      p = [float(row[1]), float(row[2])]
      # altitude
      alt = None
      ele = self.fdr_data.get("ellipsoid_height")  # as requested by GeoJSON
      if ele is None:
          ele = self.fdr_data.get("elevation")  # MSL backup without ellipsoid
      if ele is None:
          ele = self.fdr_data.get("altitude")  # desperate
      if ele is not None:
        alt = float(row[ele.data_index]) / 3.28084
      if altitude and alt is not None:
        p.append(alt)
      lines.append(p)
      # time
      ts = datetime.strptime(row[0].strip(), "%H:%M:%S.%f")
      ts = ts.replace(tzinfo=timezone.utc, day=self.basedate.day, month=self.basedate.month, year=self.basedate.year)
      # properties
      props = {"id": feature_index, self.header[0]: ts.isoformat(), "_raw_ts": ts.timestamp()}
      if all_properties:
        props = props | self.properties(row[1:])
      else:
        spd = self.fdr_data.get("ground_speed")  # derivative, for information only
        if spd is not None:
          props = props | {"speed": float(row[spd.data_index]) }
        hdg = self.fdr_data.get("heading")  # derivative, for information only
        if hdg is not None:
          props = props | {"heading": float(row[hdg.data_index]) }
        if alt is not None:
          props = props | {"altidude":  alt}
      # feature
      features.append({
        "type": "Feature",
        "id": feature_index,
        "geometry": {
          "type": "Point",
          "coordinates": p
        },
        "properties": props
      })
      feature_index += 1

    # add whole line string
    feature_index += 1
    features.append({
      "type": "Feature",
      "id": feature_index,
      "geometry": {
        "type": "LineString",
        "coordinates": lines
      },
      "properties": {
        "name": "whole flight"
      }
     })

    with open(outfile, "w") as geoj:
        json.dump({
          "type": "FeatureCollection",
          "features": features
        }, geoj, indent=4)


# ######################################################
#
if __name__ == "__main__":
  if len(sys.argv) > 1:
    for file in sys.argv[1:]:
      a = FDRReader(filename=file)
      if a.parse():
        # print("Fields:", a.header)
        pprint(a.meta, width=120)
        a.to_geojson(outfile=f"{file}.geojson", altitude=True)
        print(f"{file}: {a.length} points written, duration={a.duration}")
      else:
        print(f"{file}: failed to parse")
  else:
      a = FDRReader()
      if a.parse():
        # print("Fields:", a.header)
        pprint(a.meta, width=120)
        a.to_geojson(outfile="out.geojson", altitude=True)
        print(f"out.geojson: {a.length} points written, duration={a.duration}")
      else:
        print("failed to parse")
