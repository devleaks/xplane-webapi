import re
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import List, Dict, Optional
from pprint import pprint

def add_optional(obj, name, d):
    if hasattr(obj, name):
        v = getattr(obj, name)
        if v is not None:
            if type(v) in [int, float, str]:
                d[name] = v
            else:
                d[name] = v.toDict()

def add_required(obj, name, d):
    if not hasattr(obj, name):
        raise ValueError
    v = getattr(obj, name)
    if v is None:
        raise ValueError
    if not hasattr(v, "toDict"):
        d[name] = v
    else:
        d[name] = v.toDict()

def ccname(name):
    # StartEngine -> start_engine
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

class TowType(StrEnum):
    TUG = "tug"
    WINCH = "winch"
    NONE = "none"


@dataclass
class Aircraft:
    path: str
    livery: Optional[str] = None

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "path", d)
        add_optional(self, "livery", d)
        return d


# START LOCATION
#
@dataclass
class RunwayStart:
    airport_id: str
    runway: str

    final_distance_in_nautical_miles: Optional[float] = None
    tow_type: TowType = TowType.NONE
    tow_aircraft: Optional[Aircraft] = None

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "airport_id", d)
        add_required(self, "runway", d)
        add_optional(self, "final_distance_in_nautical_miles", d)
        if self.tow_type != TowType.NONE:
            add_required(self, "tow_type", d)
        add_optional(self, "tow_aircraft", self.tow_aircraft)
        return d

@dataclass
class RampStart:
    airport_id: str
    ramp: str

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "airport_id", d)
        add_required(self, "ramp", d)
        return d


@dataclass
class GroundStart:
    latitude: float
    longitude: float
    heading_true: float

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "latitude", d)
        add_required(self, "longitude", d)
        add_required(self, "heading_true", d)
        return d


class Speed(StrEnum):
    SHORT_FIELD = "short_field_approach"
    NORMAL = "normal_approach"
    CRUISE = "cruise"


@dataclass
class AirStart:
    latitude: float
    longitude: float
    heading_true: float
    elevation_in_meters: float
    speed_in_meter_per_second: Optional[float] = None
    speed_enum: Speed | None = None
    pitch_in_degree: Optional[float] = None

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "latitude", d)
        add_required(self, "longitude", d)
        add_required(self, "elevation_in_meters", d)
        add_required(self, "heading_true", d)
        add_optional(self, "speed_in_meter_per_second", d)
        if self.speed_in_meter_per_second is None:
            add_optional(self, "speed_enum", d)
        else:
            add_optional(self, "speed_in_meter_per_second", d)
        add_optional(self, "pitch_in_degree", d)
        return d


@dataclass
class BoatLocation:
    latitude: float
    longitude: float

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "latitude", d)
        add_required(self, "longitude", d)
        return d



@dataclass
class BoatStart:
    boat_name: str

    boat_location: Optional[BoatLocation] = None
    start_position: Optional[str] = None
    final_distance_in_nautical_miles: Optional[float] = None

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "boat_name", d)
        add_optional(self, "boat_location", d)
        add_optional(self, "start_position", d)
        add_optional(self, "final_distance_in_nautical_miles", d)
        return d



# WEIGHT
#
@dataclass
class SlungLoad:
    path_to_obj: str
    weight_in_kilograms: float

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "path_to_obj", d)
        add_required(self, "weight_in_kilograms", d)


@dataclass
class Weight:
    payload_weight_in_kilograms: List[float]
    fueltank_weight_in_kilograms: List[float]

    jato_weight_in_kilograms: Optional[float] = None
    slung_load: Optional[SlungLoad] = None
    jettisonable_weight_in_kilograms: Optional[float] = None
    shiftable_weight_in_kilograms: Optional[float] = None
    deice_holdover_time_in_minutes: Optional[float] = None
    oxygen_pressure_in_millibars: Optional[float] = None
    deice_fluid_in_liters: Optional[float] = None
    external_fueltank_weight_in_kilograms: List[float] = field(default_factory=lambda: [])

    def toDict(self) -> Dict:
        d = {}
        add_required(self, "payload_weight_in_kilograms", d)
        add_required(self, "fueltank_weight_in_kilograms", d)
        add_optional(self, "jato_weight_in_kilograms", d)
        add_optional(self, "slung_load", d)
        add_optional(self, "jettisonable_weight_in_kilograms", d)
        add_optional(self, "shiftable_weight_in_kilograms", d)
        add_optional(self, "deice_holdover_time_in_minutes", d)
        add_optional(self, "oxygen_pressure_in_millibars", d)
        add_optional(self, "deice_fluid_in_liters", d)
        if self.external_fueltank_weight_in_kilograms is not None and len(self.external_fueltank_weight_in_kilograms) > 0:
            add_required(self, "external_fueltank_weight_in_kilograms", d)
        return d



