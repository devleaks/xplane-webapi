"""Abstract base classes and core classes like Dataref and Command."""

from __future__ import annotations

import logging
import json
import base64
import math
from abc import ABC
from enum import Enum, IntEnum
from datetime import datetime
from typing import Any, Protocol, cast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from .beacon import BeaconData

type DatarefScalarType = bool | str | int | float
type DatarefArrayType = list[int] | list[float]
type DatarefValueType = DatarefScalarType | DatarefArrayType
type DatarefReadResult = DatarefValueType | bytes | None
type APIResult = bool | int


# local logger
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# special logger for all REST or Websocket traffic
WEBAPILOGFILE = "webapi.log"
webapi_logger = logging.getLogger("webapi")
webapi_logger.setLevel(logging.WARNING)
# if WEBAPILOGFILE is not None:
#     formatter = logging.Formatter('"%(asctime)s" %(message)s')
#     handler = logging.FileHandler(WEBAPILOGFILE, mode="w")
#     handler.setFormatter(formatter)
#     webapi_logger.addHandler(handler)
#     webapi_logger.propagate = False


# DATAREF VALUE TYPES
class DATAREF_DATATYPE(Enum):
    """X-Plane API dataref types"""

    INTEGER = "int"
    FLOAT = "float"
    DOUBLE = "double"
    INTARRAY = "int_array"
    FLOATARRAY = "float_array"
    DATA = "data"


class CONNECTION_STATUS(IntEnum):
    """Internal Beacon Connector status"""

    NOT_CONNECTED = 7  # i.e. not receiving beacon
    NO_BEACON = 0  # i.e. not receiving beacon
    RECEIVING_BEACON = 1
    REST_API_REACHABLE = 2
    REST_API_NOT_REACHABLE = 8
    WEBSOCKET_CONNNECTED = 3
    WEBSOCKET_DISCONNNECTED = 9
    UDP_LISTENER_RUNNING = 6
    LISTENING_FOR_DATA = 4
    RECEIVING_DATA = 5


class XPLANE_API_VERSIONS(Enum):
    """API version number (string) versus X-Plane release number when that API version appeared for the first time"""

    v1 = "12.1.1"
    v2 = "12.1.4"


SORT_INDICES = False
ENCODING_CONFIDENCE_THRESHOLD = 0.01


# #############################################
# CORE ENTITIES - META DATA
#
class APIObjMeta(ABC):
    """Container for XP Web API models meta data"""

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

        self.indices: list[int] = []
        self.indices_history: list[list[int]] = []  # past lists of indices, might be useful for requests arriving after new requests

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
            if SORT_INDICES:
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


class ValueCache:
    """Utility class to round a dataref value and determine if it has changed."""

    def __init__(self, roundings: dict[str, int]) -> None:
        self.roundings = roundings  # {dataref: int()}
        self._last_value = {}  # {dataref: Any}

    def get_rounding(self, dataref: str) -> float | None:
        # 1. plain path: sim/some/values[4]
        rnd = self.roundings.get(dataref)
        if rnd is not None:
            return rnd
        # 2. for arrays, all element can use same rounding
        if "[" in dataref:
            root_name = dataref[: dataref.find("[")]  # sim/some/values
            rnd = self.roundings.get(root_name)
            if rnd is not None:
                return rnd
            root_name = root_name + "[*]"  # sim/some/values[*]
            rnd = self.roundings.get(root_name)
            if rnd is not None:
                return rnd
        return None

    def changed(self, dataref: str, value: Any) -> bool:
        if type(value) in [int, float]:
            rnd = self.get_rounding(dataref)
            if rnd is not None:
                new_value = round(value, int(rnd))
                if new_value == self._last_value.get(dataref, math.inf):
                    return False
                self._last_value[dataref] = new_value
        return True


