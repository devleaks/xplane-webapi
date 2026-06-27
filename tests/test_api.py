import base64
import inspect
import unittest
from tempfile import TemporaryDirectory
from typing import Protocol
from unittest.mock import MagicMock

from tests.helpers import DummyAPI, encoded_data, make_command_meta, make_dataref_meta, mock_response
from xpwebapi.api import (
    API,
    DATAREF_DATATYPE,
    Cache,
    CommandCache,
    Command,
    CommandMeta,
    DatarefCache,
    Dataref,
    DatarefMeta,
    ValueCache,
)


class TestAPIProtocol(unittest.TestCase):
    def test_api_is_structural_protocol_without_abstract_methods(self):
        self.assertIn(Protocol, API.__mro__)
        self.assertFalse(inspect.isabstract(API))
        self.assertEqual(API.__abstractmethods__, frozenset())


class TestDatarefMeta(unittest.TestCase):
    def test_construction(self):
        meta = DatarefMeta(name="sim/test/value", value_type="int", is_writable=True, id=42)
        self.assertEqual(meta.name, "sim/test/value")
        self.assertEqual(meta.value_type, "int")
        self.assertTrue(meta.is_writable)
        self.assertEqual(meta.ident, 42)

    def test_is_array_for_array_types(self):
        int_array = DatarefMeta(name="sim/test/int_array", value_type=DATAREF_DATATYPE.INTARRAY.value, is_writable=False, id=1)
        float_array = DatarefMeta(name="sim/test/float_array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=False, id=2)
        scalar = DatarefMeta(name="sim/test/scalar", value_type=DATAREF_DATATYPE.FLOAT.value, is_writable=False, id=3)
        self.assertTrue(int_array.is_array)
        self.assertTrue(float_array.is_array)
        self.assertFalse(scalar.is_array)

    def test_indices_are_unique_and_historical(self):
        meta = DatarefMeta(name="sim/test/array", value_type="int_array", is_writable=False, id=1)
        meta.append_index(3)
        meta.append_index(1)
        meta.append_index(3)
        self.assertEqual(meta.indices, [3, 1])

        meta._indices_requested = True
        meta.save_indices()
        meta.remove_index(3)
        self.assertEqual(meta.indices, [1])
        self.assertEqual(meta.last_indices(), [3, 1])


class TestCommandMeta(unittest.TestCase):
    def test_construction(self):
        meta = CommandMeta(name="sim/test/command", description="Test command", id=99)
        self.assertEqual(meta.name, "sim/test/command")
        self.assertEqual(meta.description, "Test command")
        self.assertEqual(meta.ident, 99)


class TestValueCache(unittest.TestCase):
    def test_get_rounding_supports_plain_root_and_wildcard(self):
        cache = ValueCache({"sim/test/plain": 2, "sim/test/root": 3, "sim/test/wild[*]": 1})
        self.assertEqual(cache.get_rounding("sim/test/plain"), 2)
        self.assertEqual(cache.get_rounding("sim/test/root[4]"), 3)
        self.assertEqual(cache.get_rounding("sim/test/wild[7]"), 1)
        self.assertIsNone(cache.get_rounding("sim/test/missing"))

    def test_changed_tracks_rounded_numeric_values(self):
        cache = ValueCache({"sim/test/value": 2})
        self.assertTrue(cache.changed("sim/test/value", 3.14159))
        self.assertFalse(cache.changed("sim/test/value", 3.14))
        self.assertTrue(cache.changed("sim/test/value", 3.15))

    def test_changed_returns_true_for_non_numeric_values(self):
        cache = ValueCache({"sim/test/value": 2})
        self.assertTrue(cache.changed("sim/test/value", "hello"))


class TestDatarefCache(unittest.TestCase):
    def test_meta_factory_creates_dataref_meta(self):
        meta = DatarefCache.meta(name="sim/test/value", value_type="int", is_writable=True, id=1)
        self.assertIsInstance(meta, DatarefMeta)
        self.assertEqual(meta.name, "sim/test/value")
        self.assertEqual(meta.value_type, "int")
        self.assertTrue(meta.is_writable)

    def test_lookup_by_name_and_id(self):
        cache = DatarefCache(DummyAPI())
        meta = DatarefMeta(name="sim/test/value", value_type="int", is_writable=True, id=7)
        cache._by_name = {meta.name: meta}
        cache._by_ids = {meta.ident: meta}
        self.assertIs(cache.get("sim/test/value"), meta)
        self.assertIs(cache.get_by_name("sim/test/value"), meta)
        self.assertIs(cache.get_by_id(7), meta)
        self.assertIsNone(cache.get_by_name("sim/test/missing"))
        self.assertIsNone(cache.get_by_id(99))
        self.assertEqual(cache.count, 1)
        self.assertTrue(cache.has_data)
        self.assertEqual(cache.equiv(7), "7(sim/test/value)")

    def test_load_uses_datarefs_endpoint(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(200, {"data": [{"name": "sim/test/value", "value_type": "int", "is_writable": True, "id": 7}]})
        cache = DatarefCache(api)
        cache.load()
        api.session.get.assert_called_once_with(f"{api.rest_url}/datarefs")
        self.assertIsInstance(cache.get_by_name("sim/test/value"), DatarefMeta)

    def test_failed_load_leaves_cache_empty(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(500)
        cache = DatarefCache(api)
        cache.load()
        self.assertEqual(cache.count, 0)
        self.assertFalse(cache.has_data)

    def test_save_writes_loaded_metadata_json(self):
        api = DummyAPI()
        cache = DatarefCache(api)
        meta = make_dataref_meta(name="sim/test/value", ident=7)
        cache._raw = [{"name": meta.name, "value_type": meta.value_type, "is_writable": meta.is_writable, "id": meta.ident}]
        cache._by_name = {meta.name: meta}
        cache._by_ids = {meta.ident: meta}

        with TemporaryDirectory() as tmpdir:
            filename = f"{tmpdir}/datarefs.json"
            cache.save(filename)
            with open(filename, encoding="utf-8") as handle:
                content = handle.read()

        self.assertIn("sim/test/value", content)
        self.assertIn('"id": 7', content)


class TestCommandCache(unittest.TestCase):
    def test_meta_factory_creates_command_meta(self):
        meta = CommandCache.meta(name="sim/test/command", description="Test command", id=2)
        self.assertIsInstance(meta, CommandMeta)
        self.assertEqual(meta.name, "sim/test/command")
        self.assertEqual(meta.description, "Test command")

    def test_lookup_by_name_and_id(self):
        cache = CommandCache(DummyAPI())
        meta = CommandMeta(name="sim/test/command", description="Test command", id=8)
        cache._by_name = {meta.name: meta}
        cache._by_ids = {meta.ident: meta}
        self.assertIs(cache.get("sim/test/command"), meta)
        self.assertIs(cache.get_by_name("sim/test/command"), meta)
        self.assertIs(cache.get_by_id(8), meta)
        self.assertIsNone(cache.get_by_name("sim/test/missing"))
        self.assertIsNone(cache.get_by_id(99))
        self.assertEqual(cache.count, 1)
        self.assertTrue(cache.has_data)
        self.assertEqual(cache.equiv(8), "8(sim/test/command)")

    def test_load_uses_commands_endpoint(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(200, {"data": [{"name": "sim/test/command", "description": "Test command", "id": 8}]})
        cache = CommandCache(api)
        cache.load()
        api.session.get.assert_called_once_with(f"{api.rest_url}/commands")
        self.assertIsInstance(cache.get_by_name("sim/test/command"), CommandMeta)


class TestCacheCompatibility(unittest.TestCase):
    def test_meta_factory_keeps_old_dataref_heuristic(self):
        meta = Cache.meta(name="sim/test/value", value_type="int", is_writable=True, id=1)
        self.assertIsInstance(meta, DatarefMeta)

    def test_meta_factory_keeps_old_command_heuristic(self):
        meta = Cache.meta(name="sim/test/command", description="Test command", id=2)
        self.assertIsInstance(meta, CommandMeta)

    def test_load_accepts_old_path_argument(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(200, {"data": [{"name": "sim/test/value", "value_type": "int", "is_writable": True, "id": 7}]})
        cache = Cache(api)
        cache.load("/datarefs")
        api.session.get.assert_called_once_with(f"{api.rest_url}/datarefs")
        self.assertIsInstance(cache.get_by_name("sim/test/value"), DatarefMeta)


class TestDataref(unittest.TestCase):
    def test_indexed_path_parses_base_path_and_index(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/array[4]", api=api)

        self.assertEqual(dataref.name, "sim/test/array[4]")
        self.assertEqual(dataref.path, "sim/test/array")
        self.assertEqual(dataref.index, 4)

    def test_string_representation_includes_index_and_value(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/array[4]", api=api)
        dataref.value = 12.5

        self.assertEqual(str(dataref), "sim/test/array[4]=12.5")

    def test_get_string_value_decodes_data_bytes_and_strips_nulls(self):
        api = DummyAPI(value=b"ABC\x00\x00")
        api.meta_by_path["sim/test/data"] = make_dataref_meta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value)
        dataref = Dataref(path="sim/test/data", api=api)

        self.assertEqual(dataref.get_string_value("ascii"), "ABC")

    def test_set_string_value_encodes_data_value(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/data"] = make_dataref_meta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value)
        dataref = Dataref(path="sim/test/data", api=api)

        dataref.set_string_value("ABC", "ascii")

        self.assertEqual(dataref.value, b"ABC")
        self.assertEqual(dataref.b64encoded, encoded_data(b"ABC"))

    def test_value_reads_from_api_when_no_local_value_exists(self):
        api = DummyAPI(value=12)
        dataref = Dataref(path="sim/test/value", api=api)
        self.assertEqual(dataref.value, 12)

    def test_value_supports_array_values_from_api(self):
        api = DummyAPI(value=[1.0, 2.0])
        dataref = Dataref(path="sim/test/array", api=api)
        self.assertEqual(dataref.value, [1.0, 2.0])

    def test_setting_value_updates_local_value_and_timestamp(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/value", api=api)
        before = dataref.last_updated
        dataref.value = 34
        self.assertEqual(dataref.value, 34)
        self.assertGreaterEqual(dataref.last_updated, before)

    def test_auto_save_writes_on_value_change(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/value", api=api, auto_save=True)
        dataref.value = 56
        self.assertEqual(api.written, [dataref])

    def test_parse_scalar_value(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/value"] = DatarefMeta(name="sim/test/value", value_type="int", is_writable=False, id=1)
        dataref = Dataref(path="sim/test/value", api=api)
        self.assertEqual(dataref.parse_raw_value(42), 42)

    def test_parse_data_value_decodes_base64(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/data"] = DatarefMeta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value, is_writable=False, id=1)
        dataref = Dataref(path="sim/test/data", api=api)
        raw = base64.b64encode(b"abc").decode("ascii")
        self.assertEqual(dataref.parse_raw_value(raw), b"abc")

    def test_parse_array_element_uses_requested_indices(self):
        api = DummyAPI()
        meta = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=False, id=1)
        meta.append_index(0)
        meta.append_index(2)
        api.meta_by_path["sim/test/array"] = meta
        dataref = Dataref(path="sim/test/array[2]", api=api)
        self.assertEqual(dataref.parse_raw_value([10.0, 20.0]), 20.0)

    def test_parse_whole_array_when_no_indices_requested(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/array"] = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=False, id=1)
        dataref = Dataref(path="sim/test/array", api=api)
        self.assertEqual(dataref.parse_raw_value([1.0, 2.0]), [1.0, 2.0])

    def test_write_monitor_and_unmonitor_delegate_to_api(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/value", api=api)
        self.assertTrue(dataref.write())
        self.assertTrue(dataref.monitor())
        self.assertTrue(dataref.unmonitor())
        self.assertEqual(api.written, [dataref])
        self.assertEqual(api.monitored_datarefs, [("monitor", dataref), ("unmonitor", dataref)])

    def test_invalid_meta_properties_record_errors(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/missing", api=api)

        self.assertFalse(dataref.valid)
        self.assertIsNone(dataref.ident)
        self.assertIsNone(dataref.value_type)
        self.assertFalse(dataref.is_writable)
        self.assertGreaterEqual(dataref._err, 3)

    def test_monitor_counter_tracks_nested_monitoring(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/value", api=api)

        dataref.inc_monitor()
        dataref.inc_monitor()

        self.assertTrue(dataref.is_monitored)
        self.assertEqual(dataref.monitored_count, 2)
        self.assertTrue(dataref.dec_monitor())
        self.assertFalse(dataref.dec_monitor())
        self.assertEqual(dataref.monitored_count, 0)


class TestCommand(unittest.TestCase):
    def test_command_metadata_properties_use_cached_meta(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/command"] = make_command_meta(ident=44)
        command = Command(path="sim/test/command", api=api)

        self.assertTrue(command.valid)
        self.assertEqual(command.ident, 44)
        self.assertEqual(command.description, "Test command")

    def test_command_invalid_metadata_records_errors(self):
        api = DummyAPI()
        command = Command(path="sim/test/missing", api=api)

        self.assertFalse(command.valid)
        self.assertIsNone(command.ident)
        self.assertIsNone(command.description)
        self.assertGreaterEqual(command._err, 2)

    def test_execute_delegates_to_api(self):
        api = DummyAPI()
        command = Command(path="sim/test/command", api=api)
        self.assertTrue(command.execute(duration=1.5))
        self.assertEqual(api.executed, [(command, 1.5)])

    def test_monitor_and_unmonitor_delegate_to_api(self):
        api = DummyAPI()
        command = Command(path="sim/test/command", api=api)
        self.assertTrue(command.monitor())
        self.assertTrue(command.unmonitor())
        self.assertEqual(api.command_events, [("sim/test/command", True), ("sim/test/command", False)])


if __name__ == "__main__":
    unittest.main()
