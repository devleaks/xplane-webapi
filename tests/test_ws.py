import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, PropertyMock, patch

from websockets.exceptions import ConnectionClosedError

from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefMeta
from xpwebapi.retry import RetryConfig
from xpwebapi.rest import REST_KW
from xpwebapi.ws import CALLBACK_TYPE, XPWebsocketAPI


class WebsocketAPITestCase(unittest.TestCase):
    def make_api(self):
        api = XPWebsocketAPI.__new__(XPWebsocketAPI)
        api.host = "127.0.0.1"
        api.port = 8086
        api.version = "v2"
        api._api_root_path = "/api"
        api._api_version = "/v2"
        api._status = 0
        api._stats = {}
        api._show_stats = False
        api._use_rest = False
        api._use_cache = False
        api._should_use_cache = False
        api._first_try = False
        api._warning_count = 0
        api._unreach_count = 0
        api.retry_config = RetryConfig()
        api._already_warned = 0
        api.req_number = 0
        api._requests = {}
        api._dataref_by_id = {}
        api.all_commands = None
        api.all_datarefs = None
        api.session = MagicMock()
        api.session.get.return_value = MagicMock(status_code=503)
        api.ws = MagicMock()
        api.should_not_connect = MagicMock()
        api.should_not_connect.is_set.return_value = True
        api.callbacks = {callback_type.value: set() for callback_type in CALLBACK_TYPE}
        return api


class TestXPWebsocketAPISend(WebsocketAPITestCase):
    def test_send_increments_request_ids_and_writes_json(self):
        api = self.make_api()
        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            first = api.send({"type": "first"})
            second = api.send({"type": "second"})

        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        self.assertIn(first, api._requests)
        sent_payload = json.loads(api.ws.send.call_args_list[0].args[0])
        self.assertEqual(sent_payload["req_id"], 1)

    def test_send_returns_false_when_not_connected(self):
        api = self.make_api()
        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=False):
            with patch("xpwebapi.ws.logger.warning"):
                self.assertFalse(api.send({"type": "test"}))
        api.ws.send.assert_not_called()

    def test_send_returns_false_for_empty_payload(self):
        api = self.make_api()
        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            with patch("xpwebapi.ws.logger.warning"):
                self.assertFalse(api.send({}))
        api.ws.send.assert_not_called()

    def test_send_returns_false_without_allocating_request_when_socket_disappears(self):
        api = self.make_api()
        websocket = api.ws

        def disconnect_during_check():
            api.ws = None
            return True

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, side_effect=disconnect_during_check):
            with patch("xpwebapi.ws.logger.warning"):
                self.assertFalse(api.send({"type": "test"}))

        self.assertEqual(api.req_number, 0)
        self.assertEqual(api._requests, {})
        websocket.send.assert_not_called()


class TestXPWebsocketAPIConnect(WebsocketAPITestCase):
    @patch("xpwebapi.ws.connect")
    def test_connect_websocket_success(self, mock_connect):
        api = self.make_api()
        api.ws = None
        websocket = MagicMock()
        mock_connect.return_value = websocket

        with patch.object(XPWebsocketAPI, "rest_api_reachable", new_callable=PropertyMock, return_value=True):
            with patch.object(XPWebsocketAPI, "reload_caches"):
                api.connect_websocket()

        self.assertIs(api.ws, websocket)
        mock_connect.assert_called_once_with("ws://127.0.0.1:8086/api/v2", proxy=None)

    @patch("xpwebapi.ws.connect")
    def test_connect_websocket_does_not_connect_when_rest_unreachable(self, mock_connect):
        api = self.make_api()
        api.ws = None
        with patch.object(XPWebsocketAPI, "rest_api_reachable", new_callable=PropertyMock, return_value=False):
            with patch("xpwebapi.ws.logger.warning"):
                api.connect_websocket()
        self.assertIsNone(api.ws)
        mock_connect.assert_not_called()

    @patch("xpwebapi.ws.connect")
    def test_connect_websocket_retries_transient_connect_error(self, mock_connect):
        api = self.make_api()
        api.ws = None
        api.retry_config = RetryConfig(attempts=3, backoff=0.25)
        websocket = MagicMock()
        mock_connect.side_effect = [RuntimeError("failed"), websocket]

        with patch.object(XPWebsocketAPI, "rest_api_reachable", new_callable=PropertyMock, return_value=True):
            with patch.object(XPWebsocketAPI, "reload_caches"):
                with patch("xpwebapi.ws.sleep_before_retry") as sleep:
                    with patch("xpwebapi.ws.logger.error"):
                        api.connect_websocket()

        self.assertIs(api.ws, websocket)
        self.assertEqual(mock_connect.call_count, 2)
        sleep.assert_called_once_with(api.retry_config, 0)

    def test_disconnect_websocket_closes_socket_and_runs_callback(self):
        api = self.make_api()
        websocket = api.ws
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_CLOSE, callback)

        api.disconnect_websocket()

        websocket.close.assert_called_once()
        self.assertIsNone(api.ws)
        callback.assert_called_once()

    def test_context_manager_connects_on_enter_and_closes_on_exit(self):
        api = self.make_api()

        with patch.object(api, "connect") as connect:
            with patch.object(api, "close") as close:
                with api as active:
                    self.assertIs(active, api)
                    connect.assert_called_once_with()

                close.assert_called_once_with()


