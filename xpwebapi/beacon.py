import logging
import threading
import socket
import struct
import binascii
import platform
from typing import Callable, List
from enum import Enum, IntEnum
from datetime import datetime
from dataclasses import dataclass

import ifaddr

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


# XPBeaconMonitor-specific error classes
class XPlaneIpNotFound(Exception):
    args = tuple("Could not find any running XPlane instance in network")


class XPlaneVersionNotSupported(Exception):
    args = tuple("XPlane version not supported")


def list_my_ips() -> List[str]:
    # import ifaddr
    r = list()
    adapters = ifaddr.get_adapters()
    for adapter in adapters:
        for ip in adapter.ips:
            if type(ip.ip) is str:
                r.append(ip.ip)
    return r


# property names match X-Plane's
@dataclass
class BeaconData:
    host: str
    port: int
    hostname: str
    xplane_version: int
    role: int


class BEACON_DATA(Enum):
    IP = "IP"
    PORT = "Port"
    HOSTNAME = "hostname"
    XPVERSION = "XPlaneVersion"
    XPROLE = "role"


class BEACON_MONITOR_STATUS(IntEnum):
    NOT_RUNNING = 0  # Beacon not running
    RUNNING = 1  # Beacon running but not connected
    CONNECTED = 2  # Beacon running and connected


