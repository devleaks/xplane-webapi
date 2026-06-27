import base64
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import xpwebapi
from tests.helpers import mock_response
from xpwebapi.api import CONNECTION_STATUS, DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefMeta
from xpwebapi.async_rest import AsyncXPRestAPI
from xpwebapi.rest import V1_CAPABILITIES, XPRestAPI


class AsyncRestAPITestCase(unittest.IsolatedAsyncioTestCase):
    def make_api(self):
        api = AsyncXPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1")
        api.session = MagicMock()
        api.session.get = AsyncMock()
        api.session.post = AsyncMock()
        api.session.patch = AsyncMock()
        api.session.aclose = AsyncMock()
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


class TestAsyncXPRestAPILifecycle(AsyncRestAPITestCase):
    async def test_imports_async_rest_api(self):
        self.assertIs(AsyncXPRestAPI, xpwebapi.AsyncXPRestAPI)

    async def test_aclose_closes_session(self):
        api = self.make_api()
        await api.aclose()
        api.session.aclose.assert_awaited_once()

    async def test_async_context_manager_closes_session(self):
        api = self.make_api()
        async with api as entered:
            self.assertIs(entered, api)
        api.session.aclose.assert_awaited_once()


class TestAsyncXPRestAPIConnected(AsyncRestAPITestCase):
    async def test_rest_api_reachable_returns_true_for_successful_probe(self):
        api = self.make_api()
        api.session.get.return_value = mock_response(200, {"data": 1})
        self.assertTrue(await api.rest_api_reachable())
        self.assertTrue(api.connected)
        self.assertEqual(api.status, CONNECTION_STATUS.REST_API_REACHABLE)

    async def test_rest_api_reachable_returns_false_for_non_200_response(self):
        api = self.make_api()
        api.session.get.return_value = mock_response(503)
        self.assertFalse(await api.rest_api_reachable())
        self.assertFalse(api.connected)

    async def test_rest_api_reachable_returns_false_for_connect_error(self):
        api = self.make_api()
        api.session.get.side_effect = httpx.ConnectError("failed")
        self.assertFalse(await api.rest_api_reachable())
        self.assertEqual(api.status, CONNECTION_STATUS.REST_API_NOT_REACHABLE)

    async def test_successful_reconnect_resets_unreach_count(self):
        api = self.make_api()
        api._unreach_count = 2
        api.session.get.return_value = mock_response(200, {"data": 1})
        self.assertTrue(await api.rest_api_reachable())
        self.assertEqual(api._unreach_count, 0)

    async def test_rest_api_reachable_retries_transient_connect_error(self):
        api = AsyncXPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1", retry_attempts=3, retry_backoff=0.25)
        api.session = MagicMock()
        api.session.get = AsyncMock(side_effect=[httpx.ConnectError("failed"), mock_response(200, {"data": 1})])
        api.session.aclose = AsyncMock()
        api._show_stats = False

        with patch("xpwebapi.async_rest.async_sleep_before_retry", new_callable=AsyncMock) as sleep:
            self.assertTrue(await api.rest_api_reachable())

        self.assertEqual(api.session.get.await_count, 2)
        sleep.assert_awaited_once_with(api.retry_config, 0)


class TestAsyncXPRestAPICapabilities(AsyncRestAPITestCase):
    async def test_capabilities_v1_fallback_uses_unversioned_api_root(self):
        api = AsyncXPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v2")
        api.session = MagicMock()
        api.session.get = AsyncMock(
            side_effect=[
                mock_response(200, {"data": 1}),
                mock_response(404),
                mock_response(200, {"data": 1}),
            ]
        )
        api.session.aclose = AsyncMock()
        api._show_stats = False

        self.assertEqual(await api.capabilities(), V1_CAPABILITIES)
        probed_urls = [call.args[0] for call in api.session.get.await_args_list]
        self.assertIn("http://127.0.0.1:8086/api/v1/datarefs/count", probed_urls)
        self.assertNotIn("http://127.0.0.1:8086/api/v2/v1/datarefs/count", probed_urls)
        await api.aclose()