# #############################################
# API
#
class API(Protocol):
    """Protocol with shared API connection helpers."""

    def __init__(self, host: str, port: int, api: str, api_version: str) -> None:
        self.host = None
        self.port = None
        self.version = None
        self._api_root_path = None
        self._api_version = None
        self._use_rest = True  # only option on startup
        self._status = CONNECTION_STATUS.NO_BEACON  # wrong initial value to force update on next instruction and provoque logger.warning
        self.status = CONNECTION_STATUS.NOT_CONNECTED

        self._use_cache = False  # actual use of cache
        self._roundings = None

        self._show_stats = True
        self._stats = {}

        self.session: httpx.Client
        self.use_cache: bool = False
        self.all_datarefs: DatarefCache | None = None
        self.all_commands: CommandCache | None = None

        self.set_network(host=host, port=port, api=api, api_version=api_version)

    @property
    def use_rest(self) -> bool:
        """Should use REST API for some purpose"""
        return self._use_rest

    @use_rest.setter
    def use_rest(self, use_rest):
        self._use_rest = use_rest

    @property
    def status(self) -> CONNECTION_STATUS:
        """Connection status"""
        return self._status

    @property
    def status_str(self) -> str:
        """Connection status as a string"""
        return f"{CONNECTION_STATUS(self._status).name}"

    @status.setter
    def status(self, status: CONNECTION_STATUS):
        """Change connection status and reports it"""
        if self._status != status:
            self._status = status
            logger.info(f"API status is now {self.status_str}")

    @property
    def connected(self) -> bool:
        """Whether X-Plane API is reachable through this instance"""
        ...

    def set_roundings(self, roundings):
        """Add rounding to simulator variable value.
        Rounding is applied to value before it is sent to callback function.
        """
        self._roundings = ValueCache(roundings=roundings)
        logger.info(f"API dataref value rounding set ({len(self._roundings.roundings)})")

    def changed(self, dataref, value) -> bool:
        """If rounding applies, determine if value has changed according to its rounding."""
        return True if self._roundings is None else self._roundings.changed(dataref, value)

    def inc(self, name, count: int = 1):
        if name not in self._stats:
            self._stats[name] = 0
        self._stats[name] = self._stats[name] + count
        if self._show_stats and (self._stats[name] % 500 == 0 or ("/" in name and self._stats[name] % 100 == 0)):
            logger.info(f"*** web api stats: {name}: {self._stats[name]}")

    def get_rest_meta(self, obj: Dataref | Command, force: bool = False) -> DatarefMeta | CommandMeta | None:
        return None

    def set_network(self, host: str, port: int, api: str, api_version: str) -> bool:
        """Set network and API parameters for connection

        Args:
            host (str): Host name or IP address
            port (int): TCP port number for API
            api (str): API root path, starts with /.
            api_version (str): API version string, starts with /, appended to api string to form full path to API.

        Returns:
            bool: True if some network parameter has changed
        """
        ret = False

        if self.host != host:
            self.host = host
            ret = True

        if self.port != port:
            self.port = port
            ret = True

        if not api.startswith("/"):
            api = "/" + api
        if self._api_root_path != api:
            self._api_root_path = api
            ret = True

        if api_version.startswith("/"):  # v1, v2, etc. without /.
            api_version = api_version[1:]
        if self.version != api_version:
            self.version = api_version
            self._api_version = "/" + api_version  # /v1, /v2, to be appended to URL
            ret = True

        return ret

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

    def dataref(self, path: str, auto_save: bool = False) -> Dataref:
        """Create Dataref with current API

        Args:
            path (str): Dataref "path"
            auto_save (bool): Save dataref back to X-Plane if value has changed and writable (default: `False`)

        Returns:
            Dataref: Created dataref
        """
        return Dataref(path=path, api=self, auto_save=auto_save)

    def command(self, path: str) -> Command:
        """Create Command with current API

        Args:
            path (str): Command "path"

        Returns:
            Command: Created command
        """
        return Command(path=path, api=self)

    def write_dataref(self, dataref: Dataref) -> APIResult:
        """Write Dataref value to X-Plane if Dataref is writable

        Args:
            dataref (Dataref): Dataref to write

        Returns:
            APIResult: True/False for immediate APIs, or a request id for queued APIs.
        """
        ...

    def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefReadResult:
        """Returns Dataref value from simulator

        Args:
            dataref (Dataref): Dataref to get the value from
            raw (bool): Return raw value without decoding (default: `False`)
            no_decode (bool): Skip base64 decoding for data types (default: `False`)

        Returns:
            DatarefReadResult: Value of dataref.
        """
        ...

    def execute_command(self, command: Command, duration: float = 0.0) -> APIResult:
        """Execute command

        Args:
            command (Command): Command to execute
            duration (float): Duration of execution for long commands (default: `0.0`)

        Returns:
            APIResult: True/False for immediate APIs, or a request id for queued APIs.
        """
        ...

    def beacon_callback(self, connected: bool, beacon_data: "BeaconData", same_host: bool):
        """Minimal beacon callback function.

        Provided for convenience.

        Args:
            connected (bool): Whether beacon is received
            beacon_data (BeaconData): Beacon data
            same_host (bool): Whether beacon is issued from same host as host running the monitor
        """
        self.status = CONNECTION_STATUS.RECEIVING_BEACON if connected else CONNECTION_STATUS.NO_BEACON


