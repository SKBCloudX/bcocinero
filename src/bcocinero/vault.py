# src/bcocinero/vault.py
import os
import secrets
import string
import uuid
import subprocess
import logging
from typing import Dict

logger = logging.getLogger("bcocinero")

class VaultManager:
    _VAULT_PASS_FILE = ".vaultpass"
    _UD_VAULT_FILE = "group_vars/all/ud_vault.yml"
    _VAULT_FILE = "group_vars/all/vault.yml"
    _NOVA_SSH_KEY = "/tmp/nova_sshkey"

    def __init__(self, install_root_dir: str):
        self.install_root_dir = install_root_dir
        self.vault_pass_path = f"{self.install_root_dir}/{self._VAULT_PASS_FILE}"
        self.ud_vault_path = f"{self.install_root_dir}/{self._UD_VAULT_FILE}"
        self.vault_path = f"{self.install_root_dir}/{self._VAULT_FILE}"

    def gen_random_password(self,
                            mode: str = "default", length: int = 12) -> str:
        if mode == "kek":
            alphabet = string.ascii_letters + string.digits
            return ''.join(secrets.choice(alphabet) for _ in range(32))
        
        if mode == "uuid":
            return str(uuid.uuid4())

        comp = string.ascii_letters + string.digits
        comp2 = '-_.'
        
        tmp_pass = ''.join(secrets.choice(comp) for _ in range(length))
        pre = tmp_pass[0]
        post = tmp_pass[-1]
        pw_body = tmp_pass[1:-1]
        
        special_char = secrets.choice(comp2)
        body_list = list(special_char + pw_body[1:])
        secrets.SystemRandom().shuffle(body_list)
        mix = ''.join(body_list)
        
        return f"{pre}{mix}{post}"

    def _encrypt_file(self, target_filepath: str) -> None:
        subprocess.run(
            ["ansible-vault", "encrypt", "--vault-password-file", self.vault_pass_path, target_filepath],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )

    def generate_vault_files(self, user_data: Dict[str, str]) -> None:
        # Create .vaultpass
        if not os.path.exists(self.vault_pass_path):
            logger.info(f"{self._VAULT_PASS_FILE} does not exist. Creating it.")
            pw = self.gen_random_password()
            with open(self.vault_pass_path, "w", encoding="utf-8") as f:
                f.write(pw)
            os.chmod(self.vault_pass_path, 0o400)
            subprocess.run(["sudo", "chattr", "+i", self.vault_pass_path],
                            check=True)
        else:
            logger.info(f"{self._VAULT_PASS_FILE} already exists. Skipping.")

        # Create ud_vault.yml
        if not os.path.exists(self.ud_vault_path):
            logger.info(f"{self._UD_VAULT_FILE} does not exist. Creating it.")
            user_pass = user_data["user_pass"]
            os_admin_pass = user_data["os_admin_pass"]

            with open(self.ud_vault_path, "w", encoding="utf-8") as f:
                f.write(f"vault_ssh_password: '{user_pass}'\n")
                f.write(f"vault_sudo_password: '{user_pass}'\n")
                f.write(f"vault_openstack_admin_password: '{os_admin_pass}'\n")
                f.write(f"vault_pfx_admin_password: '{os_admin_pass}'\n")
                f.write(f"vault_pfx_lia_token: '{os_admin_pass}'\n")
            
            self._encrypt_file(self.ud_vault_path)
        else:
            logger.info(f"{self._UD_VAULT_FILE} already exists. Skipping.")

        # Create vault.yml
        if not os.path.exists(self.vault_path):
            logger.info(f"{self._VAULT_FILE} does not exist. Creating it.")
            
            if os.path.exists(self._NOVA_SSH_KEY): os.remove(self._NOVA_SSH_KEY)
            if os.path.exists(f"{self._NOVA_SSH_KEY}.pub"): os.remove(f"{_NOVA_SSH_KEY}.pub")

            subprocess.run(
                ["ssh-keygen", "-f", self._NOVA_SSH_KEY, "-C", "nova-ssh-public-key", "-N", ""],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            with open(self._NOVA_SSH_KEY, "r", encoding="utf-8") as f:
                priv_key = "".join(f"  {line}" for line in f)
            with open(f"{self._NOVA_SSH_KEY}.pub", "r", encoding="utf-8") as f:
                pub_key = "".join(f"  {line}" for line in f)

            lines = [
                "---",
                f"vault_mariadb_root_password: '{self.gen_random_password()}'",
                f"vault_rabbitmq_openstack_password: '{self.gen_random_password()}'",
                f"vault_ceph_secret_uuid: '{self.gen_random_password('uuid')}'",
                f"vault_keystone_password: '{self.gen_random_password()}'",
                f"vault_glance_password: '{self.gen_random_password()}'",
                f"vault_placement_password: '{self.gen_random_password()}'",
                f"vault_neutron_password: '{self.gen_random_password()}'",
                f"vault_cinder_password: '{self.gen_random_password()}'",
                f"vault_nova_password: '{self.gen_random_password()}'",
                f"vault_neutron_metadata_secret: '{self.gen_random_password()}'",
                f"vault_horizon_password: '{self.gen_random_password()}'",
                f"vault_barbican_password: '{self.gen_random_password()}'",
                f"vault_barbican_kek: '{self.gen_random_password('kek')}'",
                "vault_nova_ssh_private_key: |",
                priv_key.rstrip(),
                "vault_nova_ssh_public_key: >",
                pub_key.rstrip(),
                "..."
            ]

            with open(self.vault_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            if os.path.exists(self._NOVA_SSH_KEY): os.remove(self._NOVA_SSH_KEY)
            if os.path.exists(f"{self._NOVA_SSH_KEY}.pub"): os.remove(f"{self._NOVA_SSH_KEY}.pub")

            self._encrypt_file(self.vault_path)
        else:
            logger.info(f"{self._VAULT_FILE} already exists. Skipping.")

