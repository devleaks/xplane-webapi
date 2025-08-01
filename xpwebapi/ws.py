"""X-Plane Web API access through Websocket API
"""
from __future__ import annotations

import socket
import threading
import logging
import json
import time

from datetime import datetime
from typing import Tuple, Dict
from enum import Enum

# Packaging is used in Cockpit to check driver versions
from packaging.version import Version

from simple_websocket import Client, ConnectionClosed

from .api import CONNECTION_STATUS, DATAREF_DATATYPE, webapi_logger, Dataref, Command
from .rest import REST_KW, XPRestAPI

# local logging
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

XP_MIN_VERSION = 121400
XP_MIN_VERSION_STR = "12.1.4"
XP_MAX_VERSION = 121499
XP_MAX_VERSION_STR = "12.2.1"

MAX_WARNING_COUNT = 5


# WEB API RETURN CODES
class WS_RESPONSE_TYPE(Enum):
    """X-Plane Websocket API response types"""

    RESULT = "result"
    DATAREF_UPDATE = "dataref_update_values"
    COMMAND_ACTIVE = "command_update_is_active"


class CALLBACK_TYPE(Enum):
    ON_OPEN = "open"
    ON_CLOSE = "close"
    ON_REQUEST_FEEDBACK = "feedback"
    ON_DATAREF_UPDATE = "dataref_update"
    ON_COMMAND_ACTIVE = "command_active"
    AFTER_START = "after_start"
    BEFORE_STOP = "before_stop"


