# Interface
from .api import Dataref, Command, DatarefValueType, DATAREF_DATATYPE
from .beacon import XPBeaconMonitor, BeaconData, XPlaneNoBeacon, XPlaneVersionNotSupported
from .rest import XPRestAPI
from .ws import XPWebsocketAPI, CALLBACK_TYPE
from .udp import XPUDPAPI, XPlaneTimeout


def beacon():
    return XPBeaconMonitor()


def rest_api(**kwargs):
    return XPRestAPI(**kwargs)


def ws_api(**kwargs):
    return XPWebsocketAPI(**kwargs)


def udp_api(**kwargs):
    return XPUDPAPI(**kwargs)


version = "3.3.0"
