# Flight Data Recorder for X-Plane

Flight Data Recorder is a customizable flight data recording plugin for X-Plane flight simulator.
It generates X-Plane FDR files (version 3 or 4) from a running flight.


## Recording

The plugin installs a permanent supervisor procedure that determines if the FDR recording needs to occur.
It automatically starts when a movement is detected, it stops when there is no movement for 10 minutes.

Alternatively, it is possible to manually start and stop the recording through the _Start or stop FDR_ Plugin Menu entry.
An _enabled_ marker (white dot) sits in front of the menu entry when the recorder is running.

It is possible to bind the _Start or stop FDR_ command to a cockpit or joystick button.


## Output

FDR recording files are stored in the `<X-Plane 12 Folder>/Output/fdr/` folder.
Files are named after the start time of the record.


### FDR Meta Data

In addition to mandatory information in the record file,
FDR stores meta data information for further processing and handling.
Meta data is saved as a FDR record COMMent and can be ignored.

Meta Data is used, for example, by the FDR reader.

`fdr_info` information fields are also recorded as meta data in the header of the FDR file.

In the FDR record file, the recorder attempt to write
  - A list of columns for a record
  - The corresponding list of units used for each column.
Information is written as a comment before the data records.


## Recording Preferences

FDR first look for a aircraft specific FDR preference file in the home directory of an aircraft
`<X-Plane 12 Folder>/Aircraft/.../myaircraft/fdr.prf`.
This allows for recording aircraft-specific data.

Preferences are looked up again when aircraft is changed.

IF no aircraft specific preference file is found, FDR look in X-Plane Preference folder
`<X-Plane 12 Folder>/Output/preferences/fdr.prf`.

The preference file is a Yaml-formatted readable text file structured as follow:

```yaml
fdr_version: 4
fdr_arch: APPLE
description: Demonstration preference file
frequency: 5
report_frequency: 200
chocks: AirbusFBW/Chocks
fdr_info:
  - name: ICAO
    dataref: sim/aircraft/view/acf_ICAO
fdr_optional:
  - name: ground_speed
    dataref: sim/flightmodel/position/groundspeed
    unit: m/s
  - name: true_air_speed
    dataref: sim/flightmodel/position/true_airspeed
    unit: m/s
  - name: v_speed
    dataref: sim/cockpit2/gauges/indicators/vvi_fpm_pilot
    unit: m/s # dataref is ft/min, converted by callback
    callback: "lambda x: x * 0,00508"
```

`fdr_version` identifies the version of the recording file that is generated. Version 3 and 4 are supported.

`fdr_arch` identifies the FDR file architecture, either APPLE or IBM. Used to determine line termitors.

`description` is an information field used in the log file to identify the preferences used.

`frequency` is the time, in seconds, between 2 data collection.

`report_frequency` is the number of data collections reported in the log file. It allows for simple monitoring of the data collection process.

`chocks` is a dataref name that will be used to check whether chocks are set (non zero value) or not (zero value).

`fdr_info` is a list of data structure to identy a dataref value that is fetched *once* only at the start of the recording. The value is saved as a comment in the header file of the recording.

Example of FDR info fields may include departure and arrival airport, weather information...
as long as the data is available as a dataref.

`fdr_optional` is a list of data structure that are collected and reported.


### Collected Data Structure

Collected data is described by the following fields:
  - `name`: Name of the data field, used as a column header in the FDR file. Mandatory.
  - `dataref`: Name of dataref whose value is part of the data record. Mandatory.
  - `units`: Information field of dataref value unit. Saved as a comment in the header of the record file. Optional.
  - `factor`: Convertion factor (float value) used by FDR DREF parameter. Optional.
  - `callback`: very short python lambda expression to convert dataref value before it is saved to the record. Optional.

Callback expression is very limited in size and capabilities.
Their goal is a provide an easy mechanism to alter raw dataref values to meaningful record value
with minimal modification.

Typical, unit adjustment expressions like

```python
lambda x: x * 0.3048  # convert ft to m
lambda x: (x - 32) / 1.8  # convert farenheit to celsius
lambda x: round(x) == 0 # returns boolean value True when rounds to zero
lambda x: "on" if x == 1 else "off" # returns string value on/off
```

are harmless. (In the above expression x is the raw dataref value.)

Expression must be simple and short.
No python package can be used in expression.
Callback shall be used very cautiously as it may crash both FDR and X-Plane.
In a later release FDR may change for a more robust callback expression mechanism.

It is a alternate, more sophisticated method to FDR DREF factor parameter.


### Default Values

Without preference file, FDR generates Version 4 file for APPLE architecture.
The recording frequency is 10 seconds, and reporting frequency occurs every 200 records.
It only record mandatory data (position, attitude) and header fields once.
It is a lightweight process that has no impact on the frame rate.

This occurs automatically without user interaction.


### Mandatory Data

FDR collects the following data which is required in the header of the FDR file:
  - `ACFT`: the aircraft file to use, with full directory path from the X-Plane folder
    (ex: `Aircraft/Heavy Metal/Boeing 747.acf`).
  - `TAIL`: tail number of the aircraft (ex: `N8141Q`). Must come immediately after the `ACFT` line.
  - `TIME`: ZULU time of the beginning of the flight (ex: `18:54:32`).
  - `DATE`: date of the flight (ex: `03/05/02`).
  - `PRES`: sea-level pressure during the flight in inches HG (ex: `29.92`).
  - `TEMP`: sea-level temperatre during the flight in degrees farenheit (ex: `65`).
  - `WIND`: wind during th flight in degrees then knots (ex: `230,17`).


FDR collects the following data which is required in the FDR file:
  - UTC time of day with fractional second if available
  - longitude
  - latitude
  - altitude
  - heading
  - pitch
  - roll

`fdr_optional` data is saved after these mandatory values.


## Installation

Flight Data Recorder is a X-Plane plugin written in python.
It needs XPPython3 plugin to run.

Install `PI_fdr.py` file in `<X-Plane 12 Folder>/Resources/plugins/PythonPlugins`.
Reload scripts in XPPython3.


## Reader

There is a compagnon script fdr_reader that reads a FDR record file and generates
a GeoJSON file that can be viewed on geojson.io for example.

Column data is presented as a list of GeoJSON properties along with (3D) position.


## Troubleshooting

FDR logs a few messages in X-Plane `log.txt` file.

If constant TRACE is set to True in the `PI_fdr.py` script file, more information is produced.


# See Also

  - `<X-Plane 12 Folder>/Instruction/FDR Example Version 3.fdr`
  - `<X-Plane 12 Folder>/Instruction/FDR Example Version 4.fdr`
