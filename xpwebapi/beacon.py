"""X-Plane UDP Beacon Monitor

Beacon Monitor listen to X-Plane UDP multicast port for a «beacon» emitted by X-Plane network API, if enabled.
If no beacon is ever detected, either X-Plane is not running, or it is busy starting.
If a beacon is detected, the message contains connection information to reach X-Plane instance through the network.
Beacon also contains information about the version of X-Plane.

Attributes:
    logger (Logger): Loger for functions and classes in this file.

"""

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
class XPlaneNoBeacon(Exception):
    args = tuple("No beacon received from any running XPlane instance in network")


class XPlaneVersionNotSupported(Exception):
    args = tuple("XPlane version not supported")


def list_my_ips() -> List[str]:
    """Utility function that list most if not all IP addresses of this host.

    Returns:
        List[str]: List of IP v4 addresses of this host on most, if not all interfaces (cable, wi-fi, bluetooth...)
    """
    r = list()
    adapters = ifaddr.get_adapters()
    for adapter in adapters:
        for ip in adapter.ips:
            if type(ip.ip) is str:
                r.append(ip.ip)
    return r


@dataclass
class BeaconData:
    """Pythonic dataclass to host X-Plane Beacon data."""

    host: str
    port: int
    hostname: str
    xplane_version: int
    role: int


class BEACON_DATA(Enum):
    """X-Plane names of attributes inside its beacon."""

    IP = "IP"
    PORT = "Port"
    HOSTNAME = "hostname"
    XPVERSION = "XPlaneVersion"
    XPROLE = "role"


class BEACON_MONITOR_STATUS(IntEnum):
    """Internal status of Beacon Monitor.

    - NOT_RUNNING - Beacon is not running
    - RUNNING - Beacon monitor is running but no beacon detected
    - DETECTING_BEACON - Beacon monitor is running and beacon detected

    """

    NOT_RUNNING = 0  # Beacon not running
    RUNNING = 1  # Beacon running but no beacon detected
    DETECTING_BEACON = 2  # Beacon running and beacon detected


BEACON_TIMEOUT = 3.0  # seconds, time the socket will wait for beacon, beacon is broadcast every second or less, unless X-Plane is busy busy


