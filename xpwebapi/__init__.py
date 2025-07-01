# Interface
from .api import Dataref, Command, DatarefValueType
from .beacon import XPBeaconMonitor, BeaconData
from .rest import XPRestAPI
from .ws import XPWebsocketAPI, CALLBACK_TYPE
from .udp import XPUDPAPI, XPlaneIpNotFound, XPlaneTimeout, XPlaneVersionNotSupported


def beacon():
    return XPBeaconMonitor()


def rest_api(**kwargs):
    return XPRestAPI(**kwargs)


def ws_api(**kwargs):
    return XPWebsocketAPI(**kwargs)


def udp_api(**kwargs):
    return XPUDPAPI(**kwargs)


version = "2.2.1"