class MetaCacheBase(ABC):
    """Stores X-Plane Web API metadata in cache.

    Must be "refreshed" each time a new connection is created.
    Must be refreshed each time a new aircraft is loaded (for new datarefs, commands, etc.)
    reload_cache() is provided in xpwebapi.

    There is no faster structure than a python dict() for (name,value) pair storage.
    """

    path = ""

    def __init__(self, api) -> None:
        self.api = api
        self._what = ""
        self._raw = {}
        self._by_name = dict()
        self._by_ids = dict()
        self._last_updated = 0

    @classmethod
    def meta(cls, **kwargs) -> APIObjMeta:
        """Create metadata from dictionary returned by X-Plane Web API."""
        raise NotImplementedError("use DatarefCache or CommandCache")

    def load(self):
        """Load cache data"""
        if not self.api.connected:
            logger.warning("not connected")
            return None
        self._what = self.path
        url = self.api.rest_url + self.path
        response = self.api.session.get(url)
        webapi_logger.info(f"GET {self.path}: {url} = {response}")
        if response.status_code != 200:  # We have version 12.1.4 or above
            logger.error(f"load: response={response.status_code}")
            return
        raw = response.json()
        data = raw["data"]
        self._raw = data

        metas = [self.meta(**c) for c in data]
        self._by_name = {m.name: m for m in metas}
        self._by_ids = {m.ident: m for m in metas}

        self.last_cached = datetime.now().timestamp()
        logger.debug(f"{self.path[1:]} cached ({len(metas)} entries)")

    @property
    def count(self) -> int:
        """Number of data in cache"""
        return 0 if self._by_name is None else len(self._by_name)

    @property
    def has_data(self) -> bool:
        """Cache contains data"""
        return self._by_name is not None and len(self._by_name) > 0

    def get(self, name) -> APIObjMeta | None:
        """Get meta data from cache by name"""
        return self.get_by_name(name=name)

    def get_by_name(self, name) -> APIObjMeta | None:
        """Get meta data from cache by name"""
        return self._by_name.get(name)

    def get_by_id(self, ident: int) -> APIObjMeta | None:
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


class DatarefCache(MetaCacheBase):
    """Stores dataref metadata in cache."""

    path = "/datarefs"

    @classmethod
    def meta(cls, **kwargs) -> DatarefMeta:
        """Create DatarefMeta from dictionary returned by X-Plane Web API."""
        return DatarefMeta(**kwargs)

    def get(self, name) -> DatarefMeta | None:
        """Get dataref metadata from cache by name."""
        return self.get_by_name(name=name)

    def get_by_name(self, name) -> DatarefMeta | None:
        """Get dataref metadata from cache by name."""
        return cast(DatarefMeta | None, self._by_name.get(name))

    def get_by_id(self, ident: int) -> DatarefMeta | None:
        """Get dataref metadata from cache by identifier."""
        return cast(DatarefMeta | None, self._by_ids.get(ident))


class CommandCache(MetaCacheBase):
    """Stores command metadata in cache."""

    path = "/commands"

    @classmethod
    def meta(cls, **kwargs) -> CommandMeta:
        """Create CommandMeta from dictionary returned by X-Plane Web API."""
        return CommandMeta(**kwargs)

    def get(self, name) -> CommandMeta | None:
        """Get command metadata from cache by name."""
        return self.get_by_name(name=name)

    def get_by_name(self, name) -> CommandMeta | None:
        """Get command metadata from cache by name."""
        return cast(CommandMeta | None, self._by_name.get(name))

    def get_by_id(self, ident: int) -> CommandMeta | None:
        """Get command metadata from cache by identifier."""
        return cast(CommandMeta | None, self._by_ids.get(ident))


class Cache(MetaCacheBase):
    """Backward-compatible generic metadata cache.

    Prefer DatarefCache or CommandCache for new code.
    """

    @classmethod
    def meta(cls, **kwargs) -> DatarefMeta | CommandMeta:
        """Create metadata using the legacy dataref/command heuristic."""
        return DatarefMeta(**kwargs) if "is_writable" in kwargs else CommandMeta(**kwargs)

    def load(self, path: str | None = None):
        """Load cache data, preserving the old optional path argument."""
        if path is not None:
            self.path = path
        return super().load()


