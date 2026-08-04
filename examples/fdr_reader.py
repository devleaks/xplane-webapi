from pprint import pprint
import json
from datetime import datetime, timedelta, timezone

COMMENTS = "COMM"

VALID_KEYWORDS = [
  "ACFT",
  "TAIL",
  "DATE",
  "PRES",
  "DISA",
  "WIND",
]

class FDRReader:

  def __init__(self, filename: str) -> None:
    self.filename = filename

    with open(self.filename) as fp:
      self.lines = [l.strip() for l in fp.readlines()]

    self.basedate = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone()
    self.meta = {
      COMMENTS: []
    }
    self.header = []
    self.data = []

  @property
  def duration(self) -> timedelta:
    if len(self.data) > 1:
      return datetime.strptime(self.data[-1][0].strip(), "%H:%M:%S.%f") - datetime.strptime(self.data[0][0].strip(), "%H:%M:%S.%f")
    return timedelta(0)

  @property
  def length(self) -> int:
    return len(self.data)

  def parse(self) -> bool:
    #
    # ACFT, Aircraft/Airbus/ToLiss A321/a321.acf
    # TAIL, OO-PMA
    # DATE, 7/29/2025
    # PRES, 30.0
    # DISA, 0
    # WIND, 270, 2.61
    #
    last_comm = None

    if self.lines[0] != "A":
      print(f"invalid X-Plane FDR file ({self.lines[0]})")
      return False

    if self.lines[1] not in ["3", "4"]:
      print(f"invalid X-Plane FDR file version ({self.lines[1]})")
      return False

    i = 2
    while i < len(self.lines):
      if len(self.lines[i]) == 0:
        i += 1
        continue
      if self.lines[i].startswith("COMM,"):
        last_comm = self.lines[i]
        self.meta[COMMENTS].append(self.lines[i][5:].strip())
        i += 1
        continue

      if len(self.lines[i]) > 5 and self.lines[i][4] == ",":
        k = self.lines[i][:4]
        if k in VALID_KEYWORDS:
          if k in self.meta:
            print(f"warning: keyword {k} overwritten")
          self.meta[k] = self.lines[i][5:].strip()
        i += 1
        continue

      # else, probably data...
      if last_comm is not None:
        self.header = [l.strip() for l in last_comm[5:].split(",")]
        last_comm = None

      self.data.append([l.strip() for l in self.lines[i].split(",")])
      i += 1

    if "DATE" in self.meta:
      self.basedate = datetime.strptime(self.meta["DATE"], "%m/%d/%Y")
      print("Date:", self.basedate)

    return True

  def to_geojson(self, outfile: str):
    # Assumes all data are float except first one that is a timestamp
    # TS is datetime.now(datetime.UTC).strftime("%H:%M:%S.%f, ")
    features = []
    lines = []
    for row in self.data:
      p = [float(row[1]), float(row[2])]
      lines.append(p)
      ts = datetime.strptime(row[0].strip(), "%H:%M:%S.%f")
      ts = ts.replace(tzinfo=timezone.utc, day=self.basedate.day, month=self.basedate.month, year=self.basedate.year)
      features.append({
        "type": "Feature",
        "geometry": {
          "type": "Point",
          "coordinates": p,
          "properties": {self.header[0]: ts.isoformat()} | {self.header[i]: float(row[i].strip()) for i in range(1, len(row))}
        }
      })

    # add whole line string
    features.append({
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "LineString",
        "coordinates": lines
      }
     })

    with open(outfile, "w") as geoj:
        json.dump({
          "type": "FeatureCollection",
          "features": features
        }, geoj, indent=4)


a = FDRReader("test1.fdr")
if a.parse():
  print("Fields:", a.header)
  pprint(a.meta)
  a.to_geojson(outfile="test1.geojson")
  print(f"{a.length} points written, duration={a.duration}")
else:
  print("failed to parse")