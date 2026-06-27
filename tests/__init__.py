import logging


def _silence_test_logger(name: str) -> None:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False


for _logger_name in ("xpwebapi", "webapi"):
    _silence_test_logger(_logger_name)
