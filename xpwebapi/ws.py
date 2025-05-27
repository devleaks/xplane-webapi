from __future__ import annotations

import socket
import threading
import logging
import json
import time

from datetime import datetime

# Packaging is used in Cockpit to check driver versions
from packaging.version import Version

from simple_websocket import Client, ConnectionClosed

from .api import webapi_logger, REST_KW, REST_RESPONSE, Dataref, Command
from .rest import XPRestAPI

# local logging
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

XP_MIN_VERSION = 121400
XP_MIN_VERSION_STR = "12.1.4"
XP_MAX_VERSION = 121499
XP_MAX_VERSION_STR = "12.1.4"


# #############################################
# WEBSOCKET API
#
class XPWebsocketAPI(XPRestAPI):
    """Utility routines specific to Websocket API

    See https://developer.x-plane.com/article/x-plane-web-api/#Websockets_API.
    """

    MAX_WARNING = 5  # number of times it reports it cannot connect
    RECONNECT_TIMEOUT = 10  # seconds, times between attempts to reconnect to X-Plane when not connected
    RECEIVE_TIMEOUT = 5  # seconds, assumes no awser if no message recevied withing that timeout

    def __init__(self, host: str = "127.0.0.1", port: int = 8086, api: str = "api", api_version: str = "v2", use_rest: bool = False):
        # Open a UDP Socket to receive on Port 49000
        XPRestAPI.__init__(self, host=host, port=port, api=api, api_version=api_version, use_cache=True)

        self.use_rest = use_rest

        hostname = socket.gethostname()
        self.local_ip = socket.gethostbyname(hostname)

        self.ws = None  # None = no connection
        self.ws_event = threading.Event()
        self.ws_event.set()  # means it is off
        self.ws_thread = None

        self.req_number = 0
        self._requests = {}

        self.should_not_connect = None  # threading.Event()
        self.connect_thread = None  # threading.Thread()
        self._already_warned = 0
        self._stats = {}

        #
        self.on_dataref_update = None
        self.on_command_active = None

    @property
    def ws_url(self) -> str:
        """URL for the Websocket API"""
        return self._url("ws")

    @property
    def next_req(self) -> int:
        """Provides request number for Websocket requests

        Current request number is available through attribute `req_number`
        """
        self.req_number = self.req_number + 1
        return self.req_number

    # ################################
    # Connection to web socket
    #
    @property
    def connected(self) -> bool:
        """Whether Websocket API is reachable"""
        res = self.ws is not None
        if not res and not self._already_warned > self.MAX_WARNING:
            if self._already_warned == self.MAX_WARNING:
                logger.warning("no connection (last warning)")
            else:
                logger.warning("no connection")
            self._already_warned = self._already_warned + 1
        return res

    def connect_websocket(self):
        """Create Websocket if it is reachable"""
        if self.ws is None:
            try:
                if super().connected:
                    url = self.ws_url
                    if url is not None:
                        self.ws = Client.connect(url)
                        self.reload_caches()
                        logger.info(f"websocket opened at {url}")
                    else:
                        logger.warning(f"web socket url is none {url}")
            except:
                logger.error("cannot connect", exc_info=True)
        else:
            logger.warning("already connected")

    def disconnect_websocket(self, silent: bool = False):
        """Closes Websocket connection"""
        if self.ws is not None:
            self.ws.close()
            self.ws = None
            if not silent:
                logger.info("websocket closed")
        else:
            if not silent:
                logger.warning("already disconnected")

    def connect_loop(self):
        """
        Trys to connect to X-Plane indefinitely until self.should_not_connect is set.
        If a connection fails, drops, disappears, will try periodically to restore it.
        """
        logger.debug("starting connection monitor..")
        MAX_TIMEOUT_COUNT = 5
        WARN_FREQ = 10
        number_of_timeouts = 0
        to_count = 0
        noconn = 0
        while self.should_not_connect is not None and not self.should_not_connect.is_set():
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
                        if self.xp_version is not None:
                            curr = Version(self.xp_version)
                            xpmin = Version(XP_MIN_VERSION_STR)
                            xpmax = Version(XP_MAX_VERSION_STR)
                            if curr < xpmin:
                                logger.warning(f"X-Plane version {curr} detected, minimal version is {xpmin}")
                                logger.warning("Some features in Cockpitdecks may not work properly")
                            elif curr > xpmax:
                                logger.warning(f"X-Plane version {curr} detected, maximal version is {xpmax}")
                                logger.warning("Some features in Cockpitdecks may not work properly")
                            else:
                                logger.info(f"X-Plane version requirements {xpmin}<= {curr} <={xpmax} satisfied")
                        logger.debug("..connected, starting websocket listener..")
                        self.start()
                        logger.info("..websocket listener started..")
                    else:
                        if self.ws_event is not None and not self.ws_event.is_set():
                            number_of_timeouts = number_of_timeouts + 1
                            if number_of_timeouts <= MAX_TIMEOUT_COUNT:  # attemps to reconnect
                                logger.info(f"timeout received ({number_of_timeouts}/{MAX_TIMEOUT_COUNT})")  # , exc_info=True
                            if number_of_timeouts >= MAX_TIMEOUT_COUNT:  # attemps to reconnect
                                logger.warning("too many times out, websocket listener terminated")  # ignore
                                self.ws_event.set()

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
                    logger.debug("..no connection. trying to connect..")
            else:
                # Connection is OK, we wait before checking again
                self.should_not_connect.wait(self.RECONNECT_TIMEOUT)  # could be n * RECONNECT_TIMEOUT
                logger.debug("..monitoring connection..")
        logger.debug("..ended connection monitor")

    # ################################
    # Interface
    #
    def connect(self, reload_cache: bool = False):
        """
        Starts connect loop.
        """
        if self.should_not_connect is None:
            self.should_not_connect = threading.Event()
            self.connect_thread = threading.Thread(target=self.connect_loop, name=f"{type(self).__name__}::Connection Monitor")
            self.connect_thread.start()
            logger.debug("connection monitor started")
        else:
            if reload_cache:
                self.reload_caches()
            logger.debug("connection monitor connected")

    def disconnect(self):
        """
        End connect loop and disconnect
        """
        if self.should_not_connect is not None:
            logger.debug("disconnecting..")
            self.disconnect_websocket(silent=True)
            self.should_not_connect.set()
            wait = self.RECONNECT_TIMEOUT
            logger.debug(f"..asked to stop connection monitor.. (this may last {wait} secs.)")
            self.connect_thread.join(timeout=wait)
            if self.connect_thread.is_alive():
                logger.warning("..thread may hang..")
            self.should_not_connect = None
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
        """Send payload message through Websocket

        Args:
            payload (dict): message
            mapping (dict): corresponding {idenfier: path} for printing/debugging

        Returns:
            bool if fails
            request id if succeeded
        """
        if self.connected:
            if payload is not None and len(payload) > 0:
                req_id = self.next_req
                payload[REST_KW.REQID.value] = req_id
                self._requests[req_id] = None  # may be should remember timestamp, etc. if necessary, create Request class.
                self.ws.send(json.dumps(payload))
                webapi_logger.info(f">>SENT {payload}")
                if len(mapping) > 0:
                    maps = [f"{k}={v}" for k, v in mapping.items()]
                    webapi_logger.info(f">> MAP {', '.join(maps)}")
                return req_id
            else:
                logger.warning("no payload")
        logger.warning("not connected")
        return False

    # Dataref operations
    #
    # Note: It is not possible get the the value of a dataref just once
    # through web service. No get_dataref_value().
    #
    def set_dataref_value(self, path, value) -> bool | int:
        """Set dataref value through Websocket

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
        cmdref = self.get_command_meta_by_name(path)
        if cmdref is not None:
            mapping = {cmdref.ident: cmdref.name}
            action = "command_subscribe_is_active" if on else "command_unsubscribe_is_active"
            return self.send({REST_KW.TYPE.value: action, REST_KW.PARAMS.value: {REST_KW.COMMANDS.value: [{REST_KW.IDENT.value: cmdref.ident}]}}, mapping)
        logger.warning(f"command {path} not found in X-Plane commands database")
        return -1

    def register_bulk_command_is_active_event(self, paths, on: bool = True) -> bool | int:
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
        return self.set_command_is_active_without_duration(path=path, active=True)

    def set_command_is_active_false_without_duration(self, path) -> bool | int:
        return self.set_command_is_active_without_duration(path=path, active=False)

    # ################################
    # Start/Run/Stop
    #
    def ws_receiver(self):
        """Read and decode websocket messages and calls back"""
        logger.debug("starting websocket listener..")
        self.RECEIVE_TIMEOUT = 1  # when not connected, checks often
        total_reads = 0
        to_count = 0
        TO_COUNT_DEBUG = 10
        TO_COUNT_INFO = 50
        start_time = datetime.now()
        last_read_ts = start_time
        total_read_time = 0.0
        while not self.ws_event.is_set():
            try:
                message = self.ws.receive(timeout=self.RECEIVE_TIMEOUT)
                if message is None:
                    to_count = to_count + 1
                    if to_count % TO_COUNT_INFO == 0:
                        logger.info("waiting for data from simulator..")  # at {datetime.now()}")
                    elif to_count % TO_COUNT_DEBUG == 0:
                        logger.debug("waiting for data from simulator..")  # at {datetime.now()}")
                    continue

                now = datetime.now()
                if total_reads == 0:
                    logger.debug(f"..first message at {now} ({round((now - start_time).seconds, 2)} secs.)")
                    self.RECEIVE_TIMEOUT = 5  # when connected, check less often, message will arrive

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
                    if resp_type == REST_RESPONSE.RESULT.value:

                        webapi_logger.info(f"<<RCV  {data}")
                        req_id = data.get(REST_KW.REQID.value)
                        if req_id is not None:
                            self._requests[req_id] = data[REST_KW.SUCCESS.value]
                        if not data[REST_KW.SUCCESS.value]:
                            errmsg = REST_KW.SUCCESS.value if data[REST_KW.SUCCESS.value] else "failed"
                            errmsg = errmsg + " " + data.get("error_message")
                            errmsg = errmsg + " (" + data.get("error_code") + ")"
                            logger.warning(f"req. {req_id}: {errmsg}")
                        else:
                            logger.debug(f"req. {req_id}: {REST_KW.SUCCESS.value if data[REST_KW.SUCCESS.value] else 'failed'}")
                    #
                    #
                    elif resp_type == REST_RESPONSE.COMMAND_ACTIVE.value:

                        if REST_KW.DATA.value not in data:
                            logger.warning(f"no data: {data}")
                            continue

                        for ident, value in data[REST_KW.DATA.value].items():
                            meta = self.get_command_meta_by_id(int(ident))
                            if meta is not None:
                                webapi_logger.info(f"CMD : {meta.name}={value}")
                                if self.on_command_active is not None:
                                    self.on_command_active(command=meta.name, active=value)
                            else:
                                logger.warning(f"no command for id={self.all_commands.equiv(ident=int(ident))}")
                    #
                    #
                    elif resp_type == REST_RESPONSE.DATAREF_UPDATE.value:

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
                                    if self.on_dataref_update is not None:
                                        self.on_dataref_update(dataref=d1, value=v1)
                                        # print(f"{d1}={v1}")
                                # alternative:
                                # for d in dataref:
                                #     parsed_value = d.parse_raw_value(value)
                                #     print(f"{d.name}={parsed_value}")
                            else:
                                #
                                # 2. Scalar value
                                parsed_value = dataref.parse_raw_value(value)
                                if self.on_dataref_update is not None:
                                    self.on_dataref_update(dataref=dataref.path, value=parsed_value)
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
                self.ws_event.set()

            except:
                logger.error("ws_receiver: other error", exc_info=True)

        if self.ws is not None:  # in case we did not receive a ConnectionClosed event
            self.ws.close()
            self.ws = None

        logger.info("..websocket listener terminated")

    def start(self, release: bool = True):
        """Start Websocket monitoring"""
        if not self.connected:
            logger.warning("not connected. cannot not start.")
            return

        if self.ws_event.is_set():  # Thread for X-Plane datarefs
            self.ws_event.clear()
            self.ws_thread = threading.Thread(target=self.ws_receiver, name="XPlane::Websocket Listener")
            self.ws_thread.start()
            logger.info("websocket listener started")
        else:
            logger.info("websocket listener already running.")

        # When restarted after network failure, should clean all datarefs
        # then reload datarefs from current page of each deck
        self.reload_caches()
        self.rebuild_dataref_ids()
        logger.info(f"{type(self).__name__} started")

    def stop(self):
        """Stop Websocket monitoring"""
        if not self.ws_event.is_set():
            # if self.all_datarefs is not None:
            #     self.all_datarefs.save("datarefs.json")
            # if self.all_commands is not None:
            #     self.all_commands.save("commands.json")
            self.ws_event.set()
            if self.ws_thread is not None and self.ws_thread.is_alive():
                logger.debug("stopping websocket listener..")
                wait = self.RECEIVE_TIMEOUT
                logger.debug(f"..asked to stop websocket listener (this may last {wait} secs. for timeout)..")
                self.ws_thread.join(wait)
                if self.ws_thread.is_alive():
                    logger.warning("..thread may hang in ws.receive()..")
                logger.info("..websocket listener stopped")
        else:
            logger.debug("websocket listener not running")

    def reset_connection(self):
        """Reset Websocket connection

        Stop existing Websocket connect and create a new one.
        Initialize and load cache if requested.
        If datarefs/commands identifier have changed, reassign new identifiers.
        """
        self.stop()
        self.disconnect()
        self.connect()
        self.start()

    def _add_datarefs_to_monitor(self, datarefs: dict, reason: str | None = None):
        if not self.connected:
            logger.debug(f"would add {datarefs.keys()}")
            return
        if len(datarefs) == 0:
            logger.debug("no dataref to add")
            return
        # Add those to monitor
        bulk = {}
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

        if len(bulk) > 0:
            self.register_bulk_dataref_value_event(datarefs=bulk, on=True)
            self._dataref_by_id = self._dataref_by_id | bulk
            dlist = []
            for d in bulk.values():
                if type(d) is list:
                    for d1 in d:
                        dlist.append(d1.name)
                else:
                    dlist.append(d.name)
            logger.debug(f">>>>> add_datarefs_to_monitor: {reason}: added {dlist}")
        else:
            logger.debug("no dataref to add")

    def _remove_datarefs_to_monitor(self, datarefs: dict, reason: str | None = None):
        if not self.connected and len(self.simulator_variable_to_monitor) > 0:
            logger.debug(f"would remove {datarefs.keys()}/{self._max_datarefs_monitored}")
            return
        if len(datarefs) == 0:
            logger.debug("no variable to remove")
            return
        # Add those to monitor
        bulk = {}
        for d in datarefs.values():
            if d.is_monitored:
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

        if len(bulk) > 0:
            self.register_bulk_dataref_value_event(datarefs=bulk, on=False)
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
            logger.debug(f">>>>> remove_datarefs_to_monitor: {reason}: removed {dlist}")
        else:
            logger.debug("no variable to remove")

    # Interface
    def wait_connection(self):
        logger.debug("connecting..")
        while not self.connected:
            logger.debug("..waiting for connection..")
            time.sleep(1)
        logger.debug("..connected")

    def monitor_dataref(self, dataref: Dataref) -> bool | int:
        return self._add_datarefs_to_monitor(datarefs={dataref.path: dataref}, reason="monitor_dataref")

    def unmonitor_dataref(self, dataref: Dataref) -> bool | int:
        return self._remove_datarefs_to_monitor(datarefs={dataref.path: dataref}, reason="unmonitor_dataref")

    def monitor_command_active(self, command: Command) -> bool | int:
        return self.register_command_is_active_event(path=command.path, on=True)

    def unmonitor_command_active(self, command: Command) -> bool | int:
        return self.register_command_is_active_event(path=command.path, on=False)

    def write_dataref(self, dataref: Dataref) -> bool | int:
        if self.use_rest:
            return super().write_datatef(dataref=dataref)
        return self.set_dataref_value(path=dataref.name, value=dataref._new_value)

    def execute(self, command: Command, duration: float = 0.0) -> bool | int:
        if self.use_rest:
            return super().execute(command=command, duration=duration)
        return self.set_command_is_active_with_duration(path=command.path, duration=duration)
