# Interface
from .api import Dataref, Command, DatarefValueType, DATAREF_DATATYPE
from .beacon import XPBeaconMonitor, BeaconData, XPlaneNoBeacon, XPlaneVersionNotSupported
from .rest import XPRestAPI
from .ws import XPWebsocketAPI, CALLBACK_TYPE
from .udp import XPUDPAPI, XPlaneTimeout
from .flight import (
    TowType,
    Aircraft,
    RunwayStart,
    RampStart,
    GroundStart,
    Speed,
    AirStart,
    BoatLocation,
    BoatStart,
    SlungLoad,
    Weight,
    EngineStatus,
    Engine,
    Weapon,
    FailureStatus,
    Failure,
    Failures,
    Mission,
    AIAircraft,
    FormationAircraft,
    IncursionType,
    Incursion,
    GmtTime,
    LocalTime,
    UseSystemTime,
    TimePreset,
    PresetTime,
    WeatherPreset,
    WeatherEvolution,
    TerrainState,
    UseRealWeather,
    CloudType,
    CloudLayer,
    WindLayer,
    WeatherDefinition,
    WeatherScenario,
    Weather,
    Flight)


Flight, Aircraft, Engine, EngineStatus, Weight, UseSystemTime, UseRealWeather, RunwayStart, RampStart, BoatStart, Weather

def beacon():
    return XPBeaconMonitor()


def rest_api(**kwargs):
    return XPRestAPI(**kwargs)


def ws_api(**kwargs):
    return XPWebsocketAPI(**kwargs)


def udp_api(**kwargs):
    return XPUDPAPI(**kwargs)


version = "3.5.2"
