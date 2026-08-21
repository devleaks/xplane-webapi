import re
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import List, Dict, Optional
from pprint import pprint


@dataclass
class FlightABC:
    """Abstract class for required/optional Flight API entities

    This base class is capable of automatically generate JSON API data
    from flight specification, whether required or optional.
    Issue ValueError if required parameters not present.
    """

    def add(self, d:dict, name:str, value):
        if name in ["start_location", "time"]:
            n = re.sub(r'(?<!^)(?=[A-Z])', '_', type(value).__name__).lower()
            d.update({n: value.toDict()})
            return
        if isinstance(value, StrEnum):
            value = value.value
        if hasattr(value, "toDict"):
            value = value.toDict()
        d[name] = value

    def add_optional(self, name: str, d: dict):
        """Add optional value if present. Ignore if value is None.

        Args:
            name (str): name of optional parameter
            d (dict): dictionary where to add the value
        """
        if not hasattr(self, name):
            return
        v = getattr(self, name)
        if v is not None:
            self.add(d, name, v)

    def add_required(self, name: str, d: dict):
        """Add required value. Complains if value is None or missing.

        Args:
            name (str): name of required parameter
            d (dict): dictionary where to add the value
        """
        if not hasattr(self, name):
            raise ValueError
        v = getattr(self, name)
        if v is None:
            raise ValueError
        self.add(d, name, v)

    def toDict(self):
        """Creates a new dictionary of name, value pairs
           for all attributes of the dataclass.

        Returns:
            [dict]: Dictionary of name, value pairs
        """
        d = {}
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            if f.default is None:
                self.add_optional(f.name, d)
            else:
                self.add_required(f.name, d)
        return d


@dataclass
class Aircraft(FlightABC):
    """Aircraft specification for flight

    Attributes:
        path: str: Operating system path file from X-Plane 12 root folder
        livery: Optional livery (folder) name
    """
    path: str

    livery: Optional[str] = None

# START LOCATION
#
class TowType(StrEnum):
    """Tow mode enumaration

    Attributes:
        TUG: Tow truck or equivalent
        WINCH: Tow winch (sail planes)
        NONE: No towing device
    """
    TUG = "tug"
    WINCH = "winch"
    NONE = "none"


@dataclass
class RunwayStart(FlightABC):
    """Start from runway end

    Attributes:
        airport_id: ICAO code of airport
        runway: Runway name like 07L

        final_distance_in_nautical_miles: Optional
        tow_type: Optional
        tow_aircraft: Optional
    """
    airport_id: str
    runway: str

    final_distance_in_nautical_miles: Optional[float] = None
    tow_type: TowType = TowType.NONE
    tow_aircraft: Optional[Aircraft] = None


@dataclass
class RampStart(FlightABC):
    """Start from airport ramp

    Attributes:
        airport_id: ICAO code of airport
        ramp: Ramp name as string "161"
    """
    airport_id: str
    ramp: str


@dataclass
class GroundStart(FlightABC):
    """Start from ground position

    Attributes:
        latitude: Required
        longitude: Required
        heading_true: Required
    """
    latitude: float
    longitude: float
    heading_true: float


class Speed(StrEnum):
    """Speed category/description enumeration
    """
    SHORT_FIELD = "short_field_approach"
    NORMAL = "normal_approach"
    CRUISE = "cruise"


@dataclass
class AirStart(FlightABC):
    """Start from position in the air.

    Attributes:
        latitude: Required
        longitude: Required
        heading_true: Required
        elevation_in_meters: Required
        speed_in_meter_per_second: Required
        speed_enum: Required
        pitch_in_degree: Required
    """
    latitude: float
    longitude: float
    heading_true: float
    elevation_in_meters: float

    speed_in_meter_per_second: Optional[float] = None
    speed_enum: Optional[Speed] = None
    pitch_in_degree: Optional[float] = None


@dataclass
class BoatLocation(FlightABC):
    """Boat location

    Attributes:
        latitude: Required
        longitude: Required
    """
    latitude: float
    longitude: float


@dataclass
class BoatStart(FlightABC):
    """Start from boat location

    Attributes:
        boat_name: Required
        boat_location: Optional
        start_position: Optional
        final_distance_in_nautical_miles: Optional
    """
    boat_name: str

    boat_location: Optional[BoatLocation] = None
    start_position: Optional[str] = None
    final_distance_in_nautical_miles: Optional[float] = None


# WEIGHT
#
@dataclass
class SlungLoad(FlightABC):
    """Slung load description and weight

    Attributes:
        path_to_obj: [description]
        weight_in_kilograms: [description]
    """
    path_to_obj: str
    weight_in_kilograms: float