class XPBeaconMonitor:
    """X-Plane «beacon» monitor.

    Monitors X-Plane beacon which betrays X-Plane UDP port reachability.
    Beacon monitor listen for X-Plane beacon on UDP port.
    When beacon is detected, Beacon Monitor calls back a user-supplied function
    whenever the reachability status changes.

    Attributes:
        MCAST_GRP (str): default 239.255.1.1
        MCAST_PORT (int): default 49707 (MCAST_PORT was 49000 for XPlane10)
        BEACON_TIMEOUT (float): default 3.0 seconds
        MAX_WARNING (int): After MAX_WARNING warnings of "no connection", stops reporting "no connection". Default 3.
        BEACON_PROBING_TIMEOUT (float): Times between attempts to reconnect to X-Plane when not connected (default 10 seconds)
        WARN_FREQ (float): Report absence of connection every WARN_FREQ seconds. Default 10 seconds.

        socket (socket.socket | None): Socket to multicast listener
        status (BEACON_MONITOR_STATUS): Beacon monitor status
        data: BeaconData | None - Beacon data as broadcasted by X-Plane in its beacon. None if beacon is not received.
        my_ips (List[str]): List of this host IP addresses

        _already_warned (bool):
        _callback: (Callable | None):

        should_not_connect (threading.Event):
        connect_thread: (threading.Thread | None):


    Usage;
    ```python
    import xpwebapi

    def callback(connected: bool, beacon_data: xpwebapi.BeaconData, same_host: bool):
        print("reachable" if connected else "unreachable")

    beacon = xpwebapi.beacon()
    beacon.set_callback(callback)
    beacon.start_monitor()
    ```

    """

    # A few parameters
    #
    MCAST_GRP = "239.255.1.1"
    MCAST_PORT = 49707  # (MCAST_PORT was 49000 for XPlane10)

    BEACON_PROBING_TIMEOUT = 10.0  # seconds, times between attempts to capture beacon (times between executions of get_beacon())

    MAX_WARNING = 3  # after MAX_WARNING warnings of "no connection", stops reporting "no connection"
    WARN_FREQ = 10  # attempts: Every so often, report warning to show beacon monitor is alive, receiving beacon or not

    def __init__(self):
        # Open a UDP Socket to receive on Port 49000
        self.socket = None
        self.data: BeaconData | None = None

        self.not_monitoring: threading.Event = threading.Event()
        self.not_monitoring.set()

        self._connect_thread: threading.Thread | None = None

        self._already_warned = 0
        self._callback: Callable | None = None
        self.my_ips = list_my_ips()
        self._status = BEACON_MONITOR_STATUS.RUNNING  # init != first value
        self.status = BEACON_MONITOR_STATUS.NOT_RUNNING  # first value set through api

        # stats
        self._attempts_to_detect = 0
        self._beacon_detected = 0
        self._timeout = 0
        self._latest_timeout = 0
        self._consecutive_receives = 0
        self._consecutive_failures = 0

    @property
    def status(self) -> BEACON_MONITOR_STATUS:
        """Should use REST API for some purpose"""
        return self._status

    @property
    def status_str(self) -> str:
        """Should use REST API for some purpose"""
        return f"{BEACON_MONITOR_STATUS(self._status).name}"

    @status.setter
    def status(self, status: BEACON_MONITOR_STATUS):
        if self._status != status:
            self._status = status
            logger.info(f"Beacon monitor status is now {self.status_str}")

    # ################################
    # Internal functions
    #
    def callback(self, connected: bool, beacon_data: BeaconData, same_host: bool):
        """Execute callback function if supplied

        Callback function prototype
        ```python
        callback(connected: bool)
        ```

        Connected is True is beacon is detected at regular interval, False otherwise
        """
        if self._callback is not None:
            try:
                self._callback(connected=connected, beacon_data=beacon_data, same_host=same_host)
            except:
                logger.warning("issue calling beacon callback", exc_info=True)

    def get_beacon(self, timeout: float = BEACON_TIMEOUT) -> BeaconData | None:
        """Attemps to capture X-Plane beacon. Returns first occurence of beacon data encountered
           or None if no beacon was detected before timeout.

        It returns the first beacon it receives.

        BeaconData is a python dataclass with the following attributes:

        ```python
        class BeaconData:
            host: str
            port: int
            hostname: str
            xplane_version: int
            role: int

        ```

        Args:
            timeout (float): Time to wait for receiving beacon (typical range 1 to 10 seconds.)

        Returns:
            BeaconData | None: beacon data or None if no beacon received
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
        sock.settimeout(timeout)

        # receive data
        try:
            self._attempts_to_detect = self._attempts_to_detect + 1
            packet, sender = sock.recvfrom(1472)  # blocks timeout secs.
            logger.debug(f"XPlane Beacon: {packet.hex()}")

            # decode data
            # * Header
            header = packet[0:5]
            if header != b"BECN\x00":
                logger.warning(f"Unknown packet from {sender[0]}, {str(len(packet))} bytes:")
                logger.warning(packet)
                logger.warning(binascii.hexlify(packet))

            else:
                self._beacon_detected = self._beacon_detected + 1
                self._latest_timeout = 0
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
            self._timeout = self._timeout + 1
            self._latest_timeout = self._latest_timeout + 1
            logger.debug(f"XPlane beacon not received within timeout ({round(timeout, 1)} secs.).")
            raise XPlaneNoBeacon()
        finally:
            sock.close()

        return self.data

    @property
    def consecutive_failures(self) -> int:
        """Returns number of recent consecutive failures

        This can be used to detect temporary failures. When X-Plane is extremely busy, it may not send a beacon, or beacon emission can be delayed.
        X-Plane is up and running but no beacon has been detected. "Missing" a few detections in a row does not mean X-Plane is not running.
        This `consecutive_failures` allows to wait for a few failures to detect X-Plane before concluding its unavailability.

        """
        return self._consecutive_failures

    def monitor(self):
        """
        Trys to connect to X-Plane indefinitely until should_not_connect Event is set.
        If a connection fails, drops, disappears, will try periodically to restore it.
        """
        logger.debug("starting..")
        self.status = BEACON_MONITOR_STATUS.RUNNING
        while self.is_running:
            if not self.receiving_beacon:
                try:
                    beacon_data = self.get_beacon()  # this provokes attempt to connect
                    if self.receiving_beacon:
                        self.status = BEACON_MONITOR_STATUS.DETECTING_BEACON
                        self._consecutive_receives = self._consecutive_receives + 1
                        self._consecutive_failures = 0
                        self._already_warned = 0
                        logger.info(f"beacon: {self.data}")
                        self.callback(connected=True, beacon_data=beacon_data, same_host=self.same_host())  # connected
                except XPlaneVersionNotSupported:
                    self.data = None
                    logger.error("..X-Plane version not supported..")
                except XPlaneNoBeacon:
                    if self.status == BEACON_MONITOR_STATUS.DETECTING_BEACON:
                        logger.warning("no beacon")
                        self.status = BEACON_MONITOR_STATUS.RUNNING
                        self.callback(False, None, None)  # disconnected
                    self.data = None
                    if self._consecutive_failures % XPBeaconMonitor.WARN_FREQ == 0:
                        logger.error(f"..X-Plane beacon not found on local network.. ({datetime.now().strftime('%H:%M:%S')})")
                    self._consecutive_failures = self._consecutive_failures + 1
                    self._consecutive_receives = 0
                if not self.receiving_beacon:
                    self.not_monitoring.wait(XPBeaconMonitor.BEACON_PROBING_TIMEOUT)
                    logger.debug("..listening for beacon..")
            else:
                self.not_monitoring.wait(XPBeaconMonitor.BEACON_PROBING_TIMEOUT)  # could be n * BEACON_PROBING_TIMEOUT
                logger.debug("..beacon received..")
        self.status = BEACON_MONITOR_STATUS.NOT_RUNNING
        # self.callback(False, None, None)  # we stopped the monitor, beacon might still be alive
        logger.debug("..ended")

    # ################################
    # Interface
    #
    @property
    def receiving_beacon(self) -> bool:
        """Returns whether beacon from X-Plane is periodically received"""
        res = self.data is not None
        if not res and not self._already_warned > self.MAX_WARNING:
            if self._already_warned <= self.MAX_WARNING:
                logger.warning(f"no connection{'' if self._already_warned < self.MAX_WARNING else ' (last warning)'}")
            self._already_warned = self._already_warned + 1
        return res

    def same_host(self) -> bool:
        """Attempt to determine if X-Plane is running on local host (where beacon monitor runs) or remote host"""
        if self.receiving_beacon:
            r = self.data.host in self.my_ips
            logger.debug(f"{self.data.host}{'' if r else ' not'} in {self.my_ips}")
            return r
        return False

    def set_callback(self, callback: Callable | None = None):
        """Set callback function

        Callback function will be called whenever the status of the "connection" changes.

        Args:
            callback (Callable): Callback function
                Callback function prototype
                ```python
                callback(connected: bool, beacon_data: BeaconData | None, same_host: bool | None)
                ```

        Connected is True is beacon is detected at regular interval, False otherwise
        """
        self._callback = callback

    def start_monitor(self):
        """Starts beacon monitor"""
        if self.not_monitoring.is_set():
            self.not_monitoring.clear()  # f"{__name__}::{type(self).__name__}"
            self._connect_thread = threading.Thread(target=self.monitor, name=f"{__name__}::monitor")
            self._connect_thread.start()
            logger.debug("monitor started")
        else:
            logger.debug("monitor already started")

    @property
    def is_running(self) -> bool:
        return not self.not_monitoring.is_set()

    def stop_monitor(self):
        """Terminates beacon monitor"""
        logger.debug("stopping monitor..")
        if self.is_running:
            self.data = None
            self.not_monitoring.set()
            wait = XPBeaconMonitor.BEACON_PROBING_TIMEOUT + BEACON_TIMEOUT
            logger.debug(f"..asked to stop monitor.. (this may last {wait} secs.)")  # status will change in thread if it finishes gracefully
            if self._connect_thread is not None:
                self._connect_thread.join(timeout=wait)
                if self._connect_thread.is_alive():
                    logger.warning("..thread may hang..")
            logger.debug("..monitor stopped")
        else:
            if self.receiving_beacon:
                self.data = None
                logger.debug("..monitor not running..stopped")
            else:
                logger.debug("..monitor not running")
        self.status = BEACON_MONITOR_STATUS.NOT_RUNNING


# ######################################
# Demo and Usage
#
if __name__ == "__main__":
    beacon = XPBeaconMonitor()

    def callback(connected: bool, beacon_data: BeaconData, same_host: bool):
        print("reachable" if connected else "unreachable")
        if connected:  # beacon is bound to above declaration
            print(beacon_data)
            print(same_host)

    beacon.set_callback(callback)
    beacon.start_monitor()
