import logging
import base64
from datetime import timedelta
from typing import Any

import requests

from .api import REST_KW, DATAREF_DATATYPE, API, Dataref, DatarefMeta, Command, CommandMeta, Cache, webapi_logger

# local logging
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


RUNNING_TIME = "sim/time/total_running_time_sec"
FLYING_TIME = "sim/time/total_flight_time_sec"  # Total time since the flight got reset by something

# /api/capabilities introduced in /api/v2. Here is a default one for v1.
V1_CAPABILITIES = {"api": {"versions": ["v1"]}, "x-plane": {"version": "12.1.1"}}


# #############################################
# REST API
#
class XPRestAPI(API):
    """XPlane REST API

    Adds cache for datarefs and commands meta data.

    See Also:
        [X-Plane Web API — REST API](https://developer.x-plane.com/article/x-plane-web-api/#REST_API)
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8086, api: str = "/api", api_version: str = "v1", use_cache: bool = False) -> None:
        API.__init__(self, host=host, port=port, api=api, api_version=api_version)
        self._capabilities = {}

        self._first_try = True
        self._running_time = Dataref(path=RUNNING_TIME, api=self)  # cheating, side effect, works for rest api only, do not force!

        # Caches ids for all known datarefs and commands
        self._should_use_cache = use_cache
        self._use_cache = False
        self.all_datarefs: Cache | None = None
        self.all_commands: Cache | None = None

        self._last_updated = 0
        self._warning_count = 0
        self._dataref_by_id = {}  # {dataref-id: Dataref}

    @property
    def use_cache(self) -> bool:
        """Use cache for object meta data"""
        return self._use_cache

    @use_cache.setter
    def use_cache(self, use_cache) -> bool:
        if use_cache:
            self.reload_caches()  # will set use_cache if caches loaded successfully

    @property
    def uptime(self) -> float:
        """Time X-Plane has been running in seconds since start

        Value is fetched from simulator dataref sim/time/total_running_time_sec
        """
        if self._running_time is not None:
            r = self._running_time.value
            if r is not None:
                return float(r)
        return 0.0

    @property
    def connected(self) -> bool:
        """Whether API is reachable

        API may not be reachable if:
         - X-Plane version before 12.1.4,
         - X-Plane is not running
        """
        CHECK_API_URL = f"http://{self.host}:{self.port}/api/v1/datarefs/count"
        response = None
        if self._first_try:
            logger.info(f"trying to connect to {CHECK_API_URL}..")
            self._first_try = False
        try:
            # Relies on the fact that first version is always provided.
            # Later verion offer alternative ot detect API
            response = requests.get(CHECK_API_URL)
            webapi_logger.info(f"GET {CHECK_API_URL}: {response}")
            if response.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            if self._warning_count % 20 == 0:
                logger.warning("api unreachable, may be X-Plane is not running")
                self._warning_count = self._warning_count + 1
        except:
            logger.error("api unreachable, may be X-Plane is not running", exc_info=True)
        return False

    @property
    def capabilities(self) -> dict:
        """Fetches API capabilties and caches it"""
        if len(self._capabilities) > 0:
            return self._capabilities
        if self.connected:
            try:
                CAPABILITIES_API_URL = f"http://{self.host}:{self.port}/api/capabilities"  # independent from version
                response = requests.get(CAPABILITIES_API_URL)
                webapi_logger.info(f"GET {CAPABILITIES_API_URL}: {response}")
                if response.status_code == 200:  # We have version 12.1.4 or above
                    self._capabilities = response.json()
                    logger.debug(f"capabilities: {self._capabilities}")
                    return self._capabilities
                logger.info(f"capabilities at {self.rest_url + '/capabilities'}: response={response.status_code}")
                url = self.rest_url + "/v1/datarefs/count"
                response = requests.get(url)
                webapi_logger.info(f"GET {url}: {response}")
                if response.status_code == 200:  # OK, /api/v1 exists, we use it, we have version 12.1.1 or above
                    self._capabilities = V1_CAPABILITIES
                    logger.debug(f"capabilities: {self._capabilities}")
                    return self._capabilities
                logger.error(f"capabilities at {self.rest_url + '/datarefs/count'}: response={response.status_code}")
            except:
                logger.error("capabilities", exc_info=True)
        else:
            logger.error("no connection")
        return self._capabilities

    @property
    def xp_version(self) -> str | None:
        """Returns reported X-Plane version from simulator"""
        a = self._capabilities.get("x-plane")
        if a is None:
            return None
        return a.get("version")

    def set_api_version(self, api_version: str | None = None):
        """Set API version

        Version is often specified with a v# short string.
        If no version is supplied, try to take the latest version available.
        Version numbering is not formally specified, therefore alphabetical ordering of strings if used.
        Warning: Version v10 < v2.
        """
        capabilities = self.capabilities
        if len(capabilities) == 0:
            logger.warning("no capabilities, cannot check API version")
            self.version = api_version
            self._api_version = f"/{api_version}"
            logger.warning("no capabilities, cannot check API version")
            logger.info(f"set api {api_version} without control")
            return
        api_details = capabilities.get("api")
        if api_details is not None:
            api_versions = api_details.get("versions")
            if api_version is None:
                if api_versions is None:
                    logger.error("cannot determine api, api not set")
                    return
                api = sorted(api_versions)[-1]  # takes the latest one, hoping it is the latest in time...
                latest = ""
                try:
                    api = f"v{max([int(v.replace('v', '')) for v in api_versions])}"
                    latest = " latest"
                except:
                    pass
                logger.info(f"selected{latest} api {api} ({sorted(api_versions)})")
            if api_version in api_versions:
                self.version = api_version
                self._api_version = f"/{api_version}"
                logger.info(f"set api {api_version}, xp {self.xp_version}")
            else:
                logger.warning(f"no api {api_version} in {api_versions}")
            return
        logger.warning(f"could not check api {api_version} in {capabilities}")

    # Cache
    def reload_caches(self, force: bool = False, save: bool = False):
        """Reload meta data caches

        Must be performed regularly, if aircraft changed, etc.

        Later, Laminar Research has plan for a notification of additing of datarefs

        Args:
            force (bool): Force reloading (default: `False`)
            save (bool): Save raw meta data in JSON formatted files (default: `False`)
        """
        MINTIME_BETWEEN_RELOAD = 10  # seconds
        if not force:
            if self._last_updated != 0:
                currtime = self._running_time.value
                if currtime is not None:
                    currtime = int(currtime)
                    difftime = currtime - self._last_updated
                    if difftime < MINTIME_BETWEEN_RELOAD:
                        logger.info(f"dataref cache not updated, updated {round(difftime, 1)} secs. ago")
                        return
                else:
                    logger.warning(f"no value for {RUNNING_TIME}")
        self.all_datarefs = Cache(self)
        self.all_datarefs.load("/datarefs")
        if save:
            self.all_datarefs.save("webapi-datarefs.json")
        self.all_commands = Cache(self)
        if self.version == "v2":  # >
            self.all_commands.load("/commands")
            if save:
                self.all_commands.save("webapi-commands.json")
        currtime = self._running_time.value
        if currtime is not None:
            self._last_updated = int(currtime)
        else:
            logger.warning(f"no value for {RUNNING_TIME}")
        if self.all_commands.has_data or self.all_datarefs.has_data:
            self._use_cache = self._should_use_cache
            if self._use_cache:
                logger.info("using caches")
        logger.info(
            f"dataref cache ({self.all_datarefs.count}) and command cache ({self.all_commands.count}) reloaded, sim uptime {str(timedelta(seconds=int(self.uptime)))}"
        )

    def rebuild_dataref_ids(self):
        """Rebuild dataref idenfier index"""
        if self.all_datarefs.has_data and len(self._dataref_by_id) > 0:
            self._dataref_by_id = {d.ident: d for d in self._dataref_by_id.values()}
            logger.info("dataref ids rebuilt")
            return
        logger.warning("no data to rebuild dataref ids")

    def get_dataref_meta_by_name(self, path: str) -> DatarefMeta | None:
        """Get dataref meta data by dataref name"""
        return self.all_datarefs.get_by_name(path) if self.all_datarefs is not None else None

    def get_dataref_meta_by_id(self, ident: int) -> DatarefMeta | None:
        """Get dataref meta data by dataref identifier"""
        return self.all_datarefs.get_by_id(ident) if self.all_datarefs is not None else None

    def get_command_meta_by_name(self, path: str) -> CommandMeta | None:
        """Get command meta data by command path"""
        return self.all_commands.get_by_name(path) if self.all_commands is not None else None

    def get_command_meta_by_id(self, ident: int) -> CommandMeta | None:
        """Get command meta data by command identifier"""
        return self.all_commands.get_by_id(ident) if self.all_commands is not None else None

    def write_dataref(self, dataref: Dataref) -> bool:
        """Write single dataref value through REST API

        Returns:

        bool: success of operation
        """
        if not self.connected:
            logger.warning("not connected")
            return None
        if not dataref.valid:
            logger.error(f"dataref {dataref.path} not valid")
            return False
        if not dataref.is_writable:
            logger.warning(f"dataref {dataref.path} is not writable")
            return False
        value = dataref._new_value
        if value is None:
            if dataref.value_type == DATAREF_DATATYPE.DATA.value:
                value = ""
            elif dataref.value_type == DATAREF_DATATYPE.INTEGER.value:
                value = 0
            elif dataref.value_type in [DATAREF_DATATYPE.FLOAT.value, DATAREF_DATATYPE.DOUBLE.value]:
                value = 0.0
            elif dataref.is_array:
                logger.error("no value for array")
                return False
            logger.debug(f"no new value to write, using default {value}")
        if dataref.value_type == DATAREF_DATATYPE.DATA.value:  # Encode string
            value = str(value).encode("ascii")
            value = base64.b64encode(value).decode("ascii")
        payload = {REST_KW.DATA.value: value}
        url = f"{self.rest_url}/datarefs/{dataref.ident}/value"
        if dataref.index is not None and dataref.value_type in [DATAREF_DATATYPE.INTARRAY.value, DATAREF_DATATYPE.FLOATARRAY.value]:
            # Update just one element of the array
            url = url + f"?index={dataref.index}"
        webapi_logger.info(f"PATCH {dataref.path}: {url}, {payload}")
        response = requests.patch(url, json=payload)
        if response.status_code == 200:
            data = response.json()
            logger.debug(f"result: {data}")
            return True
        webapi_logger.info(f"ERROR {dataref.path}: {response} {response.reason} {response.text}")
        logger.error(f"rest_write: {response} {response.reason} {response.text}")
        return False

    def execute(self, command: Command, duration: float = 0.0) -> bool:
        """Executes Command through REST API

        Returns:

        bool: success of operation
        """
        if not self.connected:
            logger.warning("not connected")
            return False
        if not command.valid:
            logger.error(f"command {command.path} is not valid")
            return False
        if duration == 0.0 and command.duration != 0.0:
            duration = command.duration
        payload = {REST_KW.IDENT.value: command.ident, REST_KW.DURATION.value: duration}
        url = f"{self.rest_url}/command/{command.ident}/activate"
        response = requests.post(url, json=payload)
        webapi_logger.info(f"POST {command.path}: {url} {payload} {response}")
        data = response.json()
        if response.status_code == 200:
            logger.debug(f"result: {data}")
            return True
        webapi_logger.info(f"ERROR {command.path}: {response} {response.reason} {response.text}")
        logger.error(f"rest_execute: {response}, {data}")
        return False

    def dataref_value(self, dataref: Dataref) -> Any:
        """Get dataref value through REST API

        Value is not stored or cached.
        """
        if not self.connected:
            logger.warning("not connected")
            return None
        if not dataref.valid:
            logger.error(f"dataref {dataref.path} not valid")
            return False
        url = f"{self.rest_url}/datarefs/{dataref.ident}/value"
        response = requests.get(url)
        if response.status_code == 200:
            respjson = response.json()
            webapi_logger.info(f"GET {dataref.path}: {url} = {respjson}")
            if REST_KW.DATA.value in respjson and type(respjson[REST_KW.DATA.value]) in [bytes, str]:
                return base64.b64decode(respjson[REST_KW.DATA.value]).decode("ascii").replace("\u0000", "")
            return respjson[REST_KW.DATA.value]
        webapi_logger.info(f"ERROR {dataref.path}: {response} {response.reason} {response.text}")
        logger.error(f"rest_value: {response} {response.reason} {response.text}")
        return None