class TestXPWebsocketAPICallbacks(WebsocketAPITestCase):
    def test_add_callback_deduplicates_same_callable(self):
        api = self.make_api()
        callback = MagicMock()

        api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
        api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
        api.execute_callbacks(CALLBACK_TYPE.ON_OPEN)

        callback.assert_called_once()

    def test_execute_callbacks_runs_registered_callbacks(self):
        api = self.make_api()
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
        self.assertTrue(api.execute_callbacks(CALLBACK_TYPE.ON_OPEN))
        callback.assert_called_once()

    def test_execute_callbacks_returns_false_when_callback_raises(self):
        api = self.make_api()
        callback = MagicMock(side_effect=RuntimeError("boom"))
        api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
        with patch("xpwebapi.ws.logger.error"):
            self.assertFalse(api.execute_callbacks(CALLBACK_TYPE.ON_OPEN))

    def test_execute_callbacks_returns_true_when_no_callbacks_registered(self):
        api = self.make_api()
        self.assertTrue(api.execute_callbacks(CALLBACK_TYPE.ON_OPEN))


class TestXPWebsocketAPIMessageHandling(WebsocketAPITestCase):
    def test_result_message_updates_request_and_runs_feedback_callback(self):
        api = self.make_api()
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_REQUEST_FEEDBACK, callback)
        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            req_id = api.send({"type": "test"})
        message = json.dumps(
            {
                REST_KW.TYPE.value: "result",
                REST_KW.REQID.value: req_id,
                REST_KW.SUCCESS.value: False,
                REST_KW.ERROR_MESSAGE.value: "boom",
            }
        )

        api._handle_websocket_message(message, datetime.now())

        self.assertFalse(api._requests[req_id].success)
        self.assertEqual(api._requests[req_id].error, "boom")
        callback.assert_called_once()

    def test_command_active_message_runs_command_callback(self):
        api = self.make_api()
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_COMMAND_ACTIVE, callback)
        api.get_command_meta_by_id = MagicMock(return_value=CommandMeta(name="sim/test/command", description="Test", id=21))
        message = json.dumps({REST_KW.TYPE.value: "command_update_is_active", REST_KW.DATA.value: {"21": True}})

        api._handle_websocket_message(message, datetime.now())

        callback.assert_called_once_with(command="sim/test/command", active=True)

    def test_scalar_dataref_update_runs_dataref_callback(self):
        api = self.make_api()
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_DATAREF_UPDATE, callback)
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = DatarefMeta(name="sim/test/value", value_type="float", is_writable=True, id=11)
        api._dataref_by_id[11] = dataref
        api.changed = MagicMock(return_value=True)
        message = json.dumps({REST_KW.TYPE.value: "dataref_update_values", REST_KW.DATA.value: {"11": 3.5}})

        api._handle_websocket_message(message, datetime.now())

        callback.assert_called_once_with(dataref="sim/test/value", value=3.5)

    def test_array_dataref_update_runs_index_callbacks(self):
        api = self.make_api()
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_DATAREF_UPDATE, callback)
        meta = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=12)
        meta.indices = [2, 4]
        dataref = Dataref(path="sim/test/array[2]", api=api)
        dataref._cached_meta = meta
        api._dataref_by_id[12] = [dataref]
        api.changed = MagicMock(return_value=True)
        message = json.dumps({REST_KW.TYPE.value: "dataref_update_values", REST_KW.DATA.value: {"12": [7.5, 8.5]}})

        api._handle_websocket_message(message, datetime.now())

        callback.assert_any_call(dataref="sim/test/array[2]", value=7.5)
        callback.assert_any_call(dataref="sim/test/array[4]", value=8.5)
        self.assertEqual(callback.call_count, 2)


