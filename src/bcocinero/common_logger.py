import logging
import threading
from pathlib import Path

class TextualLogHandler(logging.Handler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def emit(self, record):
        msg = record.getMessage()
        level = record.levelname
        if level == "WARNING": level = "WARN"

        if threading.current_thread() is threading.main_thread():
            self.app.post_log(msg, level)
        else:
            self.app.call_from_thread(self.app.post_log, msg, level)

def setup_app_logger(app, module_name: str = "bcocinero"):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    log_dir = Path.home() / ".local" / "bcocinero"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{module_name}.log"

    file_handler = logging.FileHandler(
        str(log_file), mode="a", encoding="utf-8", delay=False
    )
    file_handler.setFormatter(
        logging.Formatter(
            '%(asctime)s [%(levelname)s] [%(name)s] [%(module)s]:%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    )
    logger.addHandler(file_handler)

    textual_handler = TextualLogHandler(app)
    logger.addHandler(textual_handler)
    logging.info(f"Logger initialized: Logging to {log_file}")

    return logger
