import getpass
import logging
import signal
import socket
import sys
import time

from typing import Any, Dict, List, Optional

from bcocinero.db import BcocineroDB
from bcocinero.nm_helpers import (
    NetworkManager,
    ArtifactManager,
)
from bcocinero.systemd_service import ensure_systemd_service
from . import PROJECT_NAME

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CHECK_INTERVAL = 30

nm = NetworkManager()
am = ArtifactManager()

class BcocineroDaemon:
    def __init__(self):
        self.user = getpass.getuser()
        self.bin_path = f"/home/{self.user}/.local/bin/{PROJECT_NAME}"
        self.hc_ip = None

    def _check_for_db(self) -> bool:
        msg = f"Check for connection to Head Node DB ({self.hc_ip}:4001)..."
        logging.info(msg)

        try:
            with socket.create_connection((self.hc_ip, 4001), timeout=2):
                logging.info("Connected to Head Node DB port successfully.")
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            msg = "DB not reachable (Target: {self.hc_ip})"
            logging.warning(msg)

        return False

    def setup_systemd_service(self) -> None:
        l_pkg_dirs = [
            "/usr/lib64/python3.9/site-packages",
            "/usr/lib/python3.9/site-packages"
        ]
        d_env = {"PYTHONPATH": ":".join(l_pkg_dirs)}
        ensure_systemd_service(
            service_name=PROJECT_NAME,
            description=f"{PROJECT_NAME} service",
            exec_start=self.bin_path,
            user=self.user,
            env_vars=d_env
        )

    def collect_and_report(self) -> None:
        try:
            hostinfo = nm.get_host_info()
            # if hc_ip does not exist, return
            self.hc_ip = hostinfo.get("hc_ip", None)
            if not self.hc_ip:
                msg = "Head control node is not registered. Skipping report."
                logging.warning(msg)
                return

            if not self._check_for_db():
                return

            db = BcocineroDB(urls=[f"{self.hc_ip}:4001"])
            db.upsert_host(**hostinfo)

            interfaces = nm.list_interfaces(iface_types=["bond", "vlan"])
            for iface in interfaces:
                iface["machine_id"] = hostinfo.get("machine_id")

                if iface.get("type") == "bond":
                    db.upsert_bond(**iface)
                elif iface.get("type") == "vlan":
                    db.upsert_vlan(**iface)

            msg = (
                f"Reported {hostinfo['hostname']} info to "
                f"Head Control Node ({self.hc_ip})."
            )
            logging.info(msg)
        except Exception as e:
            logging.error(f"Fail to collect interface information: {e}")

    def run(self):
        logging.info(f"Starting {PROJECT_NAME}...")

        while True:
            self.collect_and_report()
            time.sleep(CHECK_INTERVAL)

def main():
    daemon = BcocineroDaemon()

    def handler(sig, frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    daemon.run()

if __name__ == "__main__":
    main()

