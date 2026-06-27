import importlib
import socket
import unittest
from unittest.mock import MagicMock, patch

import xpwebapi
from tests.helpers import make_beacon_packet
from xpwebapi.beacon import BEACON_MONITOR_STATUS, BeaconData, XPBeaconMonitor, XPlaneNoBeacon, XPlaneVersionNotSupported

beacon_module = importlib.import_module("xpwebapi.beacon")


class BeaconMonitorTestCase(unittest.TestCase):
    def make_monitor(self):
        with patch("xpwebapi.beacon.list_my_ips", return_value=[]):
            return XPBeaconMonitor()

    def mock_sockets(self, recvfrom):
        monitor_socket = MagicMock()
        beacon_socket = MagicMock()
        beacon_socket.recvfrom.side_effect = recvfrom if isinstance(recvfrom, BaseException) else None
        if not isinstance(recvfrom, BaseException):
            beacon_socket.recvfrom.return_value = recvfrom
        return patch("xpwebapi.beacon.socket.socket", side_effect=[monitor_socket, beacon_socket]), beacon_socket


class TestBeaconData(unittest.TestCase):
    def test_construction(self):
        data = BeaconData(host="10.0.0.1", port=49000, hostname="xp", xplane_version=121400, role=1)
        self.assertEqual(data.host, "10.0.0.1")
        self.assertEqual(data.port, 49000)
        self.assertEqual(data.hostname, "xp")
        self.assertEqual(data.xplane_version, 121400)
        self.assertEqual(data.role, 1)


class TestBeaconFactory(unittest.TestCase):
    def test_package_factory_forwards_retry_options(self):
        with patch("xpwebapi.beacon.list_my_ips", return_value=[]):
            monitor = xpwebapi.beacon(retry_attempts=2, retry_backoff=0.25)

        self.assertEqual(monitor.retry_config.attempts, 2)
        self.assertEqual(monitor.retry_config.backoff, 0.25)


class TestXPBeaconMonitorGetBeacon(BeaconMonitorTestCase):
    def test_get_beacon_decodes_valid_packet(self):
        monitor = self.make_monitor()
        packet = make_beacon_packet()
        socket_patch, beacon_socket = self.mock_sockets((packet, ("127.0.0.1", 49000)))

        with socket_patch:
            with patch("xpwebapi.beacon.platform.system", return_value="Windows"):
                data = monitor.get_beacon(timeout=1.0)

        self.assertEqual(data, BeaconData(host="127.0.0.1", port=49000, hostname="testhost", xplane_version=121400, role=1))
        beacon_socket.settimeout.assert_called_once_with(1.0)
        beacon_socket.close.assert_called_once()

    def test_get_beacon_returns_none_for_unknown_packet_header(self):
        monitor = self.make_monitor()
        packet = b"XXXX\x00" + b"\x00" * 32
        socket_patch, _beacon_socket = self.mock_sockets((packet, ("127.0.0.1", 49000)))

        with socket_patch:
            with patch("xpwebapi.beacon.platform.system", return_value="Windows"):
                with patch("xpwebapi.beacon.logger.warning"):
                    self.assertIsNone(monitor.get_beacon(timeout=1.0))

    def test_get_beacon_raises_typed_no_beacon_on_timeout(self):
        monitor = self.make_monitor()
        socket_patch, _beacon_socket = self.mock_sockets(socket.timeout("timed out"))

        with socket_patch:
            with patch("xpwebapi.beacon.platform.system", return_value="Windows"):
                with self.assertRaises(XPlaneNoBeacon) as caught:
                    monitor.get_beacon(timeout=1.5)

        self.assertEqual(caught.exception.context, {"timeout": 1.5})

    def test_get_beacon_retries_timeout_then_returns_valid_packet(self):
        with patch("xpwebapi.beacon.list_my_ips", return_value=[]):
            monitor = XPBeaconMonitor(retry_attempts=2, retry_backoff=0.25)
        packet = make_beacon_packet()
        monitor_socket_1 = MagicMock()
        beacon_socket_1 = MagicMock()
        beacon_socket_1.recvfrom.side_effect = socket.timeout("timed out")
        monitor_socket_2 = MagicMock()
        beacon_socket_2 = MagicMock()
        beacon_socket_2.recvfrom.return_value = (packet, ("127.0.0.1", 49000))

        with patch("xpwebapi.beacon.socket.socket", side_effect=[monitor_socket_1, beacon_socket_1, monitor_socket_2, beacon_socket_2]):
            with patch("xpwebapi.beacon.platform.system", return_value="Windows"):
                with patch("xpwebapi.beacon.sleep_before_retry") as sleep:
                    data = monitor.get_beacon(timeout=1.0)

        self.assertEqual(data, BeaconData(host="127.0.0.1", port=49000, hostname="testhost", xplane_version=121400, role=1))
        self.assertEqual(beacon_socket_1.recvfrom.call_count, 1)
        self.assertEqual(beacon_socket_2.recvfrom.call_count, 1)
        sleep.assert_called_once_with(monitor.retry_config, 0)

    def test_get_beacon_raises_version_error_for_unsupported_packet(self):
        monitor = self.make_monitor()
        packet = make_beacon_packet(major=2)
        socket_patch, _beacon_socket = self.mock_sockets((packet, ("127.0.0.1", 49000)))

        with socket_patch:
            with patch("xpwebapi.beacon.platform.system", return_value="Windows"):
                with patch("xpwebapi.beacon.logger.warning"):
                    with self.assertRaises(XPlaneVersionNotSupported):
                        monitor.get_beacon(timeout=1.0)

    def test_get_beacon_skips_reuseport_when_constant_missing(self):
        monitor = self.make_monitor()
        socket_patch, beacon_socket = self.mock_sockets(socket.timeout("timed out"))
        had_reuseport = hasattr(beacon_module.socket, "SO_REUSEPORT")
        reuseport = getattr(beacon_module.socket, "SO_REUSEPORT", None)
        if had_reuseport:
            delattr(beacon_module.socket, "SO_REUSEPORT")
            self.addCleanup(setattr, beacon_module.socket, "SO_REUSEPORT", reuseport)

        with socket_patch:
            with patch("xpwebapi.beacon.platform.system", return_value="Linux"):
                with self.assertRaises(XPlaneNoBeacon):
                    monitor.get_beacon(timeout=1.0)

        for call in beacon_socket.setsockopt.call_args_list:
            self.assertNotEqual(call.args[0], beacon_module.socket.SOL_SOCKET)


