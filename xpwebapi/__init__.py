from .api import Dataref, Command
from .beacon import XPBeaconMonitor
from .rest import XPRestAPI
from .ws import XPWebsocketAPI


def beacon():
    return XPBeaconMonitor()


def rest_api(**kwargs):
    return XPRestAPI(**kwargs)


def ws_api(**kwargs):
    return XPWebsocketAPI(**kwargs)


version = "0.0.1"
