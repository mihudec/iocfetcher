import logging
import pathlib
import tempfile
import unittest

from pydantic import ValidationError

from iocfetcher.config import LogLevel, ServerConfig
from iocfetcher.logger import get_logger, update_logger_level


class LoggingConfigTests(unittest.TestCase):
    def test_named_log_level_is_case_insensitive(self) -> None:
        config = ServerConfig.model_validate({"log_verbosity": "WARNING"})
        self.assertIs(config.log_verbosity, LogLevel.WARNING)

    def test_invalid_log_level_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServerConfig.model_validate({"log_verbosity": "verbose"})

    def test_configured_level_is_applied_to_logger_and_handlers(self) -> None:
        logger = logging.Logger("logging-config-test")
        handler = logging.StreamHandler()
        logger.addHandler(handler)

        update_logger_level(logger, LogLevel.DEBUG)

        self.assertEqual(logger.level, logging.DEBUG)
        self.assertEqual(handler.level, logging.DEBUG)

    def test_application_handlers_are_added_even_when_root_has_a_handler(self) -> None:
        root_handler = logging.StreamHandler()
        logging.getLogger().addHandler(root_handler)
        try:
            with tempfile.TemporaryDirectory() as directory:
                logger = get_logger(
                    "logging-config-parent-handler-test",
                    log_file=pathlib.Path(directory) / "app.log",
                )
                self.assertEqual(len(logger.handlers), 2)
                self.assertFalse(logger.propagate)
                for handler in logger.handlers:
                    handler.close()
                logger.handlers.clear()
        finally:
            logging.getLogger().removeHandler(root_handler)


if __name__ == "__main__":
    unittest.main()