@dataclass
class Weight(FlightABC):
    """Aircraft weights

    Attributes:
        payload_weight_in_kilograms: List, required
        fueltank_weight_in_kilograms: List, required
        jato_weight_in_kilograms: Optional
        slung_load: Optional
        jettisonable_weight_in_kilograms: Optional
        shiftable_weight_in_kilograms: Optional
        deice_holdover_time_in_minutes: Optional
        oxygen_pressure_in_millibars: Optional
        deice_fluid_in_liters: Optional
        external_fueltank_weight_in_kilograms: List, optional
    """
    payload_weight_in_kilograms: List[float]
    fueltank_weight_in_kilograms: List[float]

    jato_weight_in_kilograms: Optional[float] = None
    slung_load: Optional[SlungLoad] = None
    jettisonable_weight_in_kilograms: Optional[float] = None
    shiftable_weight_in_kilograms: Optional[float] = None
    deice_holdover_time_in_minutes: Optional[float] = None
    oxygen_pressure_in_millibars: Optional[float] = None
    deice_fluid_in_liters: Optional[float] = None
    external_fueltank_weight_in_kilograms: Optional[List[float]] = None


# ENGINES
#
@dataclass
class EngineStatus(FlightABC):
    """Single engine status

    Attributes:
        running: Whether engine is running
    """
    running: bool


@dataclass
class Engine(FlightABC):
    all_engines: EngineStatus


# WEAPONS
#
@dataclass
class Weapon(FlightABC):
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
class Failure(FlightABC):
    name: str
    status: str
    value: float = 0.0


@dataclass
class Failures(FlightABC):
    fix_everything: Optional[bool] = None
    mean_time_between_failures_in_hours: Optional[float] = None
    operation_failures: Optional[List[Failure]] = None


# AI Aircraft, GAME
#
class Mission(StrEnum):
    ATC = "atc"
    COMBAT_TEAM_RED = "combat_team_red"
    COMBAT_TEAM_BLUE = "combat_team_blue"
    COMBAT_TEAM_GREEN = "combat_team_green"
    COMBAT_TEAM_GOLD = "combat_team_gold"


@dataclass
class AIAircraft(FlightABC):
    aircraft: Aircraft
    mission: Mission


@dataclass
class FormationAircraft(FlightABC):
    path: str


class IncursionType(StrEnum):
    FLIGHT_INCURSION = "flight_incursion"
    RUNWAY_INCURSION_ARM = "runway_incursion_arm"
    RUNWAY_INCURSION_EXECUTE = "runway_incursion_execute"
    CLEAR_INCURSION = "clear_incursion"

@dataclass
class Incursion(FlightABC):
    aircraft: Aircraft
    type: IncursionType


# ENVIRONMENT - TIME
#
class Time(FlightABC):  # ABC
    pass


@dataclass
class YearTime(Time):  # ABC
    day_of_year: int
    time_in_24_hours: float  # Time of day in hours (e.g., 13.5 = 1:30 PM)


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


class CloudType(StrEnum):
    CIRRUS = "cirrus"
    STRATUS = "stratus"
    CUMULUS = "cumulus"
    CUMULUNIMBUS = "cumulunimbus"


@dataclass
class CloudLayer(FlightABC):
    type: CloudType
    cover_ratio: float
    bases_in_feet_msl: float
    tops_in_feet_msl: float


@dataclass
class WindLayer(FlightABC):
    altitude_in_feet_msl: float
    speed_in_knots: float
    direction_in_degrees_true: float

    gust_increase_in_knots: Optional[float] = None
    shear_in_degrees: Optional[float] = None
    turbulence_ratio: Optional[float] = None


@dataclass
class UseRealWeather:

    def toDict(self) -> Dict:
        return "use_real_weather"


@dataclass
class WeatherDefinition(FlightABC):
    latitude_in_degrees: float
    longitude_in_degrees: float
    elevation_in_meters: float
    visibility_in_kilometers: float

    temperature_in_degrees_celsius: Optional[float] = None
    altimeter_setting_in_hpa: Optional[float] = None
    precipitation_ratio: Optional[float] = None
    cloud_layers: Optional[List[CloudLayer]] = None
    wind_layers: Optional[List[WindLayer]] = None


@dataclass
class WeatherScenario(FlightABC):
    definition: WeatherPreset | WeatherDefinition
    vertical_speed_in_thermal_in_feet_per_minute: float
    wave_height_in_meters: float
    wave_direction_in_degrees: float
    terrain_state: TerrainState
    variation_across_region_percentage: float
    evolution_over_time_enum: WeatherEvolution