class TestXPWebsocketAPIListener(WebsocketAPITestCase):
    def test_ws_listener_treats_recv_timeout_as_idle_receive(self):
        api = self.make_api()
        api.RECEIVE_TIMEOUT = 0.01
        api.ws.recv.side_effect = [TimeoutError, '{"type": "result", "req_id": 1, "success": true}']
        api._requests[1] = MagicMock()

        states = [True, True, False]
        with patch.object(XPWebsocketAPI, "websocket_listener_running", new_callable=PropertyMock, side_effect=states):
            with patch.object(api, "_log_receive_timeout") as log_timeout:
                with patch.object(api, "_close_websocket_listener"):
                    api.ws_listener()

        api.ws.recv.assert_any_call(timeout=1)
        log_timeout.assert_called_once_with(0)
        self.assertEqual(api._stats["receive_raw"], 1)
        self.assertEqual(api._stats["receive"], 1)

    def test_ws_listener_handles_connection_closed(self):
        api = self.make_api()
        api.RECEIVE_TIMEOUT = 0.01
        api.ws.recv.side_effect = ConnectionClosedError(None, None)

        states = [True, False]
        with patch.object(XPWebsocketAPI, "websocket_listener_running", new_callable=PropertyMock, side_effect=states):
            with patch.object(api, "_handle_websocket_closed") as handle_closed:
                with patch.object(api, "_close_websocket_listener"):
                    api.ws_listener()

        handle_closed.assert_called_once_with()

    def test_ws_listener_sleeps_when_socket_missing(self):
        api = self.make_api()
        api.ws = None

        states = [True, False]
        with patch.object(XPWebsocketAPI, "websocket_listener_running", new_callable=PropertyMock, side_effect=states):
            with patch("xpwebapi.ws.time.sleep") as sleep:
                api.ws_listener()

        sleep.assert_called_once_with(0.01)