class XPBeaconMonitor:
    """X-Plane «beacon» monitor.

    Monitors X-Plane beacon which betrays X-Plane UDP port reachability.
    Beacon monitor listen for X-Plane beacon on UDP port.
    When beacon is detected, Beacon Monitor calls back a user-supplied function
    whenever the reachability status changes.

    Usage;
    ```python
    from xpwebapi import XPBeaconMonitor

    def callback(connected: bool):
        print("reachable" if connected else "unreachable")

    beacon = XPBeaconMonitor()
    beacon.set_callback(callback)
    beacon.connect()
    ```
    """

    # constants
    MCAST_GRP = "239.255.1.1"
    MCAST_PORT = 49707  # (MCAST_PORT was 49000 for XPlane10)
    BEACON_TIMEOUT = 3.0  # seconds
    MAX_WARNING = 3  # after MAX_WARNING warnings of "no connection", stops reporting "no connection"
    RECONNECT_TIMEOUT = 10  # seconds, times between attempts to reconnect to X-Plane when not connected
    WARN_FREQ = 10  # seconds

    def __init__(self):
        # Open a UDP Socket to receive on Port 49000
        self.socket = None
        self.data: BeaconData | None = None
        self.should_not_connect: threading.Event | None = None
        self.connect_thread: threading.Thread | None = None
        self._already_warned = 0
        self._callback: Callable | None = None
        self.my_ips = list_my_ips()
        self.status = 0

    # ################################
    # Internal functions
    #
    def callback(self, connected):
        """Execute callback function if supplied

        Callback function prototype
        ```python
        callback(connected: bool)
        ```

        Connected is True is beacon is detected at regular interval, False otherwise
        """
        if self._callback is not None:
            self._callback(connected)

    def find_ip(self) -> BeaconData | None:
        """Returns first occurence of X-Plane beacon data

        Find the IP of XPlane Host in Network.
        It takes the first one it can find.

        BeaconData is a python dataclass with the following attrbiutes:
        ```python
        class BeaconData:
            host: str
            port: int
            hostname: str
            xplane_version: int
            role: int

        ```

        Returns:
            BeaconData: beacon information or None if not connected/not reachable/no beacon
        """
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.data = None

        # open socket for multicast group.
        # this socker is for getting the beacon, it can be closed when beacon is found.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # SO_REUSEPORT?
        if platform.system() == "Windows":
            sock.bind(("", self.MCAST_PORT))
        else:
            sock.bind((self.MCAST_GRP, self.MCAST_PORT))
        mreq = struct.pack("=4sl", socket.inet_aton(self.MCAST_GRP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(XPBeaconMonitor.BEACON_TIMEOUT)

        # receive data
        try:
            packet, sender = sock.recvfrom(1472)
            logger.debug(f"XPlane Beacon: {packet.hex()}")

            # decode data
            # * Header
            header = packet[0:5]
            if header != b"BECN\x00":
                logger.warning(f"Unknown packet from {sender[0]}, {str(len(packet))} bytes:")
                logger.warning(packet)
                logger.warning(binascii.hexlify(packet))

            else:
                # * Data
                data = packet[5:21]
                # struct becn_struct
                # {
                #   uchar beacon_major_version;     // 1 at the time of X-Plane 10.40
                #   uchar beacon_minor_version;     // 1 at the time of X-Plane 10.40
                #   xint application_host_id;       // 1 for X-Plane, 2 for PlaneMaker
                #   xint version_number;            // 104014 for X-Plane 10.40b14
                #   uint role;                      // 1 for master, 2 for extern visual, 3 for IOS
                #   ushort port;                    // port number X-Plane is listening on
                #   xchr    computer_name[strDIM];  // the hostname of the computer
                # };
                beacon_major_version = 0
                beacon_minor_version = 0
                application_host_id = 0
                xplane_version_number = 0
                role = 0
                port = 0
                (
                    beacon_major_version,  # 1 at the time of X-Plane 10.40
                    beacon_minor_version,  # 1 at the time of X-Plane 10.40
                    application_host_id,  # 1 for X-Plane, 2 for PlaneMaker
                    xplane_version_number,  # 104014 for X-Plane 10.40b14
                    role,  # 1 for master, 2 for extern visual, 3 for IOS
                    port,  # port number X-Plane is listening on
                ) = struct.unpack("<BBiiIH", data)
                hostname = packet[21:-1]  # the hostname of the computer
                hostname = hostname[0 : hostname.find(0)]
                if beacon_major_version == 1 and beacon_minor_version <= 2 and application_host_id == 1:
                    self.data = BeaconData(host=sender[0], port=port, hostname=hostname.decode(), xplane_version=xplane_version_number, role=role)
                    logger.info(f"XPlane Beacon Version: {beacon_major_version}.{beacon_minor_version}.{application_host_id}")
                else:
                    logger.warning(f"XPlane Beacon Version not supported: {beacon_major_version}.{beacon_minor_version}.{application_host_id}")
                    raise XPlaneVersionNotSupported()

        except socket.timeout:
            logger.debug("XPlane IP not found.")
            raise XPlaneIpNotFound()
        finally:
            sock.close()

        return self.data

    def connect_loop(self):
        """
        Trys to connect to X-Plane indefinitely until should_not_connect Event is set.
        If a connection fails, drops, disappears, will try periodically to restore it.
        """
        logger.debug("starting..")
        cnt = 0
        self.status = 1
        while self.should_not_connect is not None and not self.should_not_connect.is_set():
            if not self.connected:
                try:
                    dummy = self.find_ip()
                    if self.connected:
                        self.status = 2
                        self._already_warned = 0
                        logger.info(f"beacon: {self.data}")
                        self.callback(True)  # connected
                except XPlaneVersionNotSupported:
                    self.data = None
                    logger.error("..X-Plane Version not supported..")
                except XPlaneIpNotFound:
                    if self.status == 2:
                        logger.warning("disconnected")
                        self.status = 1
                        self.callback(False)  # disconnected
                    self.data = None
                    if cnt % XPBeaconMonitor.WARN_FREQ == 0:
                        logger.error(f"..X-Plane instance not found on local network.. ({datetime.now().strftime('%H:%M:%S')})")
                    cnt = cnt + 1
                if not self.connected:
                    self.should_not_connect.wait(XPBeaconMonitor.RECONNECT_TIMEOUT)
                    logger.debug("..trying..")
            else:
                self.should_not_connect.wait(XPBeaconMonitor.RECONNECT_TIMEOUT)  # could be n * RECONNECT_TIMEOUT
                logger.debug("..monitoring connection..")
        self.status = 0
        self.callback(False)  # disconnected
        logger.debug("..ended")

    # ################################
    # Interface
    #
    @property
    def connected(self) -> bool:
        """Returns whether beacon from X-Plane is periodically received"""
        res = self.data is not None
        if not res and not self._already_warned > self.MAX_WARNING:
            if self._already_warned == self.MAX_WARNING:
                logger.warning("no connection (last warning)")
            else:
                logger.warning("no connection")
            self._already_warned = self._already_warned + 1
        return res

    def set_callback(self, callback: Callable | None = None):
        """Set callback function

        Callback function will be called whenever the status of the "connection" changes.

        Callback function prototype
        ```python
        callback(connected: bool)
        ```

        Connected is True is beacon is detected at regular interval, False otherwise
        """
        self._callback = callback

    def connect(self):
        """Starts beacon monitor"""
        if self.should_not_connect is None:
            self.should_not_connect = threading.Event()
            self.connect_thread = threading.Thread(target=self.connect_loop, name="XPlane::Beacon Monitor")
            self.connect_thread.start()
            logger.debug("connect_loop started")
        else:
            logger.debug("connect_loop already started")

    def disconnect(self):
        """Terminates beacon monitor"""
        if self.should_not_connect is not None:
            logger.debug("disconnecting..")
            self.data = None
            self.should_not_connect.set()
            wait = XPBeaconMonitor.RECONNECT_TIMEOUT
            logger.debug(f"..asked to stop connect_loop.. (this may last {wait} secs.)")
            if self.connect_thread is not None:
                self.connect_thread.join(timeout=wait)
                if self.connect_thread.is_alive():
                    logger.warning("..thread may hang..")
            self.should_not_connect = None
            self.status = 0
            logger.debug("..disconnected")
        else:
            if self.connected:
                self.data = None
                logger.debug("..connect_loop not running..disconnected")
            else:
                logger.debug("..not connected")

    def same_host(self) -> bool:
        """Attempt to determine if X-Plane is running on local host (where beacon monitor runs) or remote host"""
        if self.connected:
            r = self.data.host in self.my_ips
            logger.debug(f"{self.data.host}{'' if r else ' not'} in {self.my_ips}")
            return r
        return False


# ######################################
# Demo and Usage
#
if __name__ == "__main__":
    beacon = XPBeaconMonitor()

    def callback(connected: bool):
        print("reachable" if connected else "unreachable")
        if beacon.connected:  # beacon is bound to above declaration
            print(beacon.find_ip())
            print(beacon.same_host())

    beacon.set_callback(callback)
    beacon.connect()
