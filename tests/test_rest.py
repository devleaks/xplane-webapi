import base64
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import httpx

from tests.helpers import mock_response
from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefCache, DatarefMeta
from xpwebapi.rest import V1_CAPABILITIES, XPRestAPI


class RestAPITestCase(unittest.TestCase):
    def make_api(self):
        api = XPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1")
        api.session = MagicMock()
        api._show_stats = False
        return api

    def make_dataref(self, api, value_type="int", is_writable=True, ident=10):
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = DatarefMeta(name=dataref.path, value_type=value_type, is_writable=is_writable, id=ident)
        return dataref

    def make_command(self, api, ident=20):
        command = Command(path="sim/test/command", api=api)
        command._cached_meta = CommandMeta(name=command.path, description="Test command", id=ident)
        return command


class TestXPRestAPIConnected(RestAPITestCase):
    def test_context_manager_closes_session(self):
        api = self.make_api()

        with api as active:
            self.assertIs(active, api)

        api.session.close.assert_called_once()

    def test_pooled_clients_reuse_session_until_last_close(self):
        with patch("xpwebapi.rest.httpx.Client") as client_cls:
            shared_session = MagicMock()
            client_cls.return_value = shared_session

            first = XPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1", pool_connections=True)
            second = XPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1", pool_connections=True)

        self.assertIs(first.session, second.session)

        first.close()
        shared_session.close.assert_not_called()

        second.close()
        shared_session.close.assert_called_once()

    def test_unpooled_clients_keep_independent_sessions(self):
        with patch("xpwebapi.rest.httpx.Client") as client_cls:
            first_session = MagicMock()
            second_session = MagicMock()
            client_cls.side_effect = [first_session, second_session]

            first = XPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1", pool_connections=False)
            second = XPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1", pool_connections=False)

        self.assertIsNot(first.session, second.session)

        first.close()
        first_session.close.assert_called_once()
        second_session.close.assert_not_called()

        second.close()
        second_session.close.assert_called_once()

    def test_pool_configuration_passes_limits_and_timeout_to_httpx_client(self):
        with patch("xpwebapi.rest.httpx.Client") as client_cls:
            client_cls.return_value = MagicMock()

            api = XPRestAPI(
                host="127.0.0.1",
                port=8086,
                api="/api",
                api_version="v1",
                pool_connections=True,
                max_connections=8,
                max_keepalive_connections=4,
                keepalive_expiry=12.5,
                timeout=3.0,
            )

        kwargs = client_cls.call_args.kwargs
        limits = kwargs["limits"]
        timeout = kwargs["timeout"]

        self.assertEqual(limits.max_connections, 8)
        self.assertEqual(limits.max_keepalive_connections, 4)
        self.assertEqual(limits.keepalive_expiry, 12.5)
        self.assertEqual(timeout.as_dict(), {"connect": 3.0, "read": 3.0, "write": 3.0, "pool": 3.0})

        api.close()

    def test_connected_returns_true_for_successful_count_probe(self):
        api = self.make_api()
        api.session.get.return_value = mock_response(200, {"data": 1})
        self.assertTrue(api.connected)
        self.assertEqual(api._unreach_count, 0)

    def test_connected_returns_false_for_non_200_response(self):
        api = self.make_api()
        api.session.get.return_value = mock_response(503)
        self.assertFalse(api.connected)

    def test_connected_returns_false_for_connect_error(self):
        api = self.make_api()
        api.session.get.side_effect = httpx.ConnectError("failed")
        self.assertFalse(api.connected)

    def test_rest_api_reachable_retries_transient_connect_error(self):
        api = XPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1", retry_attempts=3, retry_backoff=0.25)
        api.session = MagicMock()
        api._show_stats = False
        api.session.get.side_effect = [httpx.ConnectError("failed"), mock_response(200, {"data": 1})]

        with patch("xpwebapi.rest.sleep_before_retry") as sleep:
            self.assertTrue(api.connected)

        self.assertEqual(api.session.get.call_count, 2)
        sleep.assert_called_once_with(api.retry_config, 0)


class TestXPRestAPICapabilities(RestAPITestCase):
    def test_capabilities_are_cached_after_successful_fetch(self):
        api = self.make_api()
        payload = {"api": {"versions": ["v1", "v2"]}, "x-plane": {"version": "12.2.1"}}
        api.session.get.return_value = mock_response(200, payload)

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.capabilities, payload)
            self.assertEqual(api.capabilities, payload)

        api.session.get.assert_called_once()

    def test_capabilities_fall_back_to_v1_probe(self):
        api = self.make_api()
        api.session.get.side_effect = [mock_response(404), mock_response(200, {"data": 1})]

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.capabilities, V1_CAPABILITIES)

    def test_set_api_version_selects_latest_available_when_unspecified(self):
        api = self.make_api()
        api._capabilities = {"api": {"versions": ["v1", "v3", "v2"]}, "x-plane": {"version": "12.2.1"}}

        api.set_api_version()

        self.assertEqual(api.version, "v3")
        self.assertEqual(api._api_version, "/v3")