class TestXPWebsocketAPIMonitoring(WebsocketAPITestCase):
    def test_monitor_datarefs_accepts_iterable_and_sends_one_subscribe_request(self):
        api = self.make_api()
        first = Dataref(path="sim/test/first", api=api)
        first._cached_meta = DatarefMeta(name=first.path, value_type="float", is_writable=True, id=101)
        second = Dataref(path="sim/test/second", api=api)
        second._cached_meta = DatarefMeta(name=second.path, value_type="float", is_writable=True, id=102)
        api.send = MagicMock(return_value=7)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.monitor_datarefs([first, second], reason="batch-test")

        self.assertEqual(result, 7)
        self.assertEqual(set(effectives), {first.name, second.name})
        api.send.assert_called_once()
        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "dataref_subscribe_values")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value], [{"id": 101}, {"id": 102}])
        self.assertEqual(api._dataref_by_id, {101: first, 102: second})

    def test_unmonitor_datarefs_accepts_iterable_and_sends_one_unsubscribe_request(self):
        api = self.make_api()
        first = Dataref(path="sim/test/first", api=api)
        first._cached_meta = DatarefMeta(name=first.path, value_type="float", is_writable=True, id=101)
        first.inc_monitor()
        second = Dataref(path="sim/test/second", api=api)
        second._cached_meta = DatarefMeta(name=second.path, value_type="float", is_writable=True, id=102)
        second.inc_monitor()
        api._dataref_by_id = {101: first, 102: second}
        api.send = MagicMock(return_value=8)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.unmonitor_datarefs([first, second], reason="batch-test")

        self.assertEqual(result, 8)
        self.assertEqual(set(effectives), {first.name, second.name})
        api.send.assert_called_once()
        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "dataref_unsubscribe_values")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value], [{"id": 101}, {"id": 102}])
        self.assertEqual(api._dataref_by_id, {})

    def test_monitor_datarefs_groups_selected_array_indices_in_one_request(self):
        api = self.make_api()
        meta = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=201)
        first = Dataref(path="sim/test/array[2]", api=api)
        first._cached_meta = meta
        second = Dataref(path="sim/test/array[4]", api=api)
        second._cached_meta = meta
        api.send = MagicMock(return_value=9)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.monitor_datarefs([first, second], reason="array-test")

        self.assertEqual(result, 9)
        self.assertEqual(set(effectives), {first.name, second.name})
        api.send.assert_called_once()
        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "dataref_subscribe_values")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value], [{"id": 201, "index": [2, 4]}])
        self.assertEqual(api._dataref_by_id, {201: [first, second]})
        self.assertEqual(meta.indices, [2, 4])

    def test_monitor_datarefs_subscribes_only_unmonitored_datarefs(self):
        api = self.make_api()
        first = Dataref(path="sim/test/first", api=api)
        first._cached_meta = DatarefMeta(name=first.path, value_type="float", is_writable=True, id=101)
        second = Dataref(path="sim/test/second", api=api)
        second._cached_meta = DatarefMeta(name=second.path, value_type="float", is_writable=True, id=102)
        second.inc_monitor()
        api.register_bulk_dataref_value_event = MagicMock(return_value=7)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.monitor_datarefs({first.path: first, second.path: second}, reason="test")

        self.assertEqual(result, 7)
        self.assertEqual(set(effectives), {first.name, second.name})
        api.register_bulk_dataref_value_event.assert_called_once()
        bulk = api.register_bulk_dataref_value_event.call_args.kwargs["datarefs"]
        self.assertEqual(list(bulk), [101])
        self.assertEqual(first.monitored_count, 1)
        self.assertEqual(second.monitored_count, 2)

    def test_unmonitor_datarefs_skips_datarefs_still_monitored_elsewhere(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = DatarefMeta(name=dataref.path, value_type="float", is_writable=True, id=103)
        dataref.inc_monitor()
        dataref.inc_monitor()
        api.register_bulk_dataref_value_event = MagicMock(return_value=9)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.unmonitor_datarefs({dataref.path: dataref}, reason="test")

        self.assertEqual(result, 0)
        self.assertEqual(effectives, {dataref.name: dataref})
        api.register_bulk_dataref_value_event.assert_not_called()
        self.assertEqual(dataref.monitored_count, 1)

    def test_monitor_datarefs_returns_false_when_disconnected(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertEqual(api.monitor_datarefs({dataref.path: dataref}), (False, {}))


class TestXPWebsocketAPIPayloads(WebsocketAPITestCase):
    def test_set_dataref_value_sends_scalar_payload(self):
        api = self.make_api()
        meta = DatarefMeta(name="sim/test/value", value_type="float", is_writable=True, id=11)
        api.get_dataref_meta_by_name = MagicMock(return_value=meta)
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.set_dataref_value("sim/test/value", 3.5), 1)

        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "dataref_set_values")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value], [{"id": 11, "value": 3.5}])

    def test_set_dataref_value_sends_array_index_payload(self):
        api = self.make_api()
        meta = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=12)
        api.get_dataref_meta_by_name = MagicMock(return_value=meta)
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.set_dataref_value("sim/test/array[4]", 7.5), 1)

        payload = api.send.call_args.args[0]
        entry = payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value][0]
        self.assertEqual(entry, {"id": 12, "value": 7.5, "index": 4})

    def test_register_command_is_active_event_sends_subscribe_payload(self):
        api = self.make_api()
        api.get_command_meta_by_name = MagicMock(return_value=CommandMeta(name="sim/test/command", description="Test", id=21))
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.register_command_is_active_event("sim/test/command"), 1)

        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "command_subscribe_is_active")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.COMMANDS.value], [{"id": 21}])

    def test_set_command_is_active_with_duration_sends_payload(self):
        api = self.make_api()
        api.get_command_meta_by_name = MagicMock(return_value=CommandMeta(name="sim/test/command", description="Test", id=22))
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.set_command_is_active_with_duration("sim/test/command", duration=1.25), 1)

        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "command_set_is_active")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.COMMANDS.value], [{"id": 22, "is_active": True, "duration": 1.25}])

    def test_write_dataref_uses_websocket_payload_when_rest_disabled(self):
        api = self.make_api()
        meta = DatarefMeta(name="sim/test/value", value_type="float", is_writable=True, id=23)
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = meta
        dataref.value = 5.5
        api.get_rest_meta = MagicMock(return_value=meta)
        api.set_dataref_value = MagicMock(return_value=1)

        self.assertEqual(api.write_dataref(dataref), 1)
        api.set_dataref_value.assert_called_once_with(path="sim/test/value", value=5.5)

    def test_execute_command_uses_websocket_payload_when_rest_disabled(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)
        api.set_command_is_active_with_duration = MagicMock(return_value=1)

        self.assertEqual(api.execute_command(command, duration=0.5), 1)
        api.set_command_is_active_with_duration.assert_called_once_with(path="sim/test/command", duration=0.5)


if __name__ == "__main__":
    unittest.main()
