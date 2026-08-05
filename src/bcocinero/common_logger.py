import logging
import threading
from pathlib import Path

class TextualLogHandler(logging.Handler):
    def __init__(self, app_instance):
        super().__init__()
        self.app = app_instance

    def emit(self, record):
        msg = self.format(record)
        level = record.levelname
        if level == "WARNING": level = "WARN"

        if threading.current_thread() is threading.main_thread():
            self.app.post_log(msg, level)
        else:
            self.app.call_from_thread(self.app.post_log, msg, level)

class BcocineroLogger:
    def __init__(self, app, module_name="bcocinero"):
        self.app = app
        self.module_name = module_name
        self.log_dir = Path.home() / ".local" / "bcocinero"
        self.log_file = self.log_dir / f"{module_name}.log"
        self.debug_log_file = self.log_dir / f"{module_name}_debug.log"

        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger()
        self.logger.setLevel(logging.DEBUG)

        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        self._setup_handlers()

    def _setup_handlers(self):
        file_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler = logging.FileHandler(
            str(self.log_file), mode="a", encoding="utf-8"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)

        debug_file_handler = logging.FileHandler(
            str(self.debug_log_file), mode="a", encoding="utf-8"
        )
        debug_file_handler.setFormatter(file_formatter)
        debug_file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(debug_file_handler)

        # show project information (title, sub_title, and version)
        self.logger.info("=" * 50)
        self.logger.info(
            f"{self.app.title} {self.app.sub_title} ({self.app.version})"
        )
        self.logger.info("=" * 50)

        textual_formatter = logging.Formatter('%(message)s')
        textual_handler = TextualLogHandler(self.app)
        textual_handler.setFormatter(textual_formatter)
        textual_handler.setLevel(logging.INFO)
        self.logger.addHandler(textual_handler)

    def load_prev_logs(self, count: int = 3):
        if not self.log_file.exists():
            return

        try:
            log_widget = self.app.screen.get_child_by_id("main_log")
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
                last_lines = lines[-count:]
                if last_lines:
                    for line in last_lines:
                        log_widget.write(f"[dim]{line}[/]")
        except Exception as e:
            return