# #############################################
# CORE ENTITIES
#
class Dataref:
    """X-Plane Web API Dataref"""

    def __init__(self, path: str, api: API, auto_save: bool = False):
        self._cached_meta: DatarefMeta | None = None
        self._monitored = 0
        self._encoding = None
        self._new_value = None
        self.auto_save = auto_save

        self.api = api
        self.name = path  # path with array index sim/some/values[4]

        self.path = path  # path with array index sim/some/values[4]
        self.index = None  # sign is it not a selected array element
        if "[" in path:
            self.path = self.name[: self.name.find("[")]  # sim/some/values
            self.index = int(self.name[self.name.find("[") + 1 : self.name.find("]")])  # 4

        self._err = 0
        self._last_updated = datetime.now()

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
        return cast(DatarefMeta | None, self.api.get_rest_meta(self))

    @property
    def valid(self) -> bool:
        """Returns whether meta data for dataref was acquired sucessfully to carry on operations on it"""
        return self.meta is not None

    @property
    def last_updated(self) -> datetime:
        """Returns last time of modification"""
        return self._last_updated

    @property
    def value(self):
        """Return current value of dataref in local application"""
        return self._new_value if self._new_value is not None else self.api.dataref_value(self)

    @value.setter
    def value(self, value):
        """Set value of dataref in local application"""
        self._new_value = value
        self._last_updated = datetime.now()
        if self.auto_save:
            self.write()

    def get_value(self):
        """Return current value of dataref in local application"""
        return self._new_value if self._new_value is not None else self.api.dataref_value(self)

    def get_string_value(self, encoding: str) -> str | None:
        """Decodes current dataref value and replaces it with the decoded string value

        Args:
            encoding (str): Encoding used to decode the bytes value.

        Returns:
            [type]: [description]
        """
        if self.value_type not in ["data"]:
            logger.warning("value type is not data")
            return None
        # https://stackoverflow.com/questions/1021464/how-to-call-a-property-of-the-base-class-if-this-property-is-being-overwritten-i
        value_bytes = Dataref.value.fget(self)  # make sure we call OUT .value property (if overwritten)
        if value_bytes is None:
            logger.debug("no value")
            return None
        if type(value_bytes) is not bytes:
            logger.warning("value is not bytes")
            return None
        if self._encoding is not None and self._encoding != encoding:
            logger.warning(f"string value encodings differ {self._encoding} vs {encoding}")
        try:
            value = value_bytes.decode(encoding)
            value = value.replace("\u0000", "")  # remove trailing 0 (bytes with value 0)
            value = value.replace("\x00", "")  # remove trailing 0 (bytes with value 0)
            self._encoding = encoding
            return value
        except Exception:
            self.add_error()
            logger.warning(f"could not decode value {value_bytes} with encoding {encoding}", exc_info=True)
        return None

    def set_string_value(self, value: str, encoding: str):
        """Set dataref value to base64 encoded representation of string value

        [description]

        Args:
            value (str): [description]
            encoding (str): [description]
        """
        if type(value) is not str:
            logger.warning("value is not a string")
            return value
        if self.value_type != DATAREF_DATATYPE.DATA.value:
            logger.warning("value type is not data")
            return
        if self._encoding is not None and self._encoding != encoding:
            logger.warning(f"string value encodings differ {self._encoding} vs {encoding}")
        try:
            self.value = value.encode(encoding=encoding)
            self._encoding = encoding
        except Exception:
            self.add_error()
            logger.warning(f"could not encode string '{value}'' with encoding {encoding}", exc_info=True)

    @property
    def b64encoded(self) -> str | None:
        if self.value_type == DATAREF_DATATYPE.DATA.value:
            try:
                return base64.b64encode(self.value).decode("ascii")
            except Exception:
                logger.warning(f"could not base64 encode value {self.value}", exc_info=True)
        return None

    @property
    def ident(self) -> int | None:
        """Get dataref identifier meta data"""
        m = self.meta
        if m is None:
            logger.error(f"dataref {self.path} not valid")
            self.add_error()
            return None
        return m.ident

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
        m = self.meta
        if m is None:
            logger.error(f"dataref {self.path} not valid")
            self.add_error()
            return None
        return m.value_type

    @property
    def is_writable(self) -> bool:
        """Whether dataref can be written back to X-Plane"""
        m = self.meta
        if m is None:
            logger.error(f"dataref {self.path} not valid")
            self.add_error()
            return False
        return m.is_writable

    @property
    def is_array(self) -> bool:
        """Whether dataref is an array"""
        if not self.valid:
            logger.error(f"dataref {self.path} not valid")
            self.add_error()
            return False
        return self.value_type in [DATAREF_DATATYPE.INTARRAY.value, DATAREF_DATATYPE.FLOATARRAY.value]

    @property
    def selected_indices(self) -> bool:
        m = self.meta
        if m is None:
            logger.error(f"dataref {self.path} not valid")
            self.add_error()
            return False
        return len(m.indices) > 0

    def write(self) -> APIResult:
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

    def add_error(self, message: str = ""):
        self._err = self._err + 1
        if message != "":
            logger.warning(message)

    def reset_errors(self):
        self._err = 0

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
        m = self.meta
        if m is None:
            logger.error(f"dataref {self.path} not valid")
            return None

        if self.value_type in [DATAREF_DATATYPE.INTARRAY.value, DATAREF_DATATYPE.FLOATARRAY.value]:
            # 1. Arrays
            # 1.1 Whole array
            if type(raw_value) is not list:
                logger.warning(f"dataref array {self.name}: value: is not a list ({raw_value}, {type(raw_value)})")
                return None

            if len(m.indices) == 0:
                logger.debug(f"dataref array {self.name}: no index, returning whole array")
                return raw_value

            # 1.2 Single array element
            if len(raw_value) != len(m.indices):
                logger.warning(f"dataref array {self.name} size mismatch ({len(raw_value)}/{len(m.indices)})")
                logger.warning(f"dataref array {self.name}: value: {raw_value}, indices: {m.indices})")
                return None

            if self.index is not None:
                idx = m.indices.index(self.index)
            else:
                idx = -1
            if idx == -1:
                logger.warning(f"dataref index {self.index} not found in {m.indices}")
                return None

            logger.debug(f"dataref array {self.name}: returning {self.name}[{idx}]={raw_value[idx]}")
            return raw_value[idx]

        else:
            # 2. Scalar values
            # 2.1  Bytes
            if self.value_type == "data" and type(raw_value) is str:
                try:
                    return base64.b64decode(raw_value)
                except Exception:
                    logger.warning(f"failed to decode base64 {self.name}, {self.value_type}: {type(raw_value)} {raw_value}, returning raw value")
                return raw_value
            # 2.1  Number
            elif type(raw_value) not in [int, float]:
                logger.warning(f"unknown value type for {self.name}: {type(raw_value)}, {raw_value}, expected {self.value_type}")

        return raw_value

    def monitor(self) -> bool:
        """Monitor dataref value change"""
        fn = getattr(self.api, "monitor_dataref", None)
        if fn is not None:
            return fn(dataref=self)
        logger.error(f"{self.path}: not a websocket api")
        return False

    def unmonitor(self) -> bool:
        """Unmonitor dataref value change"""
        fn = getattr(self.api, "unmonitor_dataref", None)
        if fn is not None:
            return fn(dataref=self)
        logger.error(f"{self.path}: not a websocket api")
        return False


