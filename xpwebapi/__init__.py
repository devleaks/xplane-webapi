from .api import APIResult, Dataref, Command, DatarefReadResult, DatarefValueType, DATAREF_DATATYPE
from .async_rest import AsyncXPRestAPI
from .beacon import XPBeaconMonitor, BeaconData, XPlaneNoBeacon, XPlaneVersionNotSupported
from .exceptions import XPWebAPIError, XPConnectionError, XPBeaconError, XPPacketError, XPTimeoutError, XPVersionError
from .logging_config import JsonLogFormatter, LoggingConfig, configure_logging, write_logging_config
from .rest import XPRestAPI
from .ws import XPWebsocketAPI, CALLBACK_TYPE
from .udp import XPUDPAPI, XPlaneTimeout

__all__ = [
    "Dataref",
    "Command",
    "APIResult",
    "DatarefReadResult",
    "DatarefValueType",
    "DATAREF_DATATYPE",
    "AsyncXPRestAPI",
    "XPBeaconMonitor",
    "BeaconData",
    "XPlaneNoBeacon",
    "XPlaneVersionNotSupported",
    "XPWebAPIError",
    "XPConnectionError",
    "XPBeaconError",
    "XPPacketError",
    "XPTimeoutError",
    "XPVersionError",
    "JsonLogFormatter",
    "LoggingConfig",
    "XPRestAPI",
    "XPWebsocketAPI",
    "CALLBACK_TYPE",
    "XPUDPAPI",
    "XPlaneTimeout",
    "configure_logging",
    "write_logging_config",
    "beacon",
    "rest_api",
    "async_rest_api",
    "ws_api",
    "udp_api",
    "version",
]


def beacon(**kwargs):
    return XPBeaconMonitor(**kwargs)


def rest_api(**kwargs):
    return XPRestAPI(**kwargs)


def async_rest_api(**kwargs):
    return AsyncXPRestAPI(**kwargs)


def ws_api(**kwargs):
    return XPWebsocketAPI(**kwargs)


def udp_api(**kwargs):
    return XPUDPAPI(**kwargs)


version = "3.5.0"
