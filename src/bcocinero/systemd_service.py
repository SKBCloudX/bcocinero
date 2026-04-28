import getpass
import logging
import os
import subprocess

SERVICE_DIR = "/etc/systemd/system"

def ensure_systemd_service(
        service_name: str,
        description: str,
        exec_start: str,
        user: str,
        env_vars: dict = None
    ) -> None:
    service_path = os.path.join(SERVICE_DIR, f"{service_name}.service")
    s_env = ""
    if env_vars:
        for k, v in env_vars.items():
            s_env += f"Environment={k}={v}\n"
    service_str = f"""[Unit]
Description={description}
After=network-online.target

[Service]
Type=simple
User={user}
Group={user}
WorkingDirectory=/home/{user}
{s_env}ExecStart={exec_start}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
""".strip()

    b_content_match = False
    b_file_exists = os.path.exists(service_path)

    if b_file_exists:
        try:
            with open(service_path, 'r') as f:
                b_content_match = (f.read().strip() == service_str)
        except Exception as e:
            logging.error(f"Fail to read service file: {e}")

    if not b_content_match:
        try:
            cmd = ["sudo", "tee", service_path]
            subprocess.run(cmd, input=service_str, text=True,
                           check=True, stdout=subprocess.DEVNULL)
            logging.info(f"Systemd service {service_path} is updated.")

            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            subprocess.run(
                ["sudo", "systemctl", "restart", service_name],
                check=True
            )
            logging.info(f"Succeed to start {service_name}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Fail to set up systemd service: {e}")

