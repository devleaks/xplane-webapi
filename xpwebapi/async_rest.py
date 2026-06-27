"""Asynchronous X-Plane Web API access through REST."""

from __future__ import annotations

import base64
import logging
from types import TracebackType
from typing import Any, Self, cast

import httpx

from .api import (
    API,
    CONNECTION_STATUS,
    DATAREF_DATATYPE,
    Command,
    CommandCache,
    CommandMeta,
    Dataref,
    DatarefCache,
    DatarefMeta,
    DatarefReadResult,
    ValueCache,
    webapi_logger,
)
from .retry import RetryConfig, async_sleep_before_retry
from .rest import PROXY_TCP_PORT, REST_KW, V1_CAPABILITIES, XP_SUPER_MIN_VERSION

logger = logging.getLogger(__name__)


class AsyncXPRestAPI:
    """Opt-in asynchronous REST client for X-Plane Web API."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8086,
        api: str = "/api",
        api_version: str = "v1",
        use_cache: bool = False,
        retry_attempts: int = 1,
        retry_backoff: float = 0.0,
        retry_backoff_max: float = 5.0,
    ) -> None:
        self.host = None
        self.port = None
        self.version = None
        self._api_root_path = None
        self._api_version = None
        self._status = CONNECTION_STATUS.NO_BEACON
        self.status = CONNECTION_STATUS.NOT_CONNECTED

        self._use_cache = False
        self._should_use_cache = use_cache
        self._roundings = None

        self._show_stats = True
        self._stats = {}

        self._capabilities = {}
        self.retry_config = RetryConfig(attempts=retry_attempts, backoff=retry_backoff, max_backoff=retry_backoff_max)
        self._first_try = True
        self._warning_count = 0
        self._unreach_count = 0

        self.all_datarefs: DatarefCache | None = None
        self.all_commands: CommandCache | None = None

        self.session = httpx.AsyncClient(headers={"Accept": "application/json", "Content-Type": "application/json"})
        self.set_network(host=host, port=port, api=api, api_version=api_version)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _exc_type: type[BaseException] | None, _exc: BaseException | None, _tb: TracebackType | None) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying async HTTP session."""
        await self.session.aclose()

    @property
    def use_cache(self) -> bool:
        """Use cache for object metadata."""
        return self._use_cache

    @use_cache.setter
    def use_cache(self, use_cache: bool) -> None:
        self._should_use_cache = use_cache
        self._use_cache = False
        if use_cache:
            logger.warning("async cache loading is not implemented; per-object metadata fetches will be used")

    @property
    def status(self) -> CONNECTION_STATUS:
        """Connection status."""
        return self._status

    @property
    def status_str(self) -> str:
        """Connection status as a string."""
        return f"{CONNECTION_STATUS(self._status).name}"

    @status.setter
    def status(self, status: CONNECTION_STATUS) -> None:
        if self._status != status:
            self._status = status
            logger.info(f"API status is now {self.status_str}")

    @property
    def connected(self) -> bool:
        """Whether the last async REST probe succeeded."""
        return self.status == CONNECTION_STATUS.REST_API_REACHABLE

    @property
    def rest_url(self) -> str:
        """URL for the REST API."""
        return self._url("http")

    @property
    def has_data(self) -> bool:
        datarefs = self.all_datarefs
        commands = self.all_commands
        return datarefs is not None and datarefs.has_data and commands is not None and commands.has_data

    @property
    def xp_version(self) -> str | None:
        """Returns reported X-Plane version from simulator."""
        details = self._capabilities.get("x-plane")
        if details is None:
            return None
        version = details.get("version")
        return str(version) if version is not None else None

    def set_network(self, host: str, port: int, api: str, api_version: str) -> bool:
        """Set network and API parameters for connection."""
        changed = False
        if self.host != host:
            self.host = host
            changed = True
        if self.port != port:
            self.port = port
            changed = True
        if not api.startswith("/"):
            api = "/" + api
        if self._api_root_path != api:
            self._api_root_path = api
            changed = True
        if api_version.startswith("/"):
            api_version = api_version[1:]
        if self.version != api_version:
            self.version = api_version
            self._api_version = "/" + api_version
            changed = True
        return changed

    def _url(self, protocol: str) -> str:
        return f"{protocol}://{self.host}:{self.port}{self._api_root_path}{self._api_version}"

    def dataref(self, path: str, auto_save: bool = False) -> Dataref:
        """Create a Dataref bound to this async API."""
        if auto_save:
            raise ValueError("auto_save is not supported by AsyncXPRestAPI")
        return Dataref(path=path, api=cast(API, self), auto_save=auto_save)

    def command(self, path: str) -> Command:
        """Create a Command bound to this async API."""
        return Command(path=path, api=cast(API, self))

    def set_roundings(self, roundings: dict[str, int]) -> None:
        """Add rounding to simulator variable value change detection."""
        self._roundings = ValueCache(roundings=roundings)
        logger.info(f"API dataref value rounding set ({len(self._roundings.roundings)})")

    def changed(self, dataref: str, value: Any) -> bool:
        """If rounding applies, determine if value has changed."""
        return True if self._roundings is None else self._roundings.changed(dataref, value)

    def inc(self, name: str, count: int = 1) -> None:
        if name not in self._stats:
            self._stats[name] = 0
        self._stats[name] = self._stats[name] + count
        if self._show_stats and (self._stats[name] % 500 == 0 or ("/" in name and self._stats[name] % 100 == 0)):
            logger.info(f"*** web api stats: {name}: {self._stats[name]}")

    async def rest_api_reachable(self) -> bool:
        """Whether the REST API is reachable."""
        check_url = f"http://{self.host}:{self.port}/api/v1/datarefs/count"
        if self._first_try:
            logger.info(f"trying to connect to {check_url}..")
            self._first_try = False
        for attempt in range(self.retry_config.attempts):
            try:
                self.inc("get")
                response = await self.session.get(check_url)
                webapi_logger.info(f"GET {check_url}: {response}")
                if response.status_code == 200:
                    if self._unreach_count > 0:
                        logger.info("rest api reachable")
                        self._unreach_count = 0
                    self.status = CONNECTION_STATUS.REST_API_REACHABLE
                    return True
                self.status = CONNECTION_STATUS.REST_API_NOT_REACHABLE
                self._unreach_count = self._unreach_count + 1
            except httpx.ConnectError:
                if self._warning_count % 20 == 0:
                    logger.warning("api unreachable, X-Plane may be not running")
                self.status = CONNECTION_STATUS.REST_API_NOT_REACHABLE
                self._warning_count = self._warning_count + 1
                self._unreach_count = self._unreach_count + 1
            if attempt < self.retry_config.attempts - 1:
                await async_sleep_before_retry(self.retry_config, attempt)
        return False

    async def capabilities(self) -> dict:
        """Fetch and cache API capabilities."""
        if len(self._capabilities) > 0:
            return self._capabilities
        if await self.rest_api_reachable():
            try:
                url = f"http://{self.host}:{self.port}/api/capabilities"
                self.inc("get")
                response = await self.session.get(url)
                webapi_logger.info(f"GET {url}: {response}")
                if response.status_code == 200:
                    self._capabilities = response.json()
                    return self._capabilities
                v1_url = f"http://{self.host}:{self.port}{self._api_root_path}/v1/datarefs/count"
                self.inc("get")
                response = await self.session.get(v1_url)
                webapi_logger.info(f"GET {v1_url}: {response}")
                if response.status_code == 200:
                    self._capabilities = V1_CAPABILITIES
                    return self._capabilities
            except Exception:
                logger.error("capabilities", exc_info=True)
        return self._capabilities

    async def get_rest_meta(self, obj: Dataref | Command, force: bool = False) -> DatarefMeta | CommandMeta | None:
        """Get metadata from X-Plane through REST API for an object."""
        if not force and obj._cached_meta is not None:
            return obj._cached_meta
        if not await self.rest_api_reachable():
            logger.warning("not connected")
            return None
        return await self._fetch_rest_meta(obj)

    async def _meta_for(self, obj: Dataref | Command) -> DatarefMeta | CommandMeta | None:
        if obj._cached_meta is not None:
            return obj._cached_meta
        return await self._fetch_rest_meta(obj)

    async def _fetch_rest_meta(self, obj: Dataref | Command) -> DatarefMeta | CommandMeta | None:
        obj._cached_meta = None
        payload = f"filter[name]={obj.path}"
        obj_type = "/datarefs" if isinstance(obj, Dataref) else "/commands"
        url = self.rest_url + obj_type
        self.inc("get")
        response = await self.session.get(url, params=payload)
        webapi_logger.info(f"GET {obj.path}: {url} = {response}")
        if response.status_code == 200:
            metadata = response.json().get(REST_KW.DATA.value, [])
            if len(metadata) > 0:
                if isinstance(obj, Dataref):
                    meta = DatarefCache.meta(**metadata[0])
                    obj._cached_meta = meta
                else:
                    meta = CommandCache.meta(**metadata[0])
                    obj._cached_meta = meta
                return meta
        logger.error(f"{obj_type} {obj.path} could not get meta data through REST API")
        return None

    def get_dataref_meta_by_name(self, path: str) -> DatarefMeta | None:
        """Get cached dataref metadata by dataref name."""
        if self.all_datarefs is not None:
            return self.all_datarefs.get_by_name(path)
        return None

    def get_dataref_meta_by_id(self, ident: int) -> DatarefMeta | None:
        """Get cached dataref metadata by dataref identifier."""
        if self.all_datarefs is not None:
            return self.all_datarefs.get_by_id(ident)
        return None

    def get_command_meta_by_name(self, path: str) -> CommandMeta | None:
        """Get cached command metadata by command path."""
        if self.all_commands is not None:
            return self.all_commands.get_by_name(path)
        return None

    def get_command_meta_by_id(self, ident: int) -> CommandMeta | None:
        """Get cached command metadata by command identifier."""
        if self.all_commands is not None:
            return self.all_commands.get_by_id(ident)
        return None

    async def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefReadResult:
        """Get dataref value through REST API."""
        if not await self.rest_api_reachable():
            logger.debug("not connected")
            return None
        meta = await self._meta_for(dataref)
        if not isinstance(meta, DatarefMeta):
            logger.error(f"dataref {dataref.path} not valid")
            return None
        url = f"{self.rest_url}/datarefs/{meta.ident}/value"
        self.inc("get")
        response = await self.session.get(url)
        if response.status_code == 200:
            payload = response.json()
            webapi_logger.info(f"GET {dataref.path}: {url} = {payload}")
            value = payload[REST_KW.DATA.value]
            if not raw and not no_decode and meta.value_type == DATAREF_DATATYPE.DATA.value and type(value) in [bytes, str]:
                try:
                    return base64.b64decode(value)
                except Exception:
                    logger.warning(f"cannot decode: {response} {response.reason_phrase} {response.text}", exc_info=True)
            return value
        webapi_logger.info(f"ERROR {dataref.path}: {response} {response.reason_phrase} {response.text}")
        logger.error(f"dataref_value: {response} {response.reason_phrase} {response.text}")
        return None

    async def write_dataref(self, dataref: Dataref) -> bool:
        """Write single dataref value through REST API."""
        if not await self.rest_api_reachable():
            logger.warning("not connected")
            return False
        meta = await self._meta_for(dataref)
        if not isinstance(meta, DatarefMeta):
            logger.error(f"dataref {dataref.path} not valid")
            return False
        if not meta.is_writable:
            logger.warning(f"dataref {dataref.path} is not writable")
            return False
        value = dataref._new_value
        if value is None:
            logger.warning(f"dataref {dataref.path} has no new value")
            return False
        if meta.value_type == DATAREF_DATATYPE.DATA.value or type(value) is bytes:
            value = base64.b64encode(value).decode("ascii")
        payload = {REST_KW.DATA.value: value}
        url = f"{self.rest_url}/datarefs/{meta.ident}/value"
        if dataref.index is not None and meta.value_type in [DATAREF_DATATYPE.INTARRAY.value, DATAREF_DATATYPE.FLOATARRAY.value]:
            url = url + f"?index={dataref.index}"
        webapi_logger.info(f"PATCH {dataref.path}: {url}, {payload}")
        self.inc("patch")
        response = await self.session.patch(url, json=payload)
        if response.status_code == 200:
            logger.debug(f"result: {response.json()}")
            return True
        webapi_logger.info(f"ERROR {dataref.path}: {response} {response.reason_phrase} {response.text}")
        logger.error(f"rest_write: {response} {response.reason_phrase} {response.text}")
        return False

    async def execute_command(self, command: Command, duration: float = 0.0) -> bool:
        """Execute command through REST API."""
        if not await self.rest_api_reachable():
            logger.warning("not connected")
            return False
        meta = await self._meta_for(command)
        if not isinstance(meta, CommandMeta):
            logger.error(f"command {command.path} is not valid")
            return False
        if duration == 0.0 and command.duration != 0.0:
            duration = command.duration
        payload = {REST_KW.IDENT.value: meta.ident, REST_KW.DURATION.value: duration}
        url = f"{self.rest_url}/command/{meta.ident}/activate"
        self.inc("post")
        response = await self.session.post(url, json=payload)
        webapi_logger.info(f"POST {command.path}: {url} {payload} {response}")
        data = response.json()
        if response.status_code == 200:
            logger.debug(f"result: {data}")
            return True
        webapi_logger.info(f"ERROR {command.path}: {response} {response.reason_phrase} {response.text}")
        logger.error(f"rest_execute: {response}, {data}")
        return False

    def invalidate_caches(self) -> None:
        """Remove cached metadata."""
        self.all_datarefs = None
        self.all_commands = None
        logger.info("cache invalidated")

    def set_connection_from_beacon_data(self, beacon_data, same_host: bool, remote_tcp_port: int = PROXY_TCP_PORT) -> None:
        api_tcp_port = 8086
        xp_min_version = 121400

        new_host = "127.0.0.1"
        new_port = api_tcp_port
        if not same_host:
            new_host = beacon_data.host
            new_port = remote_tcp_port
        xp_version = beacon_data.xplane_version
        if xp_version is not None:
            new_api_version = "/v1"
            if xp_version >= xp_min_version:
                new_api_version = "/v2"
            elif xp_version < XP_SUPER_MIN_VERSION:
                new_api_version = ""
                logger.warning(f"could not set API version from {xp_version} ({beacon_data})")
            if new_api_version != "" and (new_api_version != self._api_version or new_host != self.host or new_port != self.port):
                self.set_network(host=new_host, port=new_port, api="/api", api_version=new_api_version)
                logger.info(f"XPlane API at {self.rest_url} from UDP beacon data")
        else:
            logger.warning(f"could not get X-Plane version from beacon data {beacon_data}")