# #############################################
# WEBSOCKET API
#
class XPWebsocketAPI(XPRestAPI):
    """X-Plane Websocket Client.

    The XPWebsocketAPI is a client interface to X-Plane Web API, Websocket server.

    The XPWebsocketAPI has a _connection monitor_ (XPWebsocketAPI.connection_monitor) that can be started (XPWebsocketAPI.connect) and stopped (XPWebsocketAPI.disconnect).
    The monitor tests for REST API reachability, and if reachable, creates a Websocket.
    If the websocket exists and is opened, requests can be made through it and responses expected.

    To handle responses, a _receiver_ (XPWebsocketAPI.ws_listener) can be started (XPWebsocketAPI.start) and stopped (XPWebsocketAPI.stop)
    to process responses coming through the websocket.

    See https://developer.x-plane.com/article/x-plane-web-api/#Websockets_API.
    """

    MAX_WARNING = 5  # number of times it reports it cannot connect
    RECONNECT_TIMEOUT = 10  # seconds, times between attempts to reconnect to X-Plane when not connected
    RECEIVE_TIMEOUT = 5  # seconds, assumes no awser if no message recevied withing that timeout
    BEACON_TIMEOUT = 60  # seconds, if no beacon for 60 seconds, stops to release resources

    def __init__(self, host: str = "127.0.0.1", port: int = 8086, api: str = "api", api_version: str = "v2", use_rest: bool = False):
        # Open a UDP Socket to receive on Port 49000
        XPRestAPI.__init__(self, host=host, port=port, api=api, api_version=api_version, use_cache=True)

        self.use_rest = use_rest  # setter in API

        hostname = socket.gethostname()
        self.local_ip = socket.gethostbyname(hostname)

        self.ws: Client | None = None  # None = no connection
        self.ws_lsnr_not_running = threading.Event()
        self.ws_lsnr_not_running.set()  # means it is off
        self.ws_thread = None

        self.req_number = 0
        self._requests = {}

        self.slow_stop = threading.Event()
        self.should_not_connect = threading.Event()
        self.should_not_connect.set()  # starts off
        self.connect_thread = None  # threading.Thread()
        self._already_warned = 0
        self._stats = {}

        self.callbacks = {t.value: set() for t in CALLBACK_TYPE}
        # Add a default
        self.set_callback(CALLBACK_TYPE.ON_REQUEST_FEEDBACK, self._on_request_feedback)
        self.on_request_feedback = (
            self._on_request_feedback
        )  # Called on command request feedback, for each indivudua feedback, prototype: `func(request_id:int, payload: dict)`

    @property
    def ws_url(self) -> str:
        """URL for the Websocket API"""
        return self._url("ws")

    @property
    def next_req(self) -> int:
        """Provides request number for Websocket requests

        Current request number is available through attribute `req_number`.
        """
        self.req_number = self.req_number + 1
        return self.req_number

    def add_callback(self, cbtype: CALLBACK_TYPE, callback: Callable):
        """Add callback function to set of callback functions

        Args:
            callback (Callable): Callback function
        """
        self.callbacks[cbtype.value].add(callback)

    def set_callback(self, cbtype: CALLBACK_TYPE, callback: Callable):
        self.add_callback(cbtype=cbtype, callback=callback)

    def execute_callbacks(self, cbtype: CALLBACK_TYPE, **kwargs) -> bool:
        """Execute list of callback functions, all with same arguments passed as keyword arguments

        returns

        bool: Whether error reported during execution

        """
        cbs = self.callbacks[cbtype.value]
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

    # ################################
    # Connection to web socket
    #
    def beacon_callback(self, connected: bool, beacon_data: "BeaconData", same_host: bool):
        """Callback waits a little bit before shutting down websocket handler on beacon miss.
           Starts or make sure it is running on beacon hit.

        Args:
            connected (bool): Whether beacon is received
            beacon_data (BeaconData): Beacon data
            same_host (bool): Whether beacon is issued from same host as host running the monitor
        """
        if connected:
            logger.debug("beacon detected")
            self.set_connection_from_beacon_data(beacon_data=beacon_data, same_host=same_host)
            self.slow_stop.set()
            if not self.websocket_listener_running:
                logger.debug("starting..")
                self.start()
                logger.debug("..started")
        else:
            logger.debug(f"beacon not detected, will stop in {self.BEACON_TIMEOUT} secs.")
            self.slow_stop.clear()
            if not self.slow_stop.wait(self.BEACON_TIMEOUT):  # time out
                logger.debug("stopping..")
                self.stop()
                self.invalidate_caches()
                logger.debug("..stopped")
            else:
                logger.debug("stop aborted")

    # ################################
    # Connection to web socket
    #
    @property
    def connected(self) -> bool:
        """Whether client software is connect to Websoket"""
        res = self.ws is None
        if res and self._already_warned <= self.MAX_WARNING:
            if self._already_warned == self.MAX_WARNING:
                logger.warning("no connection (last warning)")
            else:
                logger.warning("no connection")
            self._already_warned = self._already_warned + 1
        return not res

    @property
    def websocket_connection_monitor_running(self) -> bool:
        return not self.should_not_connect.is_set()

    def connect_websocket(self):
        """Create and open Websocket connection if REST API is reachable"""
        if self.ws is None:
            url = self.ws_url
            if url is not None:
                try:
                    if self.rest_api_reachable:
                        self.ws = Client.connect(url)
                        self.status = CONNECTION_STATUS.WEBSOCKET_CONNNECTED
                        self.reload_caches()
                        logger.info(f"websocket opened at {url}")
                        self.execute_callbacks(CALLBACK_TYPE.ON_OPEN)
                    else:
                        if self._unreach_count <= MAX_WARNING_COUNT:
                            last_warning = " (last warning)" if self._unreach_count == MAX_WARNING_COUNT else ""
                            logger.warning(f"rest api unreachable{last_warning}")
                        if self._unreach_count % 50 == 0:
                            logger.warning("rest api unreachable")
                        self._unreach_count = self._unreach_count + 1
                except:
                    logger.error("cannot connect", exc_info=True)
            else:
                logger.warning(f"web socket url is none {url}")
        else:
            logger.warning("already connected")

    def disconnect_websocket(self, silent: bool = False):
        """Gracefully closes Websocket connection"""
        if self.ws is not None:
            self.ws.close()
            self.ws = None
            self.status = CONNECTION_STATUS.WEBSOCKET_DISCONNNECTED
            dummy = super().connected  # set REST API reachability status
            if not silent:
                logger.info("websocket closed")
            self.execute_callbacks(CALLBACK_TYPE.ON_CLOSE)
        else:
            if not silent:
                logger.warning("already disconnected")

    def connection_monitor(self):
        """
        Attempts to connect to X-Plane Websocket indefinitely until self.should_not_connect is set.
        If a connection fails, drops, disappears, will try periodically to restore it.
        """
        logger.debug("starting connection monitor..")
        MAX_TIMEOUT_COUNT = 5
        WARN_FREQ = 10
        CONN_FREQ = 10
        NOCONN_FREQ = 30
        number_of_timeouts = 0
        to_count = 0
        mon_count = 0
        noconn_count = 0
        noconn = 0
        while not self.should_not_connect.is_set():
            if not self.connected:
                try:
                    if noconn % WARN_FREQ == 0:
                        logger.info("not connected, trying..")
                        noconn = noconn + 1
                    self.connect_websocket()
                    if self.connected:
                        self._already_warned = 0
                        number_of_timeouts = 0
                        self.dynamic_timeout = self.RECONNECT_TIMEOUT
                        logger.info(f"capabilities: {self.capabilities}")
                        if self.xp_version is not None:  # see https://packaging.pypa.io/en/stable/version.html
                            curr = Version(self.xp_version).base_version  # note Version() uniformly converts "12.2.0-r1" to "12.2.0.post1"
                            xpmin = Version(XP_MIN_VERSION_STR).base_version
                            xpmax = Version(XP_MAX_VERSION_STR).base_version
                            if curr < xpmin:
                                logger.warning(f"X-Plane version {curr} ({self.xp_version}) detected, minimal version is {xpmin}")
                                logger.warning("Some features may not work properly")
                            elif curr > xpmax:
                                logger.warning(f"X-Plane version {curr} ({self.xp_version}) detected, maximal version is {xpmax}")
                                logger.warning(f"Some features may not work properly (not tested against X-Plane version after {xpmax})")
                            else:
                                logger.info(f"X-Plane version requirements {xpmin}<= {curr} <={xpmax} satisfied")
                        logger.debug("..connected, starting websocket listener..")
                        self.start()  # calls local start to start websocket listener
                        logger.info("..websocket listener started..")
                    else:
                        if self.ws_lsnr_not_running is not None and self.websocket_listener_running:
                            number_of_timeouts = number_of_timeouts + 1
                            if number_of_timeouts <= MAX_TIMEOUT_COUNT:  # attemps to reconnect
                                logger.info(f"timeout received ({number_of_timeouts}/{MAX_TIMEOUT_COUNT})")  # , exc_info=True
                            if number_of_timeouts >= MAX_TIMEOUT_COUNT:  # attemps to reconnect
                                logger.warning("too many times out, websocket listener terminated")  # ignore
                                self.ws_lsnr_not_running.set()

                        if number_of_timeouts >= MAX_TIMEOUT_COUNT and to_count % WARN_FREQ == 0:
                            logger.error(f"..X-Plane instance not found on local network.. ({datetime.now().strftime('%H:%M:%S')})")
                        to_count = to_count + 1
                except:
                    logger.error(f"..X-Plane instance not found on local network.. ({datetime.now().strftime('%H:%M:%S')})", exc_info=True)
                # If still no connection (above attempt failed)
                # we wait before trying again
                if not self.connected:
                    self.dynamic_timeout = 1
                    self.should_not_connect.wait(self.dynamic_timeout)
                    if noconn_count % NOCONN_FREQ == 0:
                        logger.debug("..no connection. trying to connect..")
                    noconn_count = noconn_count + 1
            else:
                # Connection is OK, we wait before checking again
                self.should_not_connect.wait(self.RECONNECT_TIMEOUT)  # could be n * RECONNECT_TIMEOUT
                if mon_count % CONN_FREQ == 0:
                    logger.debug("..monitoring connection..")
                mon_count = mon_count + 1
        logger.debug("..ended connection monitor")

    # ################################
    # Interface
    #
    def connect(self, reload_cache: bool = False):
        """
        Starts connection to Websocket monitor
        """
        if self.should_not_connect.is_set():
            self.should_not_connect.clear()
            self.connect_thread = threading.Thread(target=self.connection_monitor, name=f"{type(self).__name__}::Connection Monitor")
            self.connect_thread.start()
            logger.debug("connection monitor started")
        else:
            if reload_cache:
                self.reload_caches()
            logger.debug("connection monitor connected")

    def disconnect(self):
        """
        Ends connection to Websocket monitor and closes websocket
        """
        if not self.should_not_connect.is_set():
            logger.debug("disconnecting..")
            self.should_not_connect.set()  # first stop the connection monitor.
            wait = self.RECONNECT_TIMEOUT  # If we close the connection first, it might be reopened by the connection monitor
            logger.debug(f"..asked to stop connection monitor.. (this may last {wait} secs.)")
            self.connect_thread.join(timeout=wait)
            if self.connect_thread.is_alive():
                logger.warning("..thread may hang..")
            self.disconnect_websocket(silent=True)  # then we close the websocket
            logger.debug("..disconnected")
        else:
            if self.connected:
                self.disconnect_websocket()
                logger.debug("..connection monitor not running..disconnected")
            else:
                logger.debug("..not connected")

    # ################################
    # I/O
    #
    # Generic payload "send" function, unique
    def send(self, payload: dict, mapping: dict = {}) -> int | bool:
        """Send payload message (JSON) through Websocket

        Args:
            payload (dict): JSON message
            mapping (dict): corresponding {idenfier: path} for printing/debugging

        Returns:
            bool if fails
            request id if succeeded
        """
        if not self.connected:
            logger.warning("not connected")
            return False
        if payload is None or len(payload) == 0:
            logger.warning("no payload")
            return False
        req_id = self.next_req
        payload[REST_KW.REQID.value] = req_id
        self._requests[req_id] = None  # may be should remember timestamp, etc. if necessary, create Request class.
        self.ws.send(json.dumps(payload))
        webapi_logger.info(f">>SENT {payload}")
        if len(mapping) > 0:
            maps = [f"{k}={v}" for k, v in mapping.items()]
            webapi_logger.info(f">> MAP {', '.join(maps)}")
        return req_id

    # Dataref operations
    #
    # Note: It is not possible get the the value of a dataref just once
    # through web service. No get_dataref_value().
    #
    def set_dataref_value(self, path, value) -> bool | int:
        """Set single dataref value through Websocket

        Returns:
            bool if fails
            request id if succeeded
        """

        def split_dataref_path(path):
            name = path
            index = -1
            split = "[" in path and "]" in path
            if split:  # sim/some/values[4]
                name = path[: path.find("[")]
                index = int(path[path.find("[") + 1 : path.find("]")])  # 4
            meta = self.get_dataref_meta_by_name(name)
            return split, meta, name, index

        if value is None:
            logger.warning(f"dataref {path} has no value to set")
            return -1
        split, meta, name, index = split_dataref_path(path)
        if meta is None:
            logger.warning(f"dataref {path} not found in X-Plane datarefs database")
            return -1
        payload = {
            REST_KW.TYPE.value: "dataref_set_values",
            REST_KW.PARAMS.value: {REST_KW.DATAREFS.value: [{REST_KW.IDENT.value: meta.ident, REST_KW.VALUE.value: value}]},
        }
        mapping = {meta.ident: meta.name}
        if split:
            payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value][0][REST_KW.INDEX.value] = index
        return self.send(payload, mapping)

    def register_bulk_dataref_value_event(self, datarefs, on: bool = True) -> bool | int:
        drefs = []
        for dataref in datarefs.values():
            if type(dataref) is list:
                meta = self.get_dataref_meta_by_id(dataref[0].ident)  # we modify the global source info, not the local copy in the Dataref()
                if meta is None:
                    logger.warning(f"cannot register {dataref[0]}, no meta data")
                    continue
                webapi_logger.info(f"INDICES bef: {dataref[0].ident} => {meta.indices}")
                meta.save_indices()  # indices of "current" requests
                ilist = []
                otext = "on "
                for d1 in dataref:
                    ilist.append(d1.index)
                    if on:
                        meta.append_index(d1.index)
                    else:
                        otext = "off"
                        meta.remove_index(d1.index)
                    meta._last_req_number = self.req_number  # not 100% correct, but sufficient
                drefs.append({REST_KW.IDENT.value: dataref[0].ident, REST_KW.INDEX.value: ilist})
                webapi_logger.info(f"INDICES {otext}: {dataref[0].ident} => {ilist}")
                webapi_logger.info(f"INDICES aft: {dataref[0].ident} => {meta.indices}")
            else:
                if dataref.is_array:
                    logger.debug(f"dataref {dataref.name}: collecting whole array")
                drefs.append({REST_KW.IDENT.value: dataref.ident})
        if len(datarefs) > 0:
            mapping = {}
            for d in datarefs.values():
                if type(d) is list:
                    for d1 in d:
                        mapping[d1.ident] = d1.name
                else:
                    mapping[d.ident] = d.name
            action = "dataref_subscribe_values" if on else "dataref_unsubscribe_values"
            return self.send({REST_KW.TYPE.value: action, REST_KW.PARAMS.value: {REST_KW.DATAREFS.value: drefs}}, mapping)
        if on:
            action = "register" if on else "unregister"
            logger.warning(f"no bulk datarefs to {action}")
        return False

    # Command operations
    #
    def register_command_is_active_event(self, path: str, on: bool = True) -> bool | int:
        """Register single command for active reporting.

        Args:
            path (str): Command path
            on (bool): True registers for active reporting, False unregisters.

        Returns:
            bool if fails
            request id if succeeded
        """
        cmdref = self.get_command_meta_by_name(path)
        if cmdref is not None:
            mapping = {cmdref.ident: cmdref.name}
            action = "command_subscribe_is_active" if on else "command_unsubscribe_is_active"
            return self.send({REST_KW.TYPE.value: action, REST_KW.PARAMS.value: {REST_KW.COMMANDS.value: [{REST_KW.IDENT.value: cmdref.ident}]}}, mapping)
        logger.warning(f"command {path} not found in X-Plane commands database")
        return -1

    def register_bulk_command_is_active_event(self, paths, on: bool = True) -> bool | int:
        """Register multiple commands for active reporting.

        Args:
            paths (str): Command paths
            on (bool): True registers for active reporting, False unregisters.

        Returns:
            bool if fails
            request id if succeeded
        """
        cmds = []
        mapping = {}
        for path in paths:
            cmdref = self.get_command_meta_by_name(path=path)
            if cmdref is None:
                logger.warning(f"command {path} not found in X-Plane commands database")
                continue
            cmds.append({REST_KW.IDENT.value: cmdref.ident})
            mapping[cmdref.ident] = cmdref.name

        if len(cmds) > 0:
            action = "command_subscribe_is_active" if on else "command_unsubscribe_is_active"
            return self.send({REST_KW.TYPE.value: action, REST_KW.PARAMS.value: {REST_KW.COMMANDS.value: cmds}}, mapping)
        if on:
            action = "register" if on else "unregister"
            logger.warning(f"no bulk command active to {action}")
        return -1

    def set_command_is_active_with_duration(self, path: str, duration: float = 0.0) -> bool | int:
        """Execute command active with duration.

        Args:
            path (str): Command path
            duration: float: Duration, should be between 0.0 and 10.0.

        Returns:
            bool if fails
            request id if succeeded
        """
        cmdref = self.get_command_meta_by_name(path)
        if cmdref is not None:
            return self.send(
                {
                    REST_KW.TYPE.value: "command_set_is_active",
                    REST_KW.PARAMS.value: {
                        REST_KW.COMMANDS.value: [{REST_KW.IDENT.value: cmdref.ident, REST_KW.ISACTIVE.value: True, REST_KW.DURATION.value: duration}]
                    },
                }
            )
        logger.warning(f"command {path} not found in X-Plane commands database")
        return -1

    def set_command_is_active_without_duration(self, path: str, active: bool) -> bool | int:
        """Execute command active with no duration

        Args:
            path (str): Command path
            active (bool): Command active status.

        Returns:
            bool if fails
            request id if succeeded
        """
        cmdref = self.get_command_meta_by_name(path)
        if cmdref is not None:
            return self.send(
                {
                    REST_KW.TYPE.value: "command_set_is_active",
                    REST_KW.PARAMS.value: {REST_KW.COMMANDS.value: [{REST_KW.IDENT.value: cmdref.ident, REST_KW.ISACTIVE.value: active}]},
                }
            )
        logger.warning(f"command {path} not found in X-Plane commands database")
        return -1

    def set_command_is_active_true_without_duration(self, path) -> bool | int:
        """Execute command active with no duration

        Args:
            path (str): Command path

        Returns:
            bool if fails
            request id if succeeded
        """
        return self.set_command_is_active_without_duration(path=path, active=True)

    def set_command_is_active_false_without_duration(self, path) -> bool | int:
        """Execute command inactive with no duration

        Args:
            path (str): Command path

        Returns:
            bool if fails
            request id if succeeded
        """
        return self.set_command_is_active_without_duration(path=path, active=False)

    # ################################
    # Start/Run/Stop
    #
    def _on_request_feedback(self, request_id: int, payload: dict):
        FAILED = "failed"
        result = payload.get(REST_KW.SUCCESS.value)
        if not result:
            errmsg = REST_KW.SUCCESS.value if result else FAILED
            errmsg = errmsg + " " + payload.get("error_message", "no error message")
            errmsg = errmsg + " (" + payload.get("error_code", "no error code") + ")"
            logger.warning(f"req. {request_id}: {errmsg}")
        else:
            logger.debug(f"req. {request_id}: {REST_KW.SUCCESS.value if payload[REST_KW.SUCCESS.value] else FAILED}")

    def ws_listener(self):
        """Read and decode websocket messages and calls back"""
        logger.info("starting websocket listener..")

        total_reads = 0
        attention = 10
        to_count = 0
        TO_COUNT_DEBUG = 10
        TO_COUNT_INFO = 50
        start_time = datetime.now()
        last_read_ts = start_time
        total_read_time = 0.0

        self.RECEIVE_TIMEOUT = 1  # when not connected, checks often
        self.status = CONNECTION_STATUS.LISTENING_FOR_DATA

        while self.websocket_listener_running:
            try:
                message = self.ws.receive(timeout=self.RECEIVE_TIMEOUT)
                # probably we don't receive messages because X-Plane has nothing to send...
                if message is None:
                    if to_count % TO_COUNT_INFO == 0:
                        logger.debug(f"..receive timeout ({self.RECEIVE_TIMEOUT} secs.), waiting for response from simulator..")  # at {datetime.now()}")
                    elif to_count % TO_COUNT_DEBUG == 0:
                        logger.debug(f"..receive timeout ({self.RECEIVE_TIMEOUT} secs.), waiting for response from simulator..")  # at {datetime.now()}")
                    to_count = to_count + 1
                    continue

                now = datetime.now()
                if total_reads == 0:
                    logger.info(f"..first message at {now.replace(microsecond=0)} ({round((now - start_time).seconds, 2)} secs.).. {'<'*attention}")
                    self.status = CONNECTION_STATUS.RECEIVING_DATA
                    self.RECEIVE_TIMEOUT = 5  # when connected, check less often, message will arrive

                if to_count > 0:
                    logger.debug(f"..receive ok..")
                    to_count = 0
                total_reads = total_reads + 1
                delta = now - last_read_ts
                total_read_time = total_read_time + delta.microseconds / 1000000
                last_read_ts = now

                # Decode response
                data = {}
                resp_type = ""
                try:
                    data = json.loads(message)
                    resp_type = data[REST_KW.TYPE.value]
                    #
                    #
                    if resp_type == WS_RESPONSE_TYPE.RESULT.value:

                        webapi_logger.info(f"<<RCV  {data}")
                        req_id = data.get(REST_KW.REQID.value)
                        if req_id is not None:
                            self._requests[req_id] = data.get(REST_KW.SUCCESS.value)
                            self.execute_callbacks(CALLBACK_TYPE.ON_REQUEST_FEEDBACK, request_id=req_id, payload=data)
                    #
                    #
                    elif resp_type == WS_RESPONSE_TYPE.COMMAND_ACTIVE.value:

                        if REST_KW.DATA.value not in data:
                            logger.warning(f"no data: {data}")
                            continue

                        for ident, value in data[REST_KW.DATA.value].items():
                            meta = self.get_command_meta_by_id(int(ident))
                            if meta is not None:
                                webapi_logger.info(f"CMD : {meta.name}={value}")
                                self.execute_callbacks(CALLBACK_TYPE.ON_COMMAND_ACTIVE, command=meta.name, active=value)
                            else:
                                logger.warning(f"no command for id={self.all_commands.equiv(ident=int(ident))}")
                    #
                    #
                    elif resp_type == WS_RESPONSE_TYPE.DATAREF_UPDATE.value:

                        if REST_KW.DATA.value not in data:
                            logger.warning(f"no data: {data}")
                            continue

                        for ident, value in data[REST_KW.DATA.value].items():
                            ident = int(ident)
                            dataref = self._dataref_by_id.get(ident)
                            if dataref is None:
                                logger.debug(
                                    f"no dataref for id={self.all_datarefs.equiv(ident=int(ident))} (this may be a previously requested dataref arriving late..., safely ignore)"
                                )
                                continue

                            if type(dataref) is list:
                                #
                                # 1. One or more values from a dataref array (but not all values)
                                if type(value) is not list:
                                    logger.warning(f"dataref array {self.all_datarefs.equiv(ident=ident)} value is not a list ({value}, {type(value)})")
                                    continue
                                meta = dataref[0].meta
                                if meta is None:
                                    logger.warning(f"dataref array {self.all_datarefs.equiv(ident=ident)} meta data not found")
                                    continue
                                current_indices = meta.indices
                                if len(value) != len(current_indices):
                                    logger.warning(
                                        f"dataref array {self.all_datarefs.equiv(ident=ident)}: size mismatch ({len(value)} vs {len(current_indices)})"
                                    )
                                    logger.warning(f"dataref array {self.all_datarefs.equiv(ident=ident)}: value: {value}, indices: {current_indices})")
                                    # So! since we totally missed this set of data, we ask for the set again to refresh the data:
                                    # err = self.send({REST_KW.TYPE.value: "dataref_subscribe_values", REST_KW.PARAMS.value: {REST_KW.DATAREFS.value: meta.indices}}, {})
                                    last_indices = meta.last_indices()
                                    if len(value) != len(last_indices):
                                        logger.warning("no attempt with previously requested indices, no match")
                                        continue
                                    else:
                                        logger.warning("attempt with previously requested indices (we have a match)..")
                                        logger.warning(f"dataref array: current value: {value}, previous indices: {last_indices})")
                                        current_indices = last_indices
                                for idx, v1 in zip(current_indices, value):
                                    d1 = f"{meta.name}[{idx}]"
                                    self.execute_callbacks(CALLBACK_TYPE.ON_DATAREF_UPDATE, dataref=d1, value=v1)
                                    # print(f"{d1}={v1}")
                                # alternative:
                                # for d in dataref:
                                #     parsed_value = d.parse_raw_value(value)
                                #     print(f"{d.name}={parsed_value}")
                            else:
                                #
                                # 2. Scalar value
                                parsed_value = dataref.parse_raw_value(value)
                                self.execute_callbacks(CALLBACK_TYPE.ON_DATAREF_UPDATE, dataref=dataref.path, value=parsed_value)
                                # print(f"{dataref.name}={parsed_value}")
                    #
                    #
                    else:
                        logger.warning(f"invalid response type {resp_type}: {data}")

                except:
                    logger.warning(f"decode data {data} failed", exc_info=True)

            except ConnectionClosed:
                logger.warning("websocket connection closed")
                self.ws = None
                self.ws_lsnr_not_running.set()
                self.status = CONNECTION_STATUS.WEBSOCKET_DISCONNNECTED  # should check rest api reachable
                dummy = super().connected
                self.execute_callbacks(CALLBACK_TYPE.ON_CLOSE)

            except:
                logger.error("ws_listener error", exc_info=True)

        if self.ws is not None:  # in case we did not receive a ConnectionClosed event
            self.ws.close()
            self.ws = None
            self.status = CONNECTION_STATUS.WEBSOCKET_DISCONNNECTED  # should check rest api reachable
            dummy = super().connected
            self.execute_callbacks(CALLBACK_TYPE.ON_CLOSE)
        logger.info("..websocket listener terminated")

    @property
    def websocket_listener_running(self) -> bool:
        return not self.ws_lsnr_not_running.is_set()

    def start(self, release: bool = True):
        """Start Websocket monitoring"""
        if not self.connected:
            logger.warning("not connected. cannot not start.")
            return

        if not self.websocket_listener_running:  # Thread for X-Plane datarefs
            self.ws_lsnr_not_running.clear()
            self.ws_thread = threading.Thread(target=self.ws_listener, name="XPlane::Websocket Listener")
            self.ws_thread.start()
            logger.info("websocket listener started")
        else:
            logger.info("websocket listener already running.")

        # When restarted after network failure, should clean all datarefs
        # then reload datarefs from current page of each deck
        self.reload_caches()
        self.rebuild_dataref_ids()
        self.execute_callbacks(CALLBACK_TYPE.AFTER_START, connected=self.connected)
        logger.info(f"{type(self).__name__} started")
        if not release:
            logger.info("waiting for termination..")
            for t in threading.enumerate():
                try:
                    t.join()
                except RuntimeError:
                    pass
            logger.info("..terminated")

    def stop(self):
        """Stop Websocket monitoring"""
        if self.websocket_listener_running:
            # if self.all_datarefs is not None:
            #     self.all_datarefs.save("datarefs.json")
            # if self.all_commands is not None:
            #     self.all_commands.save("commands.json")
            self.execute_callbacks(CALLBACK_TYPE.BEFORE_STOP, connected=self.connected)
            self.ws_lsnr_not_running.set()
            if self.ws_thread is not None and self.ws_thread.is_alive():
                logger.debug("stopping websocket listener..")
                wait = self.RECEIVE_TIMEOUT
                logger.debug(f"..asked to stop websocket listener (this may last {wait} secs. for timeout)..")
                self.ws_thread.join(wait)
                if self.ws_thread.is_alive():
                    logger.warning("..thread may hang in ws.receive()..")
                logger.info("..websocket listener stopped")
            self.invalidate_caches()
        else:
            logger.debug("websocket listener not running")

    def reset_connection(self):
        """Reset Websocket connection

        Stop existing Websocket connect and create a new one.
        Initialize and reload cache.
        If datarefs/commands identifier have changed, reassign new identifiers.
        """
        self.stop()
        self.disconnect()
        self.connect()
        self.start()

    # Interface
    def wait_connection(self):
        """Waits that connection to Websocket opens."""
        logger.debug("connecting..")
        while not self.connected:
            logger.debug("..waiting for connection..")
            time.sleep(1)
        logger.debug("..connected")

    def monitor_datarefs(self, datarefs: dict, reason: str | None = None) -> Tuple[int | bool, Dict]:
        """Starts monitoring of supplied datarefs.

        [description]

        Args:
            datarefs (dict): {path: Dataref} dictionary of datarefs
            reason (str | None): Documentation only string to identify call to function.

        Returns:
            Tuple[int | bool, Dict]: [description]
        """
        if not self.connected:
            logger.debug(f"would add {datarefs.keys()}")
            return (False, {})
        if len(datarefs) == 0:
            logger.debug("no dataref to add")
            return (False, {})
        # Add those to monitor
        bulk = {}
        effectives = {}
        for d in datarefs.values():
            if not d.is_monitored:
                ident = d.ident
                if ident is not None:
                    if d.is_array and d.index is not None:
                        if ident not in bulk:
                            bulk[ident] = []
                        bulk[ident].append(d)
                    else:
                        bulk[ident] = d
            d.inc_monitor()
            effectives[d.name] = d

        ret = 0
        if len(bulk) > 0:
            ret = self.register_bulk_dataref_value_event(datarefs=bulk, on=True)
            self._dataref_by_id = self._dataref_by_id | bulk
            dlist = []
            for d in bulk.values():
                if type(d) is list:
                    for d1 in d:
                        dlist.append(d1.name)
                else:
                    dlist.append(d.name)
            logger.debug(f">>>>> monitor_datarefs: {reason}: added {dlist}")
        else:
            logger.debug("no dataref to add")
        return ret, effectives

    def unmonitor_datarefs(self, datarefs: dict, reason: str | None = None) -> Tuple[int | bool, Dict]:
        """Stops monitoring supplied datarefs.

        [description]

        Args:
            datarefs (dict): {path: Dataref} dictionary of datarefs
            reason (str | None): Documentation only string to identify call to function.

        Returns:
            Tuple[int | bool, Dict]: [description]
        """
        if not self.connected:
            logger.debug(f"would remove {datarefs.keys()}")
            return (False, {})
        if len(datarefs) == 0:
            logger.debug("no variable to remove")
            return (False, {})
        # Add those to monitor
        bulk = {}
        effectives = {}
        for d in datarefs.values():
            if d.is_monitored:
                effectives[d.name] = d
                if not d.dec_monitor():  # will be decreased by 1 in super().remove_simulator_variable_to_monitor()
                    ident = d.ident
                    if ident is not None:
                        if d.is_array and d.index is not None:
                            if ident not in bulk:
                                bulk[ident] = []
                            bulk[ident].append(d)
                        else:
                            bulk[ident] = d
                else:
                    logger.debug(f"{d.name} monitored {d.monitored_count} times, not removed")
            else:
                logger.debug(f"no need to remove {d.name}, not monitored")

        ret = 0
        if len(bulk) > 0:
            ret = self.register_bulk_dataref_value_event(datarefs=bulk, on=False)
            for i in bulk.keys():
                if i in self._dataref_by_id:
                    del self._dataref_by_id[i]
                else:
                    logger.warning(f"no dataref for id={self.all_datarefs.equiv(ident=i)}")
            dlist = []
            for d in bulk.values():
                if type(d) is list:
                    for d1 in d:
                        dlist.append(d1.name)
                else:
                    dlist.append(d.name)
            logger.debug(f">>>>> unmonitor_datarefs: {reason}: removed {dlist}")
        else:
            logger.debug("no dataref to remove")

        return ret, effectives

    def monitor_dataref(self, dataref: Dataref) -> bool | int:
        """Starts monitoring single dataref.

        [description]

        Args:
            dataref (Dataref): Dataref to monitor

        Returns:
            bool if fails
            request id if succeeded
        """
        ret = self.monitor_datarefs(datarefs={dataref.path: dataref}, reason="monitor_dataref")
        return ret[0]

    def unmonitor_dataref(self, dataref: Dataref) -> bool | int:
        """Stops monitoring single dataref.

        [description]

        Args:
            dataref (Dataref): Dataref to stop monitoring

        Returns:
            bool if fails
            request id if succeeded
        """
        ret = self.unmonitor_datarefs(datarefs={dataref.path: dataref}, reason="unmonitor_dataref")
        return ret[0]

    def write_dataref(self, dataref: Dataref) -> bool | int:
        """Writes dataref value to simulator.

        Writing is done through REST API if use_rest is True, or Websocket API if use_rest is False and Websocket is opened.

        Args:
            dataref (Dataref): Dataref write to simulator

        Returns:
            bool if fails
            request id if succeeded
        """
        if self.use_rest:
            return super().write_dataref(dataref=dataref)
        if dataref.value_type == DATAREF_DATATYPE.DATA.value:
            return self.set_dataref_value(path=dataref.name, value=dataref.b64encoded)
        return self.set_dataref_value(path=dataref.name, value=dataref._new_value)

    def monitor_command_active(self, command: Command) -> bool | int:
        """Starts monitoring single command for activity.

        Args:
            command (Command): Command to monitor

        Returns:
            bool if fails
            request id if succeeded
        """
        return self.register_command_is_active_event(path=command.path, on=True)

    def unmonitor_command_active(self, command: Command) -> bool | int:
        """Stops monitoring single command for activity.

        Args:
            command (Command): Command to monitor

        Returns:
            bool if fails
            request id if succeeded
        """
        return self.register_command_is_active_event(path=command.path, on=False)

    def execute(self, command: Command, duration: float = 0.0) -> bool | int:
        """Execute command in simulator.

        Execution is done through REST API if use_rest is True, or Websocket API if use_rest is False and Websocket is opened.

        Args:
            command (Command): Command to execute

        Returns:
            bool if fails
            request id if succeeded
        """
        if self.use_rest:
            return super().execute(command=command, duration=duration)
        return self.set_command_is_active_with_duration(path=command.path, duration=duration)