# FLIGHT
#
@dataclass
class Flight(FlightABC):
    aircraft: Aircraft
    start_location: RunwayStart | RampStart | GroundStart | AirStart | BoatStart
    time: GmtTime | LocalTime | PresetTime | UseSystemTime
    weather: UseRealWeather | WeatherScenario
    weight: Weight
    engine_status: Engine

    failures: Optional[Failures] = None
    ai_aircraft: Optional[List[AIAircraft]] = None
    formation_aircraft: Optional[FormationAircraft] = None
    incursion: Optional[Incursion] = None
    weapons: Optional[List[Weapon]] = None

    _update: bool = False  # set it to True if Flight is an update of existing flight


    def start(self, api :"XPRestAPI"):
        self._update = False
        api.start_flight(flight=self)

    def update(self, api :"XPRestAPI"):
        self._update = True
        api.update_flight(flight=self)

    def fly(self, api :"XPRestAPI"):
        if self._update:
            self.update(api)
        else:
            self.start(api)


# TESTS
#
# Minimal
if __name__ == "__main__":

    # flight = Flight(
    #     # Aircraft
    #     # update=True,
    #     aircraft=Aircraft(path="Aircraft/Airbus/ToLiss A321/a321.acf"),
    #     engine_status=Engine(all_engines=EngineStatus(running=True)),
    #     weight=Weight(payload_weight_in_kilograms=[4200, 1000], fueltank_weight_in_kilograms=[5000, 2000]),
    #     # failures=Failures(mean_time_between_failures_in_hours=0.25, operation_failures=[Failure(name="engine1", status="false", value=1.0)]),
    #     # Location
    #     start_location=RunwayStart(airport_id="EBBR", runway="27R"),
    #     # Environment
    #     time=UseSystemTime(),
    #     weather=Weather(weather=UseRealWeather()),
    #     # weather=Weather(
    #     #     weather=WeatherScenario(
    #     #         definition=WeatherPreset.VFR_FEW_CLOUDS,
    #     #         vertical_speed_in_thermal_in_feet_per_minute=250,
    #     #         wave_height_in_meters=2,
    #     #         wave_direction_in_degrees=200,
    #     #         terrain_state=TerrainState.DRY,
    #     #         variation_across_region_percentage=100,
    #     #         evolution_over_time_enum=WeatherEvolution.STATIC,
    #     #     )
    #     # ),
    #     # weather=Weather(
    #     #     weather=WeatherScenario(
    #     #         definition=WeatherDefinition(
    #     #             latitude_in_degrees=123.3,
    #     #             longitude_in_degrees=41.5,
    #     #             elevation_in_meters=173,
    #     #             visibility_in_kilometers=12.5,
    #     #             temperature_in_degrees_celsius=21
    #     #         ),
    #     #         vertical_speed_in_thermal_in_feet_per_minute=250,
    #     #         wave_height_in_meters=2,
    #     #         wave_direction_in_degrees=200,
    #     #         terrain_state=TerrainState.DRY,
    #     #         variation_across_region_percentage=100,
    #     #         evolution_over_time_enum=WeatherEvolution.STATIC,
    #     #     )
    #     # ),
    #     # ai_aircraft=[AIAircraft(aircraft=Aircraft(path="A350"), mission=Mission.ATC)],
    #     # Game stuff: AI aircrafts, etc.
    # )
    # print(json.dumps(flight.toDict(), indent=4))

    # print(test(flight))
    f = Flight(
        # Aircraft
        # update=True,
        aircraft=Aircraft(path="Aircraft/Airbus/ToLiss A321/a321.acf", livery="panam"),
        engine_status=Engine(all_engines=EngineStatus(running=True)),
        weight=Weight(payload_weight_in_kilograms=[4200, 1000], fueltank_weight_in_kilograms=[5000, 2000]),
        failures=Failures(mean_time_between_failures_in_hours=0.25, operation_failures=[Failure(name="engine1", status="false", value=1.0)]),
        # Location
        start_location=RunwayStart(airport_id="EBBR", runway="25R"),
        # Environment
        # time=UseSystemTime(),
        time=GmtTime(day_of_year=123, time_in_24_hours=13.50),
        # weather=UseRealWeather(),
        weather=WeatherScenario(
            definition=WeatherPreset.LARGE_CELL_THUNDERSTORM,
            vertical_speed_in_thermal_in_feet_per_minute=250,
            wave_height_in_meters=2,
            wave_direction_in_degrees=200,
            terrain_state=TerrainState.DRY,
            variation_across_region_percentage=100,
            evolution_over_time_enum=WeatherEvolution.STATIC,
        ),
        # weather=WeatherScenario(
        #     definition=WeatherDefinition(
        #         latitude_in_degrees=123.3,
        #         longitude_in_degrees=41.5,
        #         elevation_in_meters=173,
        #         visibility_in_kilometers=12.5,
        #         temperature_in_degrees_celsius=21
        #     ),
        #     vertical_speed_in_thermal_in_feet_per_minute=250,
        #     wave_height_in_meters=2,
        #     wave_direction_in_degrees=200,
        #     terrain_state=TerrainState.DRY,
        #     variation_across_region_percentage=100,
        #     evolution_over_time_enum=WeatherEvolution.STATIC,
        # ),
    )
    pprint(f.toDict())

###########