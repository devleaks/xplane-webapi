import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import List


class TowType(StrEnum):
    TUG = "tug"
    WINCH = "winch"
    NONE = "none"


@dataclass
class Aircraft:
    path: str
    livery: str = ""


# START LOCATION
#
@dataclass
class RunwayStart:
    airport_id: str
    runway: str

    final_distance_in_nautical_miles: float = 0.0
    tow_type: TowType = TowType.NONE
    tow_aircraft: Aircraft | None = None


@dataclass
class RampStart:
    airport_id: str
    ramp: str


@dataclass
class GroundStart:
    latitude: float
    longitude: float
    heading_true: float


class Speed(StrEnum):
    SHORT_FIELD: "short_field_approach"
    NORMAL: "normal_approach"
    CRUISE: "cruise"


@dataclass
class AirStart:
    latitude: float
    longitude: float
    heading_true: float
    elevation_in_meters: float
    speed_in_meter_per_second: float
    speed_enum: Speed | None = None
    pitch_in_degree: float = 0.0


@dataclass
class BoatLocation:
    latitude: float
    longitude: float


@dataclass
class BoatStart:
    boat_name: str

    boat_location: BoatLocation | None = None
    start_position: str = ""
    final_distance_in_nautical_miles: float = 0.0


# WEIGHT
#
@dataclass
class SlungLoad:
    path_to_obj: str
    weight_in_kilograms: float


@dataclass
class Weight:
    payload_weight_in_kilograms: List[float]
    fueltank_weight_in_kilograms: List[float]

    jato_weight_in_kilograms: float = 0.0
    slung_load: SlungLoad | None = None
    jettisonable_weight_in_kilograms: float = 0.0
    shiftable_weight_in_kilograms: float = 0.0
    deice_holdover_time_in_minutes: float = 0.0
    oxygen_pressure_in_millibars: float = 0.0
    deice_fluid_in_liters: float = 0.0
    external_fueltank_weight_in_kilograms: List[float] = field(default_factory=lambda: [])


# ENGINES
#
@dataclass
class EngineStatus:
    running: bool


@dataclass
class Engine:
    all_engine: EngineStatus


# WEAPONS
#
@dataclass
class Weapon:
    index: int
    filename: str


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


@dataclass
class Failures:
    fix_everything: bool = True
    mean_time_between_failures_in_hours: float = 0.0
    operation_failures: List[Failure] = field(default_factory=lambda: [])


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


@dataclass
class FormationAircraft:
    path: str


class IncursionType(StrEnum):
    FLIGHT_INCURSION = "flight_incursion"
    RUNWAY_INCURSION_ARM = "runway_incursion_arm"
    RUNWAY_INCURSION_EXECUTE = "runway_incursion_execute"
    CLEAR_INCURSION = "clear_incursion"

@dataclass
class Incursion:
    aircraft: Aircraft
    type: IncursionType


# ENVIRONMENT - TIME
#
@dataclass
class Time:
    day_of_year: int
    time_in_24_hours: float  # Time of day in hours (e.g., 13.5 = 1:30 PM)


@dataclass
class GMTTime(Time):
    type: str = "GMT"


@dataclass
class LocalTime(Time):
    type: str = "local"


@dataclass
class SystemTime(Time):
    use_system_time: bool = True


class TimePreset(StrEnum):
    DAY = "day"
    SUNSET = "sunset"
    EVENING = "evening"
    NIGHT = "night"

@dataclass
class PresetTime(Time):
    preset: TimePreset


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


@dataclass
class WindLayer:
    altitude_in_feet_msl: float
    speed_in_knots: float
    direction_in_degrees_true: float

    gust_increase_in_knots: float = 0.0
    shear_in_degrees: float = 0.0
    turbulence_ratio: float = 0.0


@dataclass
class WeatherDefinition:
    latitude_in_degrees: float
    longitude_in_degrees: float
    elevation_in_meters: float
    visibility_in_kilometers: float

    temperature_in_degrees_celsius: float = 0.0
    altimeter_setting_in_hpa: float = 0.0
    precipitation_ratio: float = 0.0
    cloud_layers: List[CloudLayer] = field(default_factory=lambda: [])  # 0-3
    wind_layers: List[WindLayer] = field(default_factory=lambda: [])   # 0-13


@dataclass
class WeatherScenario:
    definition: WeatherPreset | WeatherDefinition
    vertical_speed_in_thermal_in_feet_per_minute: float
    wave_height_in_meters: float
    wave_direction_in_degrees: float
    terrain_state: TerrainState
    variation_across_region_percentage: float
    evolution_over_time_enum: WeatherEvolution


@dataclass
class Weather:
    weather: UseRealWeather | WeatherScenario


# FLIGHT
#
@dataclass
class Flight:
    aircraft: Aircraft
    start_location: RunwayStart | RampStart | GroundStart | AirStart | BoatStart
    time: GMTTime | LocalTime | PresetTime | SystemTime
    weather: Weather
    weight: Weight
    engine_status: EngineStatus
    failures: Failures | None = None
    ai_aircraft: List[AIAircraft] | None = None
    formation_aircraft: FormationAircraft | None = None
    incursion: Incursion | None = None
    weapons: List[Weapon] | None = None

    def __str__(self):
        s = dict()
        s["aircraft"] = self.aircraft
        return json.dumps(s)



# TEST
#
print(Flight(
    aircraft=Aircraft(path="airbus/a320.acf"),
    start_location=RunwayStart(airport_id="EBBR", runway="27R"),
    time=LocalTime(day_of_year=123, time_in_24_hours=9.50),
    engine_status=None,
    weather=None,
    weight=None
    )
)



###########