# ENGINES
#
@dataclass
class EngineStatus:
    running: bool

    def toDict(self) -> Dict:
        return {"running": self.running}


@dataclass
class Engine:
    all_engine: EngineStatus

    def toDict(self) -> Dict:
        return {"all_engine": self.all_engine.toDict()}


# WEAPONS
#
@dataclass
class Weapon:
    index: int
    filename: str

    def toDict(self) -> Dict:
        return {"index": self.index, "filename":self.filename}


# FAILURES
#
class FailureStatus(StrEnum):
    ALWAYS_WORK = "always_work"
    FAIL_MEAN_TIME_IN_HOURS = "fail_mean_time_in_hours"
    FAIL_EXACT_TIME_IN_HOURS = "fail_exact_time_in_hours"
    FAIL_AT_SPEED_IN_KNOTS = "fail_at_speed_in_knots"
    FAIL_AT_ALTITUDE_IN_FEET = "fail_at_altitude_in_feet"
    FAIL_AT_COMMAND_TRIGGER = "fail_at_command_trigger"
    INOPERATIVE = "inoperative"


@dataclass
class Failure:
    name: str
    status: str
    value: float = 0.0

    def toDict(self) -> Dict:
        return {"name": self.name, "status":self.status, "value":self.value}


@dataclass
class Failures:
    fix_everything: Optional[bool] = None
    mean_time_between_failures_in_hours: Optional[float] = None
    operation_failures: Optional[List[Failure]] = None

    def toDict(self) -> Dict:
        d = {}
        add_optional(self, "fix_everything", d)
        add_optional(self, "mean_time_between_failures_in_hours", d)
        if self.operation_failures is not None and len(self.operation_failures) > 0:
            d["operation_failures"] = [l.toDict() for l in self.operation_failures]
        return d

# AI Aircraft, GAME
#
class Mission(StrEnum):
    ATC = "atc"
    COMBAT_TEAM_RED = "combat_team_red"
    COMBAT_TEAM_BLUE = "combat_team_blue"
    COMBAT_TEAM_GREEN = "combat_team_green"
    COMBAT_TEAM_GOLD = "combat_team_gold"


@dataclass
class AIAircraft:
    aircraft: Aircraft
    mission: Mission

    def toDict(self) -> Dict:
        return {
            "aircraft": self.aircraft.toDict(),
            "mission":self.mission
        }

@dataclass
class FormationAircraft:
    path: str

    def toDict(self) -> Dict:
        return {"path": self.path}

class IncursionType(StrEnum):
    FLIGHT_INCURSION = "flight_incursion"
    RUNWAY_INCURSION_ARM = "runway_incursion_arm"
    RUNWAY_INCURSION_EXECUTE = "runway_incursion_execute"
    CLEAR_INCURSION = "clear_incursion"

@dataclass
class Incursion:
    aircraft: Aircraft
    type: IncursionType

    def toDict(self) -> Dict:
        return {
            "aircraft": self.aircraft.toDict(),
            "type":self.typ
        }


# ENVIRONMENT - TIME
#
class Time:  # ABC
    pass

@dataclass
class YearTime(Time):  # ABC
    day_of_year: int
    time_in_24_hours: float  # Time of day in hours (e.g., 13.5 = 1:30 PM)

    def toDict(self) -> Dict:
        return {
            "day_of_year": self.day_of_year,
            "time_in_24_hours": self.time_in_24_hours
        }

@dataclass
class GmtTime(YearTime):
    pass

@dataclass
class LocalTime(YearTime):
    pass

@dataclass
class UseSystemTime(Time):

    def toDict(self) -> Dict:
        return True


class TimePreset(StrEnum):
    DAY = "day"
    SUNSET = "sunset"
    EVENING = "evening"
    NIGHT = "night"

@dataclass
class PresetTime(Time):
    preset: TimePreset

    def toDict(self) -> Dict:
        return {
            "preset": self.preset
        }


# ENVIRONMENT - WEATHER
#
class WeatherPreset(StrEnum):
    VFR_FEW_CLOUDS = "vfr_few_clouds"
    VFR_SCATTERED = "vfr_scattered"
    VFR_BROKEN = "vfr_broken"
    MARGINAL_VFR_OVERCAST = "marginal_vfr_overcast"
    IFR_NON_PRECISION = "ifr_non_precision"
    IFR_PRECISION = "ifr_precision"
    CONVECTIVE = "convective"
    LARGE_CELL_THUNDERSTORM = "large_cell_thunderstorm"


