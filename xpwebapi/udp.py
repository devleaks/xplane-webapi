"""X-Plane access through UDP messages

UDP interface is limited to
  1. Asking for dataref values, one at a time, returned as a float number.
  2. Setting single dataref value in simulator ("write").
  3. Asking for execution of a command.

"""

import socket
import struct
import binascii
import logging
import threading
import platform

from time import sleep
from typing import Tuple, Dict, Callable

from .api import API, CONNECTION_STATUS, DatarefValueType, Dataref, Command
from .beacon import BeaconData, BEACON_TIMEOUT
from xpwebapi import beacon

# local logging
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


class XPlaneTimeout(Exception):
    args = tuple("X-Plane timeout")


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

        #
        self.callbacks = set()

        # list of requested datarefs with index number
        self.datarefidx = 0
        self.datarefs = {}  # key = idx, value = dataref
        # values from xplane
        self.xplaneValues = {}
        self.defaultFreq = 1

        #
        self.udp_lsnr_not_running = threading.Event()
        self.udp_lsnr_not_running.set()  # means it is off
        self.udp_thread = None

        host = kwargs.get("host", "127.0.0.1")
        port = kwargs.get("port", 49000)

        API.__init__(self, host=host, port=port, api="", api_version="")  # api, api_version unused, but could be compared to xplane_version_number

        if self.beacon is not None:
            self.beacon.add_callback(self.beacon_callback)  # can only add after API.__init__() call since it creates class attributes

    def __del__(self):
        for i in range(len(self.datarefs)):
            self._request_dataref(next(iter(self.datarefs.values())), freq=0)
        self.socket.close()

    @property
    def connected(self) -> bool:
        """Whether X-Plane API is reachable through this API"""
        if self.beacon is None:  # probes...
            return self.simple_connection_probe()
        return False if self.beacon.data is None else self.beacon.data.host is not None

    def simple_connection_probe(self) -> bool:
        """Exeprimental

        Do we receive a UPD message within TIMEOUT seconds?

        returns:

        (bool) UPD message recieved

        """
        MCAST_GRP = "239.255.1.1"  # XPBeaconMonitor.MCAST_GRP
        MCAST_PORT = 49707  # XPBeaconMonitor.MCAST_PORT

        logger.warning("no beacon monitor, cannot test connection")
        socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # open socket for multicast group.
        # this socker is for getting the beacon, it can be closed when beacon is found.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # SO_REUSEPORT?
        if platform.system() == "Windows":
            sock.bind(("", MCAST_PORT))
        else:
            sock.bind((MCAST_GRP, MCAST_PORT))
        mreq = struct.pack("=4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(BEACON_TIMEOUT)

        connected = False
        try:
            packet, sender = sock.recvfrom(1472)  # blocks TIMEOUT secs.
            # read something, must be up
            connected = True

        except socket.timeout:  # nothing within TIMEOUT secs
            connected = False
        finally:
            sock.close()
        return connected

    def beacon_callback(self, connected: bool, beacon_data: BeaconData, same_host: bool):
        """Callback waits a little bit before shutting down websocket handler on beacon miss.
           Starts or make sure it is running on beacon hit.

        Args:
            connected (bool): Whether beacon is received
            beacon_data (BeaconData): Beacon data
            same_host (bool): Whether beacon is issued from same host as host running the monitor
        """
        if connected:
            if beacon_data is not None and beacon_data.host is not None:
                logger.debug("beacon detected")
                self.set_network(host=beacon_data.host, port=beacon_data.port, api="", api_version="")

    def add_callback(self, callback: Callable):
        """Add callback function to set of callback functions

        Please note that in the case of UDP, callback is called for each value it received,
        whether the value has changed or not.

        Args:
            callback (Callable): Callback function
        """
        self.callbacks.add(callback)

    def execute_callbacks(self, **kwargs) -> bool:
        """Execute list of callback functions, all with same arguments passed as keyword arguments

        returns

        bool: Whether error reported during execution

        """
        cbs = self.callbacks
        if len(cbs) == 0:
            return True
        ret = True
        for callback in cbs:
            try:
                callback(**kwargs)
            except:
                logger.error(f"callback {callback}", exc_info=True)
                ret = False
        return ret

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
        self.socket.sendto(message, (self.host, self.port))
        return True

    def dataref_value(self, dataref: Dataref) -> DatarefValueType | None:
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

    def execute_command(self, command: Command, duration: float = 0.0) -> bool | int:
        """Execute command

        Args:
            command (Command): Command to execute
            duration (float): Duration of execution for long commands (default: `0.0`)

        Returns:
            bool: [description]
        """
        return self._execute_command(command.path)

    def _execute_command(self, command: str) -> bool:
        """Execute command

        Args:
            command (str): Command to execute
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
        self.socket.sendto(message, (self.host, self.port))
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
        if self.status not in [CONNECTION_STATUS.LISTENING_FOR_DATA, CONNECTION_STATUS.RECEIVING_DATA]:
            self.status = CONNECTION_STATUS.LISTENING_FOR_DATA
        try:
            # Receive packet
            data, addr = self.socket.recvfrom(1472)  # maximum bytes of an RREF answer X-Plane will send (Ethernet MTU - IP hdr - UDP hdr)
            if self.status != CONNECTION_STATUS.RECEIVING_DATA:
                self.status = CONNECTION_STATUS.RECEIVING_DATA
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
                        self.execute_callbacks(dataref=self.datarefs[idx], value=value)
            self.xplaneValues.update(retvalues)
        except:
            if self.status != CONNECTION_STATUS.LISTENING_FOR_DATA:
                self.status = CONNECTION_STATUS.LISTENING_FOR_DATA
            raise XPlaneTimeout
        return self.xplaneValues

    @property
    def udp_listener_running(self) -> bool:
        return not self.udp_lsnr_not_running.is_set()

    def udp_listener(self):
        logger.info("starting udp listener..")

        self.status = CONNECTION_STATUS.UDP_LISTENER_RUNNING
        while self.udp_listener_running:
            try:
                data = self.read_monitored_dataref_values()
            except:
                logger.warning("error", exc_info=True)

        logger.info("..udp listener stopped")

    def start(self, release: bool = True):
        """Start UDP monitoring"""
        if not self.udp_listener_running:  # Thread for X-Plane datarefs
            self.udp_lsnr_not_running.clear()
            self.udp_thread = threading.Thread(target=self.udp_listener, name="XPlane::UDP Listener")
            self.udp_thread.start()
            logger.info("udp listener started")
        else:
            logger.info("udp listener already running.")

        if not release:
            logger.info("waiting for termination..")
            for t in threading.enumerate():
                try:
                    t.join()
                except RuntimeError:
                    pass
            logger.info("..terminated")

    def stop(self):
        """Stop UDP monitoring"""
        if self.udp_listener_running:
            self.udp_lsnr_not_running.set()
            if self.udp_thread is not None and self.udp_thread.is_alive():
                logger.debug("stopping udp listener..")
                wait = self.RECEIVE_TIMEOUT
                logger.debug(f"..asked to stop udp listener (this may last {wait} secs. for timeout)..")
                self.udp_thread.join(wait)
                if self.udp_thread.is_alive():
                    logger.warning("..thread may hang in ws.receive()..")
                logger.info("..udp listener stopped")
        else:
            logger.debug("udp listener not running")
