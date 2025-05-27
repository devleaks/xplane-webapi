from .api import Dataref, Command
from .beacon import XPBeaconMonitor
from .rest import XPRestAPI
from .ws import XPWebSocketAPI


def beacon():
    return XPBeaconMonitor()


def rest_api(**kwargs):
    return XPRestAPI(**kwargs)


def ws_api(**kwargs):
    return XPWebSocketAPI(**kwargs)


__version__ = "1.0.0"
