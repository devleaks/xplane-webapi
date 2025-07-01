# Class to get dataref values from XPlane Flight Simulator via network.
# License: GPLv3

import socket
import struct
import binascii
from time import sleep
from typing import Tuple, Dict
import logging

from .api import API, DatarefValueType, Dataref, Command

# local logging
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


class XPlaneIpNotFound(Exception):
    args = "Could not find any running X-Plane instance on network."


class XPlaneTimeout(Exception):
    args = "X-Plane timeout."


class XPlaneVersionNotSupported(Exception):
    args = "X-Plane version not supported."


class XPUDPAPI(API):
    """
    Get data from XPlane via network.
    Use a class to implement RAI Pattern for the UDP socket.
    """

    def __init__(self, **kwargs):
        # Prepare a UDP Socket to read/write to X-Plane
        self.beacon = kwargs.get("beacon")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(10.0)
        # list of requested datarefs with index number
        self.datarefidx = 0
        self.datarefs = {}  # key = idx, value = dataref
        # values from xplane
        self.xplaneValues = {}
        self.defaultFreq = 1
        API.__init__(self, host="127.0.0.1", port=49000, api="", api_version="")

    def __del__(self):
        for i in range(len(self.datarefs)):
            self._request_dataref(next(iter(self.datarefs.values())), freq=0)
        self.socket.close()

    @property
    def connected(self) -> bool:
        """Whether X-Plane API is reachable through this API"""
        return False if self.beacon.data is None else self.beacon.data.host is not None

    def write_dataref(self, dataref: Dataref) -> bool:
        """Write Dataref value to X-Plane if Dataref is writable

        Args:
            dataref (Dataref): Dataref to write

        Returns:
            bool: Whether write operation was successful or not
        """
        path = dataref.path
        cmd = b"DREF\x00"
        path = path + "\x00"
        string = path.ljust(500).encode()
        message = "".encode()

        vtype = "float"
        if vtype == "float":
            message = struct.pack("<5sf500s", cmd, float(dataref.value), string)
        elif vtype == "int":
            message = struct.pack("<5si500s", cmd, int(dataref.value), string)
        elif vtype == "bool":
            message = struct.pack("<5sI500s", cmd, int(dataref.value), string)

        assert len(message) == 509
        self.socket.sendto(message, (self.beacon.data.host, self.beacon.data.port))
        return True

    def dataref_value(self, dataref: Dataref) -> DatarefValueType:
        """Returns Dataref value from simulator

        Args:
            dataref (Dataref): Dataref to get the value from

        Returns:
            bool | str | int | float: Value of dataref
        """
        all_values = self.read_monitored_dataref_values()
        if dataref.path in all_values:
            dataref.value = all_values[dataref.path]
            return dataref.value
        return None

    def execute(self, command: Command, duration: float = 0.0) -> bool | int:
        """Execute command

        Args:
            command (Command): Command to execute
            duration (float): Duration of execution for long commands (default: `0.0`)

        Returns:
            bool: [description]
        """
        message = struct.pack("<4sx500s", b"CMND", command.path.encode("utf-8"))
        self.socket.sendto(message, (self.beacon_data["IP"], self.UDP_PORT))
        return True

    def monitor_dataref(self, dataref: Dataref) -> bool | int:
        """Starts monitoring single dataref.

        [description]

        Args:
            dataref (Dataref): Dataref to monitor

        Returns:
            bool if fails
            request id if succeeded
        """
        return self._request_dataref(dataref=dataref.path, freq=1)

    def unmonitor_datarefs(self, datarefs: dict, reason: str | None = None) -> Tuple[int | bool, Dict]:
        """Stops monitoring supplied datarefs.

        [description]

        Args:
            datarefs (dict): {path: Dataref} dictionary of datarefs
            reason (str | None): Documentation only string to identify call to function.

        Returns:
            Tuple[int | bool, Dict]: [description]
        """
        return self._request_dataref(dataref=dataref.path, freq=0)

    def _request_dataref(self, dataref: str, freq: int | None = None) -> bool | int:
        """Request X-Plane to send the dataref with a certain frequency.
        You can disable a dataref by setting freq to 0.
        """
        if not self.connected:
            logger.warning("not connected")
            return False
        idx = -9999
        if freq is None:
            freq = self.defaultFreq

        if dataref in self.datarefs.values():
            idx = list(self.datarefs.keys())[list(self.datarefs.values()).index(dataref)]
            if freq == 0:
                if dataref in self.xplaneValues.keys():
                    del self.xplaneValues[dataref]
                del self.datarefs[idx]
        else:
            idx = self.datarefidx
            self.datarefs[self.datarefidx] = dataref
            self.datarefidx += 1

        cmd = b"RREF\x00"
        string = dataref.encode()
        message = struct.pack("<5sii400s", cmd, freq, idx, string)
        assert len(message) == 413
        self.socket.sendto(message, (self.beacon.data.host, self.beacon.data.port))
        if self.datarefidx % 100 == 0:
            sleep(0.2)
        return True

    def read_monitored_dataref_values(self):
        """Do a single read and populate dataref with values.

        This function should be called at regular intervals to collect all requested datarefs.
        (A single read returns about 15 values.)

        Returns:
            dict: {path: value} for received datarefs so far.

        Raises:
            XPlaneTimeout: [description]
        """
        try:
            # Receive packet
            data, addr = self.socket.recvfrom(1472)  # maximum bytes of an RREF answer X-Plane will send (Ethernet MTU - IP hdr - UDP hdr)
            # Decode Packet
            retvalues = {}
            # * Read the Header "RREFO".
            header = data[0:5]
            if header != b"RREF,":  # (was b"RREFO" for XPlane10)
                logger.warning("unknown packet: ", binascii.hexlify(data))
            else:
                # * We get 8 bytes for every dataref sent:
                #   An integer for idx and the float value.
                values = data[5:]
                lenvalue = 8
                numvalues = int(len(values) / lenvalue)
                for i in range(0, numvalues):
                    singledata = data[(5 + lenvalue * i) : (5 + lenvalue * (i + 1))]
                    (idx, value) = struct.unpack("<if", singledata)
                    if idx in self.datarefs.keys():
                        # convert -0.0 values to positive 0.0
                        if value < 0.0 and value > -0.001:
                            value = 0.0
                        retvalues[self.datarefs[idx]] = value
            self.xplaneValues.update(retvalues)
        except:
            raise XPlaneTimeout
        return self.xplaneValues
