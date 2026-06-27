from typing import Any


class XPWebAPIError(Exception):
    def __init__(self, message: str = "", **context: Any):
        self.context = context
        super().__init__(message)


class XPConnectionError(XPWebAPIError):
    pass


class XPBeaconError(XPConnectionError):
    pass


class XPPacketError(XPWebAPIError):
    pass


class XPTimeoutError(XPWebAPIError):
    pass


class XPVersionError(XPWebAPIError):
    pass