class TestAsyncXPRestAPIGetRestMeta(AsyncRestAPITestCase):
    async def test_get_rest_meta_returns_cached_meta_without_http(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        self.assertIs(await api.get_rest_meta(dataref), dataref._cached_meta)
        api.session.get.assert_not_awaited()

    async def test_get_rest_meta_fetches_dataref_meta(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.session.get.side_effect = [
            mock_response(200, {"data": 1}),
            mock_response(200, {"data": [{"name": dataref.path, "value_type": "int", "is_writable": True, "id": 7}]}),
        ]
        meta = await api.get_rest_meta(dataref)
        self.assertIsInstance(meta, DatarefMeta)
        self.assertEqual(meta.ident, 7)
        self.assertIs(dataref._cached_meta, meta)

    async def test_get_rest_meta_fetches_command_meta(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)
        api.session.get.side_effect = [
            mock_response(200, {"data": 1}),
            mock_response(200, {"data": [{"name": command.path, "description": "Test command", "id": 8}]}),
        ]
        meta = await api.get_rest_meta(command)
        self.assertIsInstance(meta, CommandMeta)
        self.assertEqual(meta.ident, 8)
        self.assertIs(command._cached_meta, meta)

    async def test_get_rest_meta_returns_none_when_disconnected(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.session.get.return_value = mock_response(503)
        self.assertIsNone(await api.get_rest_meta(dataref))

    async def test_get_rest_meta_returns_none_for_empty_response(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": []})]
        self.assertIsNone(await api.get_rest_meta(dataref))


class TestAsyncXPRestAPIDatarefValue(AsyncRestAPITestCase):
    async def test_dataref_value_returns_scalar(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": 42})]
        self.assertEqual(await api.dataref_value(dataref), 42)

    async def test_shared_mock_response_supports_async_rest(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": 77})]

        self.assertEqual(await api.dataref_value(dataref), 77)

    async def test_dataref_value_decodes_base64_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": encoded})]
        self.assertEqual(await api.dataref_value(dataref), b"abc")

    async def test_dataref_value_raw_returns_encoded_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": encoded})]
        self.assertEqual(await api.dataref_value(dataref, raw=True), encoded)

    async def test_dataref_value_no_decode_returns_encoded_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": encoded})]
        self.assertEqual(await api.dataref_value(dataref, no_decode=True), encoded)

    async def test_dataref_value_returns_none_when_not_connected(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.return_value = mock_response(503)
        self.assertIsNone(await api.dataref_value(dataref))

    async def test_dataref_value_returns_none_when_meta_missing(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": []})]
        self.assertIsNone(await api.dataref_value(dataref))

    async def test_dataref_value_returns_none_for_error_response(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(404)]
        self.assertIsNone(await api.dataref_value(dataref))


class TestAsyncXPRestAPIWriteDataref(AsyncRestAPITestCase):
    async def test_write_dataref_success(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        dataref._new_value = 99
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.patch.return_value = mock_response(200, {"result": "ok"})
        self.assertTrue(await api.write_dataref(dataref))
        api.session.patch.assert_awaited_once()

    async def test_write_dataref_returns_false_when_not_connected(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        dataref._new_value = 99
        api.session.get.return_value = mock_response(503)
        self.assertFalse(await api.write_dataref(dataref))
        api.session.patch.assert_not_awaited()

    async def test_write_dataref_returns_false_when_meta_missing(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._new_value = 99
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": []})]
        self.assertFalse(await api.write_dataref(dataref))

    async def test_write_dataref_rejects_unwritable_dataref(self):
        api = self.make_api()
        dataref = self.make_dataref(api, is_writable=False)
        dataref._new_value = 99
        api.session.get.return_value = mock_response(200, {"data": 1})
        self.assertFalse(await api.write_dataref(dataref))
        api.session.patch.assert_not_awaited()

    async def test_write_dataref_rejects_missing_new_value(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.return_value = mock_response(200, {"data": 1})
        self.assertFalse(await api.write_dataref(dataref))

    async def test_write_dataref_base64_encodes_data_values(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        dataref._new_value = b"abc"
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.patch.return_value = mock_response(200, {"result": "ok"})
        self.assertTrue(await api.write_dataref(dataref))
        payload = api.session.patch.call_args.kwargs["json"]
        self.assertEqual(payload["data"], base64.b64encode(b"abc").decode("ascii"))

    async def test_write_dataref_selected_array_element_adds_index_to_url(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/array[3]", api=api)
        dataref._cached_meta = DatarefMeta(name=dataref.path, value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=11)
        dataref._new_value = 3.14
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.patch.return_value = mock_response(200, {"result": "ok"})
        self.assertTrue(await api.write_dataref(dataref))
        url = api.session.patch.call_args.args[0]
        self.assertTrue(url.endswith("/datarefs/11/value?index=3"))

    async def test_write_dataref_returns_false_for_error_response(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        dataref._new_value = 99
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.patch.return_value = mock_response(400)
        self.assertFalse(await api.write_dataref(dataref))


class TestAsyncXPRestAPIExecuteCommand(AsyncRestAPITestCase):
    async def test_execute_command_success(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.post.return_value = mock_response(200, {"result": "ok"})
        self.assertTrue(await api.execute_command(command))
        api.session.post.assert_awaited_once()

    async def test_execute_command_returns_false_when_not_connected(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.get.return_value = mock_response(503)
        self.assertFalse(await api.execute_command(command))

    async def test_execute_command_returns_false_when_meta_missing(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)
        api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": []})]
        self.assertFalse(await api.execute_command(command))

    async def test_execute_command_sends_explicit_duration(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.post.return_value = mock_response(200, {"result": "ok"})
        self.assertTrue(await api.execute_command(command, duration=1.5))
        payload = api.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["duration"], 1.5)

    async def test_execute_command_uses_command_default_duration(self):
        api = self.make_api()
        command = self.make_command(api)
        command.duration = 2.5
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.post.return_value = mock_response(200, {"result": "ok"})
        self.assertTrue(await api.execute_command(command))
        payload = api.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["duration"], 2.5)

    async def test_execute_command_returns_false_for_error_response(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.get.return_value = mock_response(200, {"data": 1})
        api.session.post.return_value = mock_response(500, {"error": "boom"})
        self.assertFalse(await api.execute_command(command))


class TestAsyncXPRestAPIExports(AsyncRestAPITestCase):
    async def test_dataref_rejects_auto_save_for_async_api(self):
        api = self.make_api()

        with self.assertRaises(ValueError) as caught:
            api.dataref("sim/test/value", auto_save=True)

        self.assertEqual(str(caught.exception), "auto_save is not supported by AsyncXPRestAPI")

    async def test_package_factory_returns_async_rest_api(self):
        api = xpwebapi.async_rest_api()
        try:
            self.assertIsInstance(api, AsyncXPRestAPI)
        finally:
            await api.aclose()

    async def test_sync_rest_factory_still_returns_sync_api(self):
        api = xpwebapi.rest_api()
        try:
            self.assertIsInstance(api, XPRestAPI)
        finally:
            api.session.close()


if __name__ == "__main__":
    unittest.main()
