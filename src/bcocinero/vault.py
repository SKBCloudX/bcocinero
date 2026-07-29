# src/bcocinero/vault.py
import subprocess
import logging
from typing import Dict

class VaultManager:
    def __init__(self, install_root_dir: str):
        self.install_root_dir = install_root_dir

    def create_vault(self, user_data: Dict[str, str]) -> bool:
        user_pass = user_data["user_pass"]
        os_admin_pass = user_data["os_admin_pass"]

        inputs = f"{user_pass}\n{os_admin_pass}\n"

        logging.debug("Invoke ./run.sh vault...")
        try:
            p = subprocess.Popen(
                ["./run.sh", "vault"],
                cwd=str(self.install_root_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8"
            )

            out, err = p.communicate(input=inputs)

            if p.returncode == 0:
                logging.info("Vaulting succeeded")
                return True
            else:
                logging.error(f"Vaulting failed with exitcode {p.returncode}")
                return False
        except Exception as e:
            logging.error(f"Failed to execute ./run.sh vault: {e}")
            return False

