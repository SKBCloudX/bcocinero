import getpass
import libnmstate
import os
import subprocess
import time
import signal
import sys
import logging
from typing import Optional, List, Dict, Any

from bcocinero.nm_helpers import (
    ArtifactManager,
    NetworkManager,
)


TARGET_PROFILE = "management"
RQLITED_PATH = "/usr/bin/rqlited"
DATA_DIR = "/var/lib/rqlite"
CHECK_INTERVAL = 10

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

nm = NetworkManager()

class RqliteManager:
    def __init__(self) -> None:
        self.data_dir = DATA_DIR
        self.target_profile = TARGET_PROFILE
        self.process = None
        self.current_ip = None
        self.user = getpass.getuser()
        self.check_data_dir()

    def check_data_dir(self) -> None:
        # create data dir if not exist.
        if not os.path.exists(self.data_dir):
            logging.info(f"{self.data_dir} does not exist. Creating it...")
            try:
                subprocess.run(
                    ["sudo", "mkdir", "-p", self.data_dir],
                    check=True
                )
                logging.info(f"Created {self.data_dir}")
            except subprocess.CalledProcessError as e:
                logging.error(f"Failed to create directory: {e}")
                return
        # change ownership to the user who runs this script.
        try:
            subprocess.run(
                ["sudo", "chown", "-R", f"{self.user}:{self.user}",
                    self.data_dir],
                check=True
            )
            logging.info(f"Change ownership of {self.data_dir} to {self.user}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to change ownership: {e}")
                
    def get_mgmt_ip(self) -> Optional[str]:
        try:
            net_state = nm.show_state()
            interfaces = net_state.get("interfaces", [])
            for iface in interfaces:
                if iface.get("profile-name", "") == TARGET_PROFILE:
                    addresses = iface.get("ipv4", {}).get("address", [])
                    if addresses:
                        return addresses[0].get("ip")
            return None
        except Exception as e:
            logging.error(f"Network lookup failed: {e}")
            return None

    def start_rqlited(self, ip: str) -> None:
        logging.info(f"Detected IP {ip}. Launching rqlited...")
        cmd = [
            RQLITED_PATH,
            "-http-addr", f"{ip}:4001",
            "-raft-addr", f"{ip}:4002",
            DATA_DIR
        ]
        try:
            self.process = subprocess.Popen(cmd)
            self.current_ip = ip
        except Exception as e:
            logging.error(f"Failed to start rqlited: {e}")

    def stop_rqlited(self) -> None:
        if self.process:
            logging.info("Stopping rqlited daemon...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            self.current_ip = None

    def run(self) -> None:
        logging.info("Starting rqlite controller.")
        logging.info(f"Monitoring profile: {TARGET_PROFILE}")
        while True:
            new_ip = self.get_mgmt_ip()

            if new_ip and new_ip != self.current_ip:
                if self.current_ip:
                    self.stop_rqlited()
                self.start_rqlited(new_ip)
            elif not new_ip and self.current_ip:
                logging.warning("Management IP lost. Shutting down rqlited.")
                self.stop_rqlited()

            time.sleep(CHECK_INTERVAL)

def main():
    manager = RqliteManager()

    def handle_exit(signum, frame):
        manager.stop_rqlited()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    manager.run()

if __name__ == "__main__":
    main()