class WeatherEvolution(StrEnum):
    RAPIDLY_IMPROVING = "rapidly_improving"
    IMPROVING = "improving"
    GRADUALLY_IMPROVING = "gradually_improving"
    STATIC = "static"
    GRADUALLY_DETERIORATING = "gradually_deteriorating"
    DETERIORATING = "deteriorating"
    RAPIDLY_DETERIORATING = "rapidly_deteriorating"


class TerrainState(StrEnum):
    DRY = "dry"
    LIGHTLY_WET = "lightly_wet"
    MEDIUM_WET = "medium_wet"
    VERY_WET = "very_wet"
    LIGHTLY_PUDDLY = "lightly_puddly"
    MEDIUM_PUDDLY = "medium_puddly"
    VERY_PUDDLY = "very_puddly"
    LIGHTLY_SNOWY = "lightly_snowy"
    MEDIUM_SNOWY = "medium_snowy"
    VERY_SNOWY = "very_snowy"
    LIGHTLY_ICY = "lightly_icy"
    MEDIUM_ICY = "medium_icy"
    VERY_ICY = "very_icy"
    LIGHTLY_SNOWY_AND_ICY = "lightly_snowy_and_icy"
    MEDIUM_SNOWY_AND_ICY = "medium_snowy_and_icy"
    VERY_SNOWY_AND_ICY = "very_snowy_and_icy"


class UseRealWeather(StrEnum):
    USE_REAL_WEATHER = "use_real_weather"


class CloudType(StrEnum):
    CIRRUS = "cirrus"
    STRATUS = "stratus"
    CUMULUS = "cumulus"
    CUMULUNIMBUS = "cumulunimbus"


@dataclass
class CloudLayer:
    type: CloudType
    cover_ratio: float
    bases_in_feet_msl: float
    tops_in_feet_msl: float

    def toDict(self) -> Dict:
        return {
            "type": self.type,
            "cover_ratio": self.cover_ratio,
            "bases_in_feet_msl": self.bases_in_feet_msl,
            "tops_in_feet_msl": self.tops_in_feet_ms
        }


@dataclass
class WindLayer:
    altitude_in_feet_msl: float
    speed_in_knots: float
    direction_in_degrees_true: float

    gust_increase_in_knots: Optional[float] = None
    shear_in_degrees: Optional[float] = None
    turbulence_ratio: Optional[float] = None

    def toDict(self) -> Dict:
        d = {
            "altitude_in_feet_msl": self.altitude_in_feet_msl,
            "speed_in_knots": self.speed_in_knots,
            "direction_in_degrees_true": self.direction_in_degrees_true
        }
        add_optional(self, "gust_increase_in_knots", d)
        add_optional(self, "shear_in_degrees", d)
        add_optional(self, "turbulence_ratio", d)
        return d


@dataclass
class WeatherDefinition:
    latitude_in_degrees: float
    longitude_in_degrees: float
    elevation_in_meters: float
    visibility_in_kilometers: float

    temperature_in_degrees_celsius: Optional[float] = None
    altimeter_setting_in_hpa: Optional[float] = None
    precipitation_ratio: Optional[float] = None
    cloud_layers: Optional[List[CloudLayer]] = None
    wind_layers: Optional[List[WindLayer]] = None

    def toDict(self) -> Dict:
        d = {
            "latitude_in_degrees": self.latitude_in_degrees,
            "longitude_in_degrees": self.longitude_in_degrees,
            "elevation_in_meters": self.elevation_in_meters,
            "visibility_in_kilometers": self.visibility_in_kilometers
        }
        add_optional(self, "temperature_in_degrees_celsius", d)
        add_optional(self, "altimeter_setting_in_hpa", d)
        add_optional(self, "precipitation_ratio", d)
        if self.wind_layers is not None and len(self.cloud_layers) > 0:
            d["cloud_layers"] = [l.toDict() for l in self.cloud_layers]
        if self.cloud_layers is not None and len(self.wind_layers) > 0:
            d["wind_layers"] = [l.toDict() for l in self.wind_layers]
        return d