class TestXPRestAPIGetRestMeta(RestAPITestCase):
    def test_get_rest_meta_returns_cached_meta(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertIs(api.get_rest_meta(dataref), dataref._cached_meta)
        api.session.get.assert_not_called()

    def test_get_rest_meta_fetches_dataref_meta(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.session.get.return_value = mock_response(200, {"data": [{"name": dataref.path, "value_type": "int", "is_writable": True, "id": 7}]})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            meta = api.get_rest_meta(dataref)
        self.assertIsInstance(meta, DatarefMeta)
        self.assertEqual(meta.ident, 7)
        self.assertIs(dataref._cached_meta, meta)

    def test_get_rest_meta_fetches_command_meta(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)
        api.session.get.return_value = mock_response(200, {"data": [{"name": command.path, "description": "Test command", "id": 8}]})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            meta = api.get_rest_meta(command)
        self.assertIsInstance(meta, CommandMeta)
        self.assertEqual(meta.ident, 8)
        self.assertIs(command._cached_meta, meta)

    def test_get_rest_meta_returns_none_for_empty_metadata(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.session.get.return_value = mock_response(200, {"data": []})

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertIsNone(api.get_rest_meta(dataref))


class TestXPRestAPIDatarefValue(RestAPITestCase):
    def test_dataref_value_returns_scalar(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.return_value = mock_response(200, {"data": 42})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.dataref_value(dataref), 42)

    def test_dataref_value_decodes_base64_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.return_value = mock_response(200, {"data": encoded})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.dataref_value(dataref), b"abc")

    def test_dataref_value_raw_returns_encoded_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.return_value = mock_response(200, {"data": encoded})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.dataref_value(dataref, raw=True), encoded)

    def test_dataref_value_no_decode_returns_encoded_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.return_value = mock_response(200, {"data": encoded})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.dataref_value(dataref, no_decode=True), encoded)

    def test_dataref_value_returns_none_when_not_connected(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertIsNone(api.dataref_value(dataref))

    def test_dataref_value_returns_none_for_error_response(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.return_value = mock_response(404)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertIsNone(api.dataref_value(dataref))


class TestXPRestAPIWriteDataref(RestAPITestCase):
    def test_write_dataref_success(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        dataref.value = 99
        api.session.patch.return_value = mock_response(200, {"result": "ok"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.write_dataref(dataref))
        api.session.patch.assert_called_once()

    def test_write_dataref_rejects_unwritable_dataref(self):
        api = self.make_api()
        dataref = self.make_dataref(api, is_writable=False)
        dataref.value = 99
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertFalse(api.write_dataref(dataref))
        api.session.patch.assert_not_called()

    def test_write_dataref_rejects_missing_new_value(self):
        api = self.make_api()
        dataref = self.make_dataref(api)

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertFalse(api.write_dataref(dataref))

        api.session.patch.assert_not_called()

    def test_write_dataref_selected_array_element_adds_index_to_url(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/array[2]", api=api)
        dataref._cached_meta = DatarefMeta(name=dataref.path, value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=31)
        dataref.value = 8.5
        api.session.patch.return_value = mock_response(200, {"result": "ok"})

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.write_dataref(dataref))

        url = api.session.patch.call_args.args[0]
        self.assertTrue(url.endswith("/datarefs/31/value?index=2"))

    def test_write_dataref_returns_false_when_not_connected(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertFalse(api.write_dataref(dataref))

    def test_write_dataref_returns_false_for_error_response(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        dataref.value = 99
        api.session.patch.return_value = mock_response(400)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertFalse(api.write_dataref(dataref))


class TestXPRestAPIExecuteCommand(RestAPITestCase):
    def test_execute_command_success(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.post.return_value = mock_response(200, {"result": "ok"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.execute_command(command))
        api.session.post.assert_called_once()

    def test_execute_command_uses_command_duration(self):
        api = self.make_api()
        command = self.make_command(api)
        command.duration = 2.5
        api.session.post.return_value = mock_response(200, {"result": "ok"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.execute_command(command))
        payload = api.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["duration"], 2.5)

    def test_execute_command_returns_false_when_not_connected(self):
        api = self.make_api()
        command = self.make_command(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertFalse(api.execute_command(command))

    def test_execute_command_returns_false_for_error_response(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.post.return_value = mock_response(500, {"error": "boom"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertFalse(api.execute_command(command))


class TestXPRestAPICaches(RestAPITestCase):
    def test_invalidate_caches_clears_loaded_caches(self):
        api = self.make_api()
        api.all_datarefs = DatarefCache(api)
        api.all_commands = MagicMock()

        api.invalidate_caches()

        self.assertIsNone(api.all_datarefs)
        self.assertIsNone(api.all_commands)

    def test_get_dataref_meta_by_id_returns_none_without_cache(self):
        api = self.make_api()

        self.assertIsNone(api.get_dataref_meta_by_id(99))
        self.assertIsNone(api.get_dataref_meta_by_name("sim/test/value"))


if __name__ == "__main__":
    unittest.main()
