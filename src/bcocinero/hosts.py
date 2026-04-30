import logging
import re
import subprocess
from typing import List, Dict, Any

START_TAG = "## BCOCINERO HOSTS BEGIN ##"
END_TAG = "## BCOCINERO HOSTS END ##"

def update_etc_hosts(hosts_data: List[Dict[str, Any]]) -> None:
    if not hosts_data:
        logging.warning("No host records to update /etc/hosts.")
        return

    new_lines = [START_TAG]
    for host in hosts_data:
        ip = host.get("mgmt_ip")
        hostname = host.get("hostname")
        role = host.get("role")
        if ip and hostname:
            new_lines.append(f"{ip} {hostname} # {role}")
    new_lines.append(END_TAG)
    new_hosts_block = "\n".join(new_lines)

    with open("/etc/hosts", "r") as f:
        old_etchosts = f.read()

    pattern = re.compile(f"{START_TAG}.*?{END_TAG}", re.DOTALL)
    if pattern.search(old_etchosts):
        update_etchosts = pattern.sub(new_hosts_block, old_etchosts)
    else:
        update_etchosts = (
            old_etchosts.strip() + "\n\n" + new_hosts_block + "\n"
        )

    try:
        p = subprocess.Popen(
            ["sudo", "tee", "/etc/hosts"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True
        )
        p.communicate(input=update_etchosts)
        if p.returncode == 0:
            logging.info("Succeed to update /etc/hosts.")
        else:
            logging.error(
                "Fail to update /etc/hosts. " +
                f"Return code: {p.returncode}"
            )
    except Exception as e:
        logging.error(f"Subprocess error: {e}")
