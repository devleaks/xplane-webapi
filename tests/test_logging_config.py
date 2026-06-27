import json
import logging
import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

import xpwebapi.logging_config as logging_config_module
from xpwebapi.logging_config import JsonLogFormatter, LoggingConfig, configure_logging, write_logging_config


class TestJsonLogFormatter(unittest.TestCase):
    def test_json_formatter_emits_stable_core_fields(self):
        record = logging.LogRecord(
            name="xpwebapi.rest",
            level=logging.INFO,
            pathname="rest.py",
            lineno=188,
            msg="rest api reachable",
            args=(),
            exc_info=None,
            func="rest_api_reachable",
        )

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "xpwebapi.rest")
        self.assertEqual(payload["message"], "rest api reachable")
        self.assertEqual(payload["module"], "rest")
        self.assertEqual(payload["function"], "rest_api_reachable")
        self.assertEqual(payload["line"], 188)
        self.assertRegex(payload["timestamp"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
        self.assertNotIn("exception", payload)

    def test_json_formatter_includes_exception_text(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
            record = logging.getLogger("xpwebapi.rest").makeRecord(
                name="xpwebapi.rest",
                level=logging.ERROR,
                fn="rest.py",
                lno=200,
                msg="request failed",
                args=(),
                exc_info=exc_info,
                func="dataref_value",
                extra=None,
            )

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["level"], "ERROR")
        self.assertIn("RuntimeError: boom", payload["exception"])


class TestLoggingConfig(unittest.TestCase):
    def test_logging_config_accepts_standard_python_levels(self):
        config = LoggingConfig(
            format="json",
            level="debug",
            traffic_level="WARNING",
            components={"xpwebapi.rest": "INFO", "webapi": "ERROR"},
        )

        self.assertEqual(config.format, "json")
        self.assertEqual(config.level, "DEBUG")
        self.assertEqual(config.traffic_level, "WARNING")
        self.assertEqual(config.components["xpwebapi.rest"], "INFO")
        self.assertEqual(config.components["webapi"], "ERROR")

    def test_logging_config_rejects_unknown_level_names(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(level="NOTICE")

    def test_logging_config_rejects_unrelated_component_names(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(components={"urllib3": "DEBUG"})

    def test_logging_config_rejects_trailing_dot_only_component(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(components={"xpwebapi.": "DEBUG"})


class IsolatedLoggerState:
    def __init__(self, *names: str) -> None:
        self.names = names
        self.state = {}
        self.owned_component_levels = {}

    def __enter__(self) -> "IsolatedLoggerState":
        self.owned_component_levels = logging_config_module._OWNED_COMPONENT_LOGGER_LEVELS.copy()
        logging_config_module._OWNED_COMPONENT_LOGGER_LEVELS.clear()
        for name in self.names:
            logger = logging.getLogger(name)
            self.state[name] = (logger.handlers[:], logger.level, logger.propagate)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)
            logger.propagate = True
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        logging_config_module._OWNED_COMPONENT_LOGGER_LEVELS.clear()
        logging_config_module._OWNED_COMPONENT_LOGGER_LEVELS.update(self.owned_component_levels)
        for name, (handlers, level, propagate) in self.state.items():
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.handlers.extend(handlers)
            logger.setLevel(level)
            logger.propagate = propagate


class TestLoggingConfigFileIO(unittest.TestCase):
    def test_write_logging_config_writes_valid_starter_config(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xpwebapi-logging.json"

            written = write_logging_config(path)

            self.assertEqual(written, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            config = LoggingConfig.model_validate(raw["logging"])
            self.assertEqual(config.format, "text")
            self.assertEqual(config.level, "INFO")
            self.assertEqual(config.traffic_level, "WARNING")

    def test_write_logging_config_does_not_overwrite_by_default(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xpwebapi-logging.json"
            path.write_text("{}", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                write_logging_config(path)

    def test_configure_logging_raises_value_error_for_invalid_json(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xpwebapi-logging.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "xpwebapi-logging.json"):
                configure_logging(config_file=path)

    def test_configure_logging_raises_file_not_found_for_explicit_missing_file(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.json"

            with self.assertRaises(FileNotFoundError):
                configure_logging(config_file=path)


class TestConfigureLogging(unittest.TestCase):
    def test_configure_logging_separates_application_and_traffic_loggers(self):
        app_stream = StringIO()

        with IsolatedLoggerState("xpwebapi", "webapi"):
            config = configure_logging(format="json", level="DEBUG", traffic_level="ERROR", stream=app_stream)

            app_logger = logging.getLogger("xpwebapi")
            traffic_logger = logging.getLogger("webapi")

            self.assertEqual(config.format, "json")
            self.assertEqual(app_logger.level, logging.DEBUG)
            self.assertEqual(traffic_logger.level, logging.ERROR)
            self.assertEqual(len(app_logger.handlers), 1)
            self.assertEqual(len(traffic_logger.handlers), 1)
            self.assertIsInstance(app_logger.handlers[0].formatter, JsonLogFormatter)
            self.assertIsInstance(traffic_logger.handlers[0].formatter, JsonLogFormatter)
            self.assertIsNot(app_logger.handlers[0], traffic_logger.handlers[0])
            self.assertFalse(traffic_logger.propagate)

    def test_configure_logging_applies_component_levels(self):
        with IsolatedLoggerState("xpwebapi", "webapi", "xpwebapi.rest", "xpwebapi.ws"):
            configure_logging(level="WARNING", components={"xpwebapi.rest": "DEBUG", "xpwebapi.ws": "ERROR"})

            self.assertEqual(logging.getLogger("xpwebapi").level, logging.WARNING)
            self.assertEqual(logging.getLogger("xpwebapi.rest").level, logging.DEBUG)
            self.assertEqual(logging.getLogger("xpwebapi.ws").level, logging.ERROR)

    def test_repeated_configure_logging_restores_removed_component_overrides(self):
        with IsolatedLoggerState("xpwebapi", "webapi", "xpwebapi.rest", "xpwebapi.ws"):
            rest_logger = logging.getLogger("xpwebapi.rest")
            ws_logger = logging.getLogger("xpwebapi.ws")
            rest_logger.setLevel(logging.ERROR)
            ws_logger.setLevel(logging.CRITICAL)

            configure_logging(components={"xpwebapi.rest": "DEBUG"})
            configure_logging(components={"xpwebapi.ws": "WARNING"})

            self.assertEqual(rest_logger.level, logging.ERROR)
            self.assertEqual(ws_logger.level, logging.WARNING)

    def test_manual_component_level_change_after_configure_is_preserved_when_override_is_removed(self):
        with IsolatedLoggerState("xpwebapi", "webapi", "xpwebapi.rest"):
            rest_logger = logging.getLogger("xpwebapi.rest")

            configure_logging(components={"xpwebapi.rest": "DEBUG"})
            rest_logger.setLevel(logging.ERROR)
            configure_logging()

            self.assertEqual(rest_logger.level, logging.ERROR)

    def test_explicit_component_reconfigure_reclaims_control_after_manual_change(self):
        with IsolatedLoggerState("xpwebapi", "webapi", "xpwebapi.rest"):
            rest_logger = logging.getLogger("xpwebapi.rest")

            configure_logging(components={"xpwebapi.rest": "DEBUG"})
            rest_logger.setLevel(logging.ERROR)
            configure_logging(components={"xpwebapi.rest": "INFO"})

            self.assertEqual(rest_logger.level, logging.INFO)

    def test_configure_logging_validates_before_mutating_handlers(self):
        foreign_handler = logging.NullHandler()

        with IsolatedLoggerState("xpwebapi", "webapi"):
            app_logger = logging.getLogger("xpwebapi")
            app_logger.addHandler(foreign_handler)

            with self.assertRaises(ValidationError):
                configure_logging(level="NOTICE")

            self.assertEqual(app_logger.handlers, [foreign_handler])

    def test_repeated_configure_logging_replaces_only_owned_handlers(self):
        foreign_handler = logging.NullHandler()

        with IsolatedLoggerState("xpwebapi", "webapi"):
            app_logger = logging.getLogger("xpwebapi")
            app_logger.addHandler(foreign_handler)

            configure_logging(level="INFO")
            configure_logging(level="DEBUG")

            self.assertIn(foreign_handler, app_logger.handlers)
            owned_handlers = [handler for handler in app_logger.handlers if getattr(handler, "_xpwebapi_owned_handler", False)]
            self.assertEqual(len(owned_handlers), 1)
            self.assertEqual(app_logger.level, logging.DEBUG)

    def test_importing_package_does_not_configure_logging_handlers(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json, logging; "
                    "before = {name: len(logging.getLogger(name).handlers) for name in ('xpwebapi', 'webapi')}; "
                    "import xpwebapi; "
                    "after = {name: len(logging.getLogger(name).handlers) for name in ('xpwebapi', 'webapi')}; "
                    "print(json.dumps({'before': before, 'after': after}))"
                ),
            ],
            capture_output=True,
            check=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["after"], payload["before"])


class TestPackageRootExports(unittest.TestCase):
    def test_logging_helpers_are_exported_from_package_root(self):
        import xpwebapi

        self.assertIs(xpwebapi.configure_logging, configure_logging)
        self.assertIs(xpwebapi.write_logging_config, write_logging_config)
        self.assertIs(xpwebapi.LoggingConfig, LoggingConfig)
        self.assertIs(xpwebapi.JsonLogFormatter, JsonLogFormatter)
        self.assertIn("configure_logging", xpwebapi.__all__)
        self.assertIn("write_logging_config", xpwebapi.__all__)
        self.assertIn("LoggingConfig", xpwebapi.__all__)
        self.assertIn("JsonLogFormatter", xpwebapi.__all__)


if __name__ == "__main__":
    unittest.main()