@dataclass
class WeatherScenario:
    definition: WeatherPreset | WeatherDefinition
    vertical_speed_in_thermal_in_feet_per_minute: float
    wave_height_in_meters: float
    wave_direction_in_degrees: float
    terrain_state: TerrainState
    variation_across_region_percentage: float
    evolution_over_time_enum: WeatherEvolution

    def toDict(self) -> Dict:
        d = {
            "definition": self.definition.value if type (self.definition) is WeatherPreset else self.definition.toDict(),
            "vertical_speed_in_thermal_in_feet_per_minute": self.vertical_speed_in_thermal_in_feet_per_minute,
            "wave_height_in_meters": self.wave_height_in_meters,
            "wave_direction_in_degrees": self.wave_direction_in_degrees,
            "terrain_state": self.terrain_state.value,
            "evolution_over_time_enum": self.evolution_over_time_enum.value,
        }
        return d


@dataclass
class Weather:
    weather: UseRealWeather | WeatherScenario

    def toDict(self) -> Dict:
        if type(self.weather) is UseRealWeather:
            return self.weather.value
        return self.weather.toDict()


# FLIGHT
#
@dataclass
class Flight:
    aircraft: Aircraft
    start_location: RunwayStart | RampStart | GroundStart | AirStart | BoatStart
    time: GmtTime | LocalTime | PresetTime | UseSystemTime
    weather: Weather
    weight: Weight
    engine_status: Engine
    failures: Failures | None = None
    ai_aircraft: List[AIAircraft] | None = None
    formation_aircraft: FormationAircraft | None = None
    incursion: Incursion | None = None
    weapons: List[Weapon] | None = None

    update: bool = False  # set it to True if Flight is an update of existing flight

    def toDict(self) -> Dict:
        d = {}

        # Aircraft
        if not self.update:
            add_required(self, "aircraft", d)
        add_required(self, "weight", d)
        add_required(self, "engine_status", d)
        add_optional(self, "failures", d)

        # Location
        if not self.update:
            d = d | {ccname(type(self.start_location).__name__): self.start_location.toDict()}

        # Environment
        d = d | {ccname(type(self.time).__name__): self.time.toDict()}
        add_required(self, "weather", d)

        # Game stuff: Failures, AI aircrafts, etc.
        add_optional(self, "formation_aircraft", d)
        add_optional(self, "incursion", d)
        if self.ai_aircraft is not None and len(self.ai_aircraft) > 0:
            d["ai_aircraft"] = [l.toDict() for l in self.ai_aircraft]
        if self.weapons is not None and len(self.weapons) > 0:
            d["weapons"] = [l.toDict() for l in self.weapons]

        return d

    def start(self, api):
        self.update = False
        api.start_flight(flight=self)

    def update(self, api):
        self.update = True
        api.update_flight(flight=self)

# TESTS
#
# Minimal
if __name__ == "__main__":
    print(json.dumps(Flight(
        # Aircraft
        # update=True,
        aircraft=Aircraft(path="Aircraft/Airbus/ToLiss A321/a321.acf"),
        engine_status=Engine(all_engine=EngineStatus(running=True)),
        weight=Weight(payload_weight_in_kilograms=[4200, 1000], fueltank_weight_in_kilograms=[5000, 2000]),
        # failures=Failures(mean_time_between_failures_in_hours=0.25, operation_failures=[Failure(name="engine1", status="false", value=1.0)]),
        # Location
        start_location=RunwayStart(airport_id="EBBR", runway="27R"),
        # Environment
        time=UseSystemTime(),
        weather=Weather(weather=UseRealWeather.USE_REAL_WEATHER),
        # weather=Weather(
        #     weather=WeatherScenario(
        #         definition=WeatherPreset.VFR_FEW_CLOUDS,
        #         vertical_speed_in_thermal_in_feet_per_minute=250,
        #         wave_height_in_meters=2,
        #         wave_direction_in_degrees=200,
        #         terrain_state=TerrainState.DRY,
        #         variation_across_region_percentage=100,
        #         evolution_over_time_enum=WeatherEvolution.STATIC,
        #     )
        # ),
        # weather=Weather(
        #     weather=WeatherScenario(
        #         definition=WeatherDefinition(
        #             latitude_in_degrees=123.3,
        #             longitude_in_degrees=41.5,
        #             elevation_in_meters=173,
        #             visibility_in_kilometers=12.5,
        #             temperature_in_degrees_celsius=21
        #         ),
        #         vertical_speed_in_thermal_in_feet_per_minute=250,
        #         wave_height_in_meters=2,
        #         wave_direction_in_degrees=200,
        #         terrain_state=TerrainState.DRY,
        #         variation_across_region_percentage=100,
        #         evolution_over_time_enum=WeatherEvolution.STATIC,
        #     )
        # ),
        # ai_aircraft=[AIAircraft(aircraft=Aircraft(path="A350"), mission=Mission.ATC)],
        # Game stuff: AI aircrafts, etc.
        ).toDict(), indent=4))

###########