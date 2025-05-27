from __future__ import annotations

import logging
import json
import base64
from abc import ABC, abstractmethod
from enum import Enum
from datetime import datetime
from typing import List

import requests

# local logger
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# special logger for all REST or Websocket traffic
WEBAPILOGFILE = "webapi.log"
webapi_logger = logging.getLogger("webapi")
# webapi_logger.setLevel(logging.DEBUG)
# if WEBAPILOGFILE is not None:
#     formatter = logging.Formatter('"%(asctime)s" %(message)s')
#     handler = logging.FileHandler(WEBAPILOGFILE, mode="w")
#     handler.setFormatter(formatter)
#     webapi_logger.addHandler(handler)
#     webapi_logger.propagate = False


# REST KEYWORDS
class REST_KW(Enum):
    COMMANDS = "commands"
    DATA = "data"
    DATAREFS = "datarefs"
    DESCRIPTION = "description"
    DURATION = "duration"
    IDENT = "id"
    INDEX = "index"
    ISACTIVE = "is_active"
    ISWRITABLE = "is_writable"
    NAME = "name"
    PARAMS = "params"
    REQID = "req_id"
    RESULT = "result"
    SUCCESS = "success"
    TYPE = "type"
    VALUE = "value"
    VALUE_TYPE = "value_type"


# DATAREF VALUE TYPES
class DATAREF_DATATYPE(Enum):
    """X-Plane API dataref types"""

    INTEGER = "int"
    FLOAT = "float"
    DOUBLE = "double"
    INTARRAY = "int_array"
    FLOATARRAY = "float_array"
    DATA = "data"


# WEB API RETURN CODES
class REST_RESPONSE(Enum):
    """X-Plane REST API response codes"""

    RESULT = "result"
    COMMAND_ACTIVE = "command_update_is_active"
    DATAREF_UPDATE = "dataref_update_values"


# #############################################
# CORE ENTITIES
#
class APIObjMeta(ABC):
    """Container for XP Web API command meta data"""

    def __init__(self, name: str, ident: int) -> None:
        self.name = name
        self.ident = ident
        if ident == -1:
            logger.error(f"{self.name}: invalid identifier")


class DatarefMeta(APIObjMeta):
    """Container for XP Web API dataref meta data"""

    def __init__(self, name: str, value_type: str, is_writable: bool, **kwargs) -> None:
        APIObjMeta.__init__(self, name=name, ident=kwargs.get("id", -1))
        self.value_type = value_type
        self.is_writable = is_writable

        self.indices: List[int] = []
        self.indices_history: List[List[int]] = []  # past lists of indices, might be useful for requests arriving after new requests

        self._last_req_number = 0
        self._indices_requested = False

    @property
    def is_array(self) -> bool:
        """Is dataref an array of values"""
        return self.value_type in [DATAREF_DATATYPE.INTARRAY.value, DATAREF_DATATYPE.FLOATARRAY.value]

    def save_indices(self):
        """Keep a copy of indices as requested"""
        if self._indices_requested:
            self.indices_history.append(self.indices.copy())

    def last_indices(self) -> list:
        """Get list of last requested indices"""
        if len(self.indices_history) > 0:
            return self.indices_history[-1]
        return []

    def append_index(self, i):
        """Add index to list of requested indices for dataref of type array of value

        Note from Web API instruction/manual:
        If you subscribed to certain indexes of the dataref, they’ll be sent in the index order
        but no sparse arrays will be sent. For example if you subscribed to indexes [1, 5, 7] you’ll get
        a 3 item array like [200, 200, 200], meaning you need to remember that the first item of that response
        corresponds to index 1, the second to index 5 and the third to index 7 of the dataref.
        This also means that if you subscribe to index 2 and later to index 0 you’ll get them as [0,2].
        So bottom line is — keep it simple: either ask for a single index, or a range,
        or all; and if later your requirements change, unsubscribe, then subscribe again.
        """
        if i not in self.indices:
            self.indices.append(i)
            self.indices.sort()

    def remove_index(self, i):
        # there is a problem if we remove a key here, and then still get
        # an array of values that contains the removed index.
        # Hence the historical storage of requested indices.
        if i in self.indices:
            self.indices.remove(i)
        else:
            logger.warning(f"{self.name} index {i} not in {self.indices}")


class CommandMeta(APIObjMeta):
    """Container for XP Web API command meta data"""

    def __init__(self, name: str, description: str, **kwargs) -> None:
        APIObjMeta.__init__(self, name=name, ident=kwargs.get("id", -1))
        self.description = description


# #############################################
# API
#
class API(ABC):
    """API Abstract class with connection information"""

    def __init__(self, host: str, port: int, api: str, api_version: str) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self._api_root_path = api
        self.version = api_version  # v1, v2, etc.
        if self.version.startswith("/"):
            self.version = self.version[1:]

        if not self._api_root_path.startswith("/"):
            self._api_root_path = "/" + api
        self._api_version = api_version  # /v1, /v2, to be appended to URL
        if not self._api_version.startswith("/"):
            self._api_version = "/" + self._api_version

        self._use_rest = True  # only option on startup

    @property
    def use_rest(self) -> bool:
        """Should use REST API for some purpose"""
        return self._use_rest

    @use_rest.setter
    def use_rest(self, use_rest):
        self._use_rest = use_rest

    @abstractmethod
    def connected(self) -> bool:
        return False

    def _url(self, protocol: str) -> str:
        """URL builder for the API

        Args:
            protocol (str): URL protocol, either http or ws.

        Returns:
            str: well formed URL from protocol, host, port, and paths portions

        """
        return f"{protocol}://{self.host}:{self.port}{self._api_root_path}{self._api_version}"

    @property
    def rest_url(self) -> str:
        """URL for the REST API"""
        return self._url("http")

    def dataref(self, path, auto_save: bool = False) -> Dataref:
        """Create Dataref with current API"""
        return Dataref(path=path, api=self, auto_save=auto_save)

    def command(self, path) -> Command:
        """Create Command with current API"""
        return Command(path=path, api=self)

    def get_rest_meta(self, obj: Dataref | Command, force: bool = False) -> APIObjMeta | None:
        """Get meta date for object

        Fetches meta data and cache it unless force = True.
        """
        if not self.connected:
            logger.warning("not connected")
            return None
        if not force and obj._cached_meta is not None:
            return obj._cached_meta
        obj._cached_meta = None
        payload = f"filter[name]={obj.path}"
        obj_type = "/datarefs" if type(obj) is Dataref else "/commands"
        url = self.rest_url + obj_type
        response = requests.get(url, params=payload)
        webapi_logger.info(f"GET {obj.path}: {url} = {response}")
        if response.status_code == 200:
            respjson = response.json()
            metadata = respjson[REST_KW.DATA.value]
            if len(metadata) > 0:
                m0 = metadata[0]
                obj._cached_meta = Cache.meta(**m0)
                return obj._cached_meta
        logger.error(f"{obj_type} {obj.path} could not get meta data through REST API")
        return None

    @abstractmethod
    def write_dataref(self, dataref: Dataref) -> bool:
        return False

    @abstractmethod
    def dataref_value(self, dataref: Dataref) -> bool:
        return False

    @abstractmethod
    def execute(self, command: Command) -> bool:
        return False


class Cache:
    """Stores dataref or command meta data in cache

    Must be "refreshed" each time a new connection is created.
    Must be refreshed each time a new aircraft is loaded (for new datarefs, commands, etc.)
    reload_cache() is provided in xpwebapi.

    There is no faster structure than a python dict() for (name,value) pair storage.
    """

    def __init__(self, api: API) -> None:
        self.api = api
        self._what = ""
        self._raw = {}
        self._by_name = dict()
        self._by_ids = dict()
        self._last_updated = 0

    @classmethod
    def meta(cls, **kwargs) -> DatarefMeta | CommandMeta:
        """Create DatarefMeta or CommandMeta from dictionary of meta data returned by X-Plane Web API"""
        return DatarefMeta(**kwargs) if REST_KW.ISWRITABLE.value in kwargs else CommandMeta(**kwargs)

    def load(self, path):
        """Load cache data"""
        if not self.api.connected:
            logger.warning("not connected")
            return None
        self._what = path
        url = self.api.rest_url + path
        response = requests.get(url)
        webapi_logger.info(f"GET {path}: {url} = {response}")
        if response.status_code != 200:  # We have version 12.1.4 or above
            logger.error(f"load: response={response.status_code}")
            return
        raw = response.json()
        data = raw[REST_KW.DATA.value]
        self._raw = data

        metas = [Cache.meta(**c) for c in data]
        self._by_name = {m.name: m for m in metas}
        self._by_ids = {m.ident: m for m in metas}

        self.last_cached = datetime.now().timestamp()
        logger.debug(f"{path[1:]} cached ({len(metas)} entries)")

    @property
    def count(self) -> int:
        """Number of data in cache"""
        return 0 if self._by_name is None else len(self._by_name)

    @property
    def has_data(self) -> bool:
        """Cache contains data"""
        return self._by_name is not None and len(self._by_name) > 0

    def get(self, name) -> DatarefMeta | CommandMeta | None:
        """Get meta data from cache by name"""
        return self.get_by_name(name=name)

    def get_by_name(self, name) -> DatarefMeta | CommandMeta | None:
        """Get meta data from cache by name"""
        return self._by_name.get(name)

    def get_by_id(self, ident: int) -> DatarefMeta | CommandMeta | None:
        """Get meta data from cache by dataref or command identifier"""
        return self._by_ids.get(ident)

    def save(self, filename):
        """Saved cached data into file"""
        with open(filename, "w") as fp:
            json.dump(self._raw, fp)

    def equiv(self, ident) -> str | None:
        """Return identifier/name equivalence, for diaply prupose in format 1234(path/to/object)"""
        r = self._by_ids.get(ident)
        if r is not None:
            return f"{ident}({r.name})"
        return f"no equivalence for {ident}"


class Dataref:
    """X-Plane Web API Dataref"""

    def __init__(self, path: str, api: API, auto_save: bool = False):
        self._cached_meta: DatarefMeta | None = None
        self._monitored = 0
        self._new_value = None
        self.auto_save = auto_save

        self.api = api
        self.name = path  # path with array index sim/some/values[4]

        self.path = path  # path with array index sim/some/values[4]
        self.index = None  # sign is it not a selected array element
        if "[" in path:
            self.path = self.name[: self.name.find("[")]  # sim/some/values
            self.index = int(self.name[self.name.find("[") + 1 : self.name.find("]")])  # 4

    def __str__(self) -> str:
        if self.index is not None:
            return f"{self.path}[{self.index}]={self.value}"
        else:
            return f"{self.path}={self.value}"

    @property
    def meta(self) -> DatarefMeta | None:
        """Meta data of dataref"""
        if self.api.use_cache:
            if self.api.all_datarefs is not None:
                r = self.api.all_datarefs.get(self.path)
                if r is not None:
                    return r
                logger.error(f"dataref {self.path} has no api meta data in cache")
            else:
                logger.error("no cache data")
        return self.api.get_rest_meta(self)

    @property
    def valid(self) -> bool:
        """Returns whether meta data for dataref was acquired sucessfully to carry on operations on it"""
        return self.meta is not None

    @property
    def value(self):
        """Return current value of dataref in local application"""
        return self._new_value if self._new_value is not None else self.api.dataref_value(self)

    @value.setter
    def value(self, value):
        """Set value of dataref in local application"""
        self._new_value = value
        if self.auto_save:
            self.write()

    @property
    def ident(self) -> int | None:
        """Get dataref identifier meta data"""
        if not self.valid:
            logger.error(f"dataref {self.path} not valid")
            return None
        return self.meta.ident

    @property
    def value_type(self) -> str | None:
        """Get dataref value type meta data

        Valid value types are:
            - INTEGER = "int"
            - FLOAT = "float"
            - DOUBLE = "double"
            - INTARRAY = "int_array"
            - FLOATARRAY = "float_array"
            - DATA = "data" """
        if not self.valid:
            logger.error(f"dataref {self.path} not valid")
            return None
        return self.meta.value_type

    @property
    def is_writable(self) -> bool:
        """Whether dataref can be written back to X-Plane"""
        if not self.valid:
            logger.error(f"dataref {self.path} not valid")
            return False
        return self.meta.is_writable

    @property
    def is_array(self) -> bool:
        """Whether dataref is an array"""
        if not self.valid:
            logger.error(f"dataref {self.path} not valid")
            return False
        return self.value_type in [DATAREF_DATATYPE.INTARRAY.value, DATAREF_DATATYPE.FLOATARRAY.value]

    def write(self) -> bool:
        """Write new value to X-Plane through REST API

        Dataref value is saved locally and written to X-Plane when write() or save() is called.
        """
        return self.api.write_dataref(dataref=self)

    # Websocket
    @property
    def is_monitored(self):
        """Whether dataref is currently monitored"""
        return self._monitored > 0

    @property
    def monitored_count(self) -> int:
        """How many times dataref is monitored"""
        return self._monitored

    def inc_monitor(self):
        """Register dataref for monitoring"""
        self._monitored = self._monitored + 1

    def dec_monitor(self) -> bool:
        """Unregister dataref from monitoring

        Returns
        bool: Whether dataref is still monitored after this unmonitoring() call
        """
        if self._monitored > 0:
            self._monitored = self._monitored - 1
        else:
            logger.warning(f"{self.name} currently not monitored")
        return self._monitored > 0

    def parse_raw_value(self, raw_value):
        if not self.valid:
            logger.error(f"dataref {self.path} not valid")
            return None

        if self.value_type in [DATAREF_DATATYPE.INTARRAY.value, DATAREF_DATATYPE.FLOATARRAY.value]:
            # 1. Arrays
            # 1.1 Whole array
            if type(raw_value) is not list:
                logger.warning(f"dataref array {self.name}: value: is not a list ({raw_value}, {type(raw_value)})")
                return None

            if len(self.meta.indices) == 0:
                logger.debug(f"dataref array {self.name}: no index, returning whole array")
                return raw_value

            # 1.2 Single array element
            if len(raw_value) != len(self.meta.indices):
                logger.warning(f"dataref array {self.name} size mismatch ({len(raw_value)}/{len(self.meta.indices)})")
                logger.warning(f"dataref array {self.name}: value: {raw_value}, indices: {self.meta.indices})")
                return None

            idx = self.meta.indices.index(self.index)
            if idx == -1:
                logger.warning(f"dataref index {self.index} not found in {self.meta.indices}")
                return None

            logger.debug(f"dataref array {self.name}: returning {self.name}[{idx}]={raw_value[idx]}")
            return raw_value[idx]

        else:
            # 2. Scalar values
            # 2.1  String
            if self.value_type == "data" and type(raw_value) in [bytes, str]:
                return base64.b64decode(raw_value).decode("ascii").replace("\u0000", "")

            # 2.1  Number
            elif type(raw_value) not in [int, float]:
                logger.warning(f"unknown value type for {self.name}: {type(raw_value)}, {raw_value}, expected {self.value_type}")

        return raw_value

    def monitor(self) -> bool:
        """Monitor dataref value change"""
        if hasattr(self.api, "monitor_dataref"):
            return self.api.monitor_dataref(dataref=self)
        logger.error(f"{self.path}: not a websocket api")
        return False

    def unmonitor(self) -> bool:
        """Unmonitor dataref value change"""
        if hasattr(self.api, "unmonitor_dataref"):
            return self.api.unmonitor_dataref(dataref=self)
        logger.error(f"{self.path}: not a websocket api")
        return False


class Command:
    """X-Plane Web API Command"""

    def __init__(self, api: API, path: str, duration: float = 0.0):
        self._cached_meta = None
        self.api = api
        self.path = path  # some/command
        self.name = path  # some/command
        self.duration = duration

    def __str__(self) -> str:
        return f"{self.path}" if self.name is None else f"{self.name} ({self.path})"

    @property
    def meta(self) -> CommandMeta | None:
        """Meta data of command"""
        if self.api.use_cache:
            if self.api.all_commands is not None:
                r = self.api.all_commands.get(self.path)
                if r is not None:
                    return r
                logger.error(f"command {self.path} has no api meta data in cache")
            else:
                logger.error("no cache data")
        return self.api.get_rest_meta(self)

    @property
    def valid(self) -> bool:
        """Returns whether meta data for command was acquired sucessfully to carry on operations on it"""
        return self.meta is not None

    @property
    def ident(self) -> int | None:
        """Get command identifier meta data"""
        if not self.valid:
            logger.error(f"command {self.path} not valid")
            return None
        return self.meta.ident

    @property
    def description(self) -> str | None:
        """Get command description as provided by X-Plane"""
        if not self.valid:
            return None
        return self.meta.description

    def execute(self, duration: float = 0.0) -> bool:
        """Execute command through API supplied at creation"""
        return self.api.execute(self, duration=duration)

    def monitor(self, on: bool = True) -> bool:
        """Monitor command activation through Websocket API"""
        if hasattr(self.api, "register_command_is_active_event"):
            return self.api.register_command_is_active_event(path=self.path, on=on)
        logger.error(f"{self.path}: not a websocket api")
        return False

    def unmonitor(self) -> bool:
        """Suppress monitor command activation through Websocket API"""
        return self.unmonitor(on=False)
