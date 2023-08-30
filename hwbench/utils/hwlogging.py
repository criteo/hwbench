import json
import logging

from time import gmtime, strftime


def init_logging(tuning_logfile: str) -> None:
    logger = logging.getLogger("tuning")

    logger.setLevel(logging.DEBUG)
    out = logging.FileHandler(
        filename=tuning_logfile,
        encoding="utf-8",
    )
    out.setLevel(logging.DEBUG)

    fmt = CustomJsonFormatter(datefmt="%Y/%m/%dT%H:%M:%SZ")
    out.setFormatter(fmt)

    logger.addHandler(out)


def tunninglog() -> logging.Logger:
    return logging.getLogger("tuning")


class CustomJsonFormatter(logging.Formatter):
    dropped_keys = {
        "name",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "msecs",
        "threadName",
        "processName",
        "msg",
        "args",
    }

    def format(self, record: logging.LogRecord) -> str:
        super().format(record)
        output = {
            k: v for k, v in record.__dict__.items() if k not in self.dropped_keys
        }
        output["timestamp"] = strftime(self.datefmt, gmtime(record.created))
        return json.dumps(output)
