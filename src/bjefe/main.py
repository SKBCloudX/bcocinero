import getpass
import logging
import os
import requests
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from bcocinero.db import BcocineroDB
from bcocinero.nm_helpers import NetworkManager
from bcocinero.systemd_service import ensure_systemd_service
from bcocinero.hosts import update_etc_hosts

from . import PROJECT_NAME

TARGET_PROFILE = "management"
RQLITED_PATH = "/usr/bin/rqlited"
DATA_DIR = "/var/lib/rqlite"
CHECK_INTERVAL = 10

nm = NetworkManager()

class BjefeDaemon:
    def __init__(self):
        self.data_dir = DATA_DIR
        self.target_profile = TARGET_PROFILE
        self.process = None
        self.current_ip = None
        self.user = getpass.getuser()
        self.bin_path = f"/home/{self.user}/.local/bin/{PROJECT_NAME}"
        self.is_db_initialized = False
        self.check_data_dir()

    def setup_systemd_service(self) -> None:
        l_pkg_dirs = [
            "/usr/lib64/python3.9/site-packages", 
            "/usr/lib/python3.9/site-packages"
        ]
        d_env = {"PYTHONPATH": ":".join(l_pkg_dirs)}
        ensure_systemd_service(
            service_name=PROJECT_NAME,
            description=f"{PROJECT_NAME} service - rqlited controller",
            exec_start=self.bin_path,
            user=self.user,
            env_vars=d_env
        )

    def check_data_dir(self) -> None:
        # create data dir if not exist.
        if not os.path.exists(self.data_dir):
            logging.info(f"{self.data_dir} does not exist. Creating it...")
            try:
                subprocess.run(
                    ["sudo", "mkdir", "-p", self.data_dir],
                    check=True
                )
                logging.debug(f"Created {self.data_dir}")
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
            logging.debug(f"Change ownership of {self.data_dir} to {self.user}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to change ownership: {e}")

    def start_rqlited(self, ip: str) -> None:
        logging.info(f"Detected IP {ip}. Launching rqlited...")
        cmd = [
            RQLITED_PATH,
            "-http-addr", f"{ip}:4001",
            "-raft-addr", f"{ip}:4002",
            "-fk",
            DATA_DIR
        ]
        try:
            self.process = subprocess.Popen(cmd)
            self.current_ip = ip
        except Exception as e:
            logging.error(f"Failed to start rqlited: {e}")

    def wait_rqlited(self,
                     ip: str = "127.0.0.1",
                     port: int = 4001,
                     timeout: int = 5):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                res = requests.get(f"http://{ip}:{port}/status", timeout=2)
                if res.status_code == 200:
                    status_data = res.json()
                    store_data = status_data.get("store", {})
                    if store_data.get("ready") is True:
                        logging.info("rqlited is open and ready.")
                        return True
            except Exception:
                pass
            time.sleep(1)

        return False

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
        logging.info(f"Starting {PROJECT_NAME} (rqlited controller)...")
        logging.info(f"Monitoring profile: {self.target_profile}")
        while True:
            hostinfo = nm.get_host_info()
            new_ip = hostinfo.get("mgmt_ip")

            if new_ip and new_ip != self.current_ip:
                if self.current_ip:
                    self.stop_rqlited()
                self.start_rqlited(new_ip)
                if self.wait_rqlited(new_ip):
                    db = BcocineroDB(urls=[f"{new_ip}:4001"])
                    if not self.is_db_initialized:
                        try:
                            self.is_db_initialized = db.initialize_schema()
                            logging.info("DB schema is initialized.")
                        except Exception as e:
                            logging.error(f"Fail to initialize DB: {e}")
                    try:
                        # update hosts table
                        db.upsert_host(**hostinfo)
                        logging.error(f"Succeed to update hosts DB.")
                    except Exception as e:
                        logging.error(f"Fail to update hosts DB: {e}")
                else:
                    s_msg = f"rqlited port on {new_ip} not open in time."
                    logging.error(s_msg)
            elif not new_ip and self.current_ip:
                logging.warning("Management IP lost. Shutting down rqlited.")
                self.stop_rqlited()

            if self.current_ip:
                try:
                    db = BcocineroDB(urls=[f"{self.current_ip}:4001"])
                    db.upsert_host(**hostinfo)
                    all_hosts = db.get_all_hosts()
                    update_etc_hosts(all_hosts)
                except Exception as e:
                    logging.error(f"Fail to sync hosts info: {e}")

            time.sleep(CHECK_INTERVAL)

def main():
    daemon = BjefeDaemon()

    def handle_exit(signum, frame):
        daemon.stop_rqlited()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    daemon.run()

if __name__ == "__main__":
    main()
