import sys
import pathlib
import logging
from datetime import datetime, timezone
import json

class JSONFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.isoformat()

    def format(self, record):
        log_record = {
            'time': self.formatTime(record),
            'name': record.name,
            'filename': record.filename,
            'module': record.module,
            'funcName': record.funcName,
            'lineno': record.lineno,
            'level': record.levelname,
            'message': record.getMessage(),
        }
        return json.dumps(log_record)

def get_logger(name: str, log_file: pathlib.Path = pathlib.Path("/tmp/iocfetcher.log"), level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        # Set the log level to the specified level.
        logger.setLevel(level)

        # Create a console handler for STDERR.
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)

        # Create a file handler.
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)

        # Create a JSON formatter.
        json_formatter = JSONFormatter()

        # Set the JSON formatter for both handlers.
        console_handler.setFormatter(json_formatter)
        file_handler.setFormatter(json_formatter)

        # Add the handlers to the logger.
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger

def update_logger_level(logger: logging.Logger, level: int):
    logger.setLevel(level)
    if logger.hasHandlers():
        for handler in logger.handlers:
            handler.setLevel(level)