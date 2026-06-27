"""Logging configuration helpers for xpwebapi."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LOGGING_FORMAT_TEXT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
PYTHON_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}
OWNED_HANDLER_ATTR = "_xpwebapi_owned_handler"
_OWNED_COMPONENT_LOGGER_LEVELS: dict[str, tuple[int, int]] = {}


def _normalize_level_name(level: str) -> str:
    if not isinstance(level, str):
        raise TypeError("logging level must be a string")
    normalized = level.upper()
    if normalized not in PYTHON_LEVELS:
        valid = ", ".join(PYTHON_LEVELS)
        raise ValueError(f"unknown logging level {level!r}; expected one of: {valid}")
    return normalized


def _validate_component_name(name: str) -> str:
    if name == "webapi" or (name.startswith("xpwebapi.") and len(name) > len("xpwebapi.")):
        return name
    raise ValueError("component logger must be 'webapi' or start with 'xpwebapi.'")


class LoggingConfig(BaseModel):
    """Validated logging configuration."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["text", "json"] = "text"
    level: str = "INFO"
    traffic_level: str = "WARNING"
    components: dict[str, str] = Field(default_factory=dict)

    @field_validator("level", "traffic_level")
    @classmethod
    def _validate_level(cls, value: str) -> str:
        return _normalize_level_name(value)

    @model_validator(mode="after")
    def _validate_components(self) -> "LoggingConfig":
        self.components = {_validate_component_name(name): _normalize_level_name(level) for name, level in self.components.items()}
        return self


class LoggingConfigFile(BaseModel):
    """Top-level JSON config file schema."""

    model_config = ConfigDict(extra="forbid")

    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def _level_number(level: str) -> int:
    return PYTHON_LEVELS[_normalize_level_name(level)]


def _load_config_file(config_file: str | Path) -> LoggingConfig:
    path = Path(config_file)
    raw_text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON logging config {path}: {exc}") from exc
    return LoggingConfigFile.model_validate(raw).logging


def _make_handler(config: LoggingConfig, stream: TextIO | None) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    formatter: logging.Formatter
    if config.format == "json":
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter(LOGGING_FORMAT_TEXT)
    handler.setFormatter(formatter)
    setattr(handler, OWNED_HANDLER_ATTR, True)
    return handler


def _replace_owned_handlers(logger: logging.Logger, handler: logging.Handler) -> None:
    logger.handlers = [existing for existing in logger.handlers if not getattr(existing, OWNED_HANDLER_ATTR, False)]
    logger.addHandler(handler)


def _apply_component_levels(components: Mapping[str, str]) -> None:
    configured_names = set(components)

    for logger_name in tuple(_OWNED_COMPONENT_LOGGER_LEVELS):
        if logger_name in configured_names:
            continue
        previous_level, owned_level = _OWNED_COMPONENT_LOGGER_LEVELS.pop(logger_name)
        logger = logging.getLogger(logger_name)
        if logger.level == owned_level:
            logger.setLevel(previous_level)

    for logger_name, logger_level in components.items():
        logger = logging.getLogger(logger_name)
        previous_level, owned_level = _OWNED_COMPONENT_LOGGER_LEVELS.get(
            logger_name,
            (logger.level, logger.level),
        )
        new_level = _level_number(logger_level)
        if logger_name in _OWNED_COMPONENT_LOGGER_LEVELS and logger.level != owned_level:
            previous_level = logger.level
        logger.setLevel(new_level)
        _OWNED_COMPONENT_LOGGER_LEVELS[logger_name] = (previous_level, new_level)


def _merge_config(
    base: LoggingConfig,
    *,
    format: Literal["text", "json"] | None,
    level: str | None,
    traffic_level: str | None,
    components: Mapping[str, str] | None,
) -> LoggingConfig:
    data = base.model_dump()
    if format is not None:
        data["format"] = format
    if level is not None:
        data["level"] = level
    if traffic_level is not None:
        data["traffic_level"] = traffic_level
    if components is not None:
        data["components"] = {**data["components"], **dict(components)}
    return LoggingConfig.model_validate(data)


def configure_logging(
    config_file: str | Path | None = None,
    *,
    format: Literal["text", "json"] | None = None,
    level: str | None = None,
    traffic_level: str | None = None,
    components: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> LoggingConfig:
    """Configure xpwebapi application and traffic logging explicitly."""

    base_config = _load_config_file(config_file) if config_file is not None else LoggingConfig()
    config = _merge_config(base_config, format=format, level=level, traffic_level=traffic_level, components=components)

    app_logger = logging.getLogger("xpwebapi")
    traffic_logger = logging.getLogger("webapi")

    app_handler = _make_handler(config, stream)
    traffic_handler = _make_handler(config, stream)

    _replace_owned_handlers(app_logger, app_handler)
    _replace_owned_handlers(traffic_logger, traffic_handler)

    app_logger.setLevel(_level_number(config.level))
    traffic_logger.setLevel(_level_number(config.traffic_level))
    app_logger.propagate = False
    traffic_logger.propagate = False

    _apply_component_levels(config.components)

    return config


def write_logging_config(path: str | Path, *, config: LoggingConfig | None = None, overwrite: bool = False) -> Path:
    """Write a starter JSON logging config file."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(output_path)

    config_file = LoggingConfigFile(logging=config or LoggingConfig())
    output_path.write_text(json.dumps(config_file.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