class TestXPBeaconMonitorSameHost(BeaconMonitorTestCase):
    def test_same_host_returns_true_when_beacon_host_is_local(self):
        monitor = self.make_monitor()
        monitor.data = BeaconData(host="127.0.0.1", port=49000, hostname="xp", xplane_version=121400, role=1)
        monitor.my_ips = ["127.0.0.1"]
        self.assertTrue(monitor.same_host())

    def test_same_host_returns_false_when_no_data(self):
        monitor = self.make_monitor()
        monitor.data = None
        with patch("xpwebapi.beacon.logger.warning"):
            self.assertFalse(monitor.same_host())

    def test_same_host_returns_false_for_remote_host(self):
        monitor = self.make_monitor()
        monitor.data = BeaconData(host="192.168.1.50", port=49000, hostname="xp", xplane_version=121400, role=1)
        monitor.my_ips = ["127.0.0.1"]
        self.assertFalse(monitor.same_host())


class TestXPBeaconMonitorStatus(BeaconMonitorTestCase):
    def test_receiving_beacon_returns_true_when_data_exists(self):
        monitor = self.make_monitor()
        monitor.data = BeaconData(host="127.0.0.1", port=49000, hostname="xp", xplane_version=121400, role=1)

        self.assertTrue(monitor.receiving_beacon)

    def test_receiving_beacon_increments_warning_counter_when_no_data(self):
        monitor = self.make_monitor()

        with patch("xpwebapi.beacon.logger.warning"):
            self.assertFalse(monitor.receiving_beacon)

        self.assertEqual(monitor._already_warned, 1)

    def test_stop_monitor_marks_status_not_running_when_already_stopped(self):
        monitor = self.make_monitor()

        with patch("xpwebapi.beacon.logger.warning"):
            monitor.stop_monitor()

        self.assertEqual(monitor.status, BEACON_MONITOR_STATUS.NOT_RUNNING)


class TestXPBeaconMonitorCallbacks(BeaconMonitorTestCase):
    def test_callback_executes_registered_callbacks(self):
        monitor = self.make_monitor()
        callback = MagicMock()
        data = BeaconData(host="127.0.0.1", port=49000, hostname="xp", xplane_version=121400, role=1)
        monitor.set_callback(callback)

        monitor.callback(connected=True, beacon_data=data, same_host=True)

        callback.assert_called_once_with(connected=True, beacon_data=data, same_host=True)

    def test_callback_handles_callback_exception(self):
        monitor = self.make_monitor()
        callback = MagicMock(side_effect=RuntimeError("boom"))
        monitor.set_callback(callback)

        with patch("xpwebapi.beacon.logger.warning"):
            monitor.callback(connected=False, beacon_data=None, same_host=False)

        callback.assert_called_once()

    def test_multiple_callbacks_are_executed(self):
        monitor = self.make_monitor()
        first = MagicMock()
        second = MagicMock()
        monitor.set_callback(first)
        monitor.set_callback(second)

        monitor.callback(connected=False, beacon_data=None, same_host=False)

        first.assert_called_once()
        second.assert_called_once()

    def test_set_callback_ignores_none(self):
        monitor = self.make_monitor()

        monitor.set_callback(None)
        monitor.callback(connected=False, beacon_data=None, same_host=None)

        self.assertEqual(monitor._callback, set())


if __name__ == "__main__":
    unittest.main()