class Command:
    """X-Plane Web API Command"""

    def __init__(self, api: API, path: str, duration: float = 0.0):
        self._cached_meta: CommandMeta | None = None
        self.api = api
        self.path = path  # some/command
        self.name = path  # some/command
        self.duration = duration

        self._err = 0

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
                self.add_error()
                logger.error(f"command {self.path} has no api meta data in cache")
            else:
                logger.error("no cache data")
        return cast(CommandMeta | None, self.api.get_rest_meta(self))

    @property
    def valid(self) -> bool:
        """Returns whether meta data for command was acquired sucessfully to carry on operations on it"""
        return self.meta is not None

    @property
    def ident(self) -> int | None:
        """Get command identifier meta data"""
        m = self.meta
        if m is None:
            logger.error(f"command {self.path} not valid")
            self.add_error()
            return None
        return m.ident

    @property
    def description(self) -> str | None:
        """Get command description as provided by X-Plane"""
        m = self.meta
        if m is None:
            self.add_error()
            return None
        return m.description

    def add_error(self, message: str = ""):
        self._err = self._err + 1
        if message != "":
            logger.warning(message)

    def reset_errors(self):
        self._err = 0

    def execute(self, duration: float = 0.0) -> APIResult:
        """Execute command through API supplied at creation"""
        return self.api.execute_command(command=self, duration=duration)

    def monitor(self, on: bool = True) -> bool:
        """Monitor command activation through Websocket API"""
        fn = getattr(self.api, "register_command_is_active_event", None)
        if fn is not None:
            return fn(path=self.path, on=on)
        logger.error(f"{self.path}: not a websocket api")
        return False

    def unmonitor(self) -> bool:
        """Suppress monitor command activation through Websocket API"""
        return self.monitor(on=False)
