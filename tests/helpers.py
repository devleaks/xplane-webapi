import base64
import struct
import unittest
from unittest.mock import MagicMock

from xpwebapi.api import API, APIResult, Command, CommandMeta, Dataref, DatarefMeta, DatarefReadResult


def mock_response(status_code: int, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.reason_phrase = "OK" if status_code == 200 else "Error"
    response.text = ""
    response.json.return_value = payload or {}
    return response


class TestHelpersSmoke(unittest.TestCase):
    def test_helpers_are_importable(self):
        helpers = (
            mock_response,
            make_dataref_meta,
            make_command_meta,
            encoded_data,
            make_rref_packet,
            make_beacon_packet,
            DummyAPI,
        )

        for helper in helpers:
            self.assertIsNotNone(helper)


def make_dataref_meta(name: str = "sim/test/value", value_type: str = "int", is_writable: bool = True, ident: int = 10) -> DatarefMeta:
    return DatarefMeta(name=name, value_type=value_type, is_writable=is_writable, id=ident)


def make_command_meta(name: str = "sim/test/command", description: str = "Test command", ident: int = 20) -> CommandMeta:
    return CommandMeta(name=name, description=description, id=ident)


def encoded_data(value: bytes = b"abc") -> str:
    return base64.b64encode(value).decode("ascii")


def make_rref_packet(values: list[tuple[int, float]]) -> bytes:
    packet = b"RREF,"
    for ident, value in values:
        packet += struct.pack("<if", ident, value)
    return packet


def make_beacon_packet(
    hostname: str = "testhost",
    port: int = 49000,
    xplane_version: int = 121400,
    role: int = 1,
    major: int = 1,
    minor: int = 2,
    app_id: int = 1,
) -> bytes:
    header = b"BECN\x00"
    data = struct.pack("<BBiiIH", major, minor, app_id, xplane_version, role, port)
    return header + data + hostname.encode("utf-8") + b"\x00\x00"


class DummyAPI(API):
    def __init__(self, value: DatarefReadResult = None):
        self.meta_by_path = {}
        self.value_to_return = value
        self.written = []
        self.executed = []
        self.monitored_datarefs = []
        self.command_events = []
        super().__init__(host="127.0.0.1", port=8086, api="/api", api_version="v1")

    @property
    def connected(self) -> bool:
        return True

    def get_rest_meta(self, obj: Dataref | Command, force: bool = False) -> DatarefMeta | CommandMeta | None:
        return self.meta_by_path.get(obj.path)

    def write_dataref(self, dataref: Dataref) -> APIResult:
        self.written.append(dataref)
        return True

    def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefReadResult:
        return self.value_to_return

    def execute_command(self, command: Command, duration: float = 0.0) -> APIResult:
        self.executed.append((command, duration))
        return True

    def monitor_dataref(self, dataref: Dataref) -> bool:
        self.monitored_datarefs.append(("monitor", dataref))
        return True

    def unmonitor_dataref(self, dataref: Dataref) -> bool:
        self.monitored_datarefs.append(("unmonitor", dataref))
        return True

    def register_command_is_active_event(self, path: str, on: bool = True) -> bool:
        self.command_events.append((path, on))
        return True
