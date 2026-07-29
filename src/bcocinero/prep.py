import os
import subprocess
import tarfile
import logging
from pathlib import Path
from typing import Optional, Generator, Tuple
from bcocinero.nm_helpers import NetworkManager

class Prep:
    def __init__(self,
                 target_mnt: str = "/mnt",
                 install_path: Optional[str] = None):
        self.home_dir = Path.home()
        self.mnt_dir = Path(target_mnt)
        self.install_path = (
            Path(install_path) if install_path else self.home_dir
        )
        self.install_root_dir: Optional[Path] = None
        self.nm = NetworkManager()

    def _create_mgmt_ip_file(self, work_dir: Path):
        mgmt_file = work_dir / "scripts/.mgmt_ip"
        if mgmt_file.exists():
            logging.debug(".mgmt_ip already exists.")
            return

        try:
            mgmt_ip, _ = self.nm.get_mgmt_iface_info()

            if mgmt_ip:
                with open(mgmt_file, "w") as f:
                    f.write(mgmt_ip)
                logging.debug(f"Created .mgmt_ip with {mgmt_ip}")
            else:
                logging.error("Cannot create .mgmt_ip.")
        except Exception as e:
            logging.error(f"Fail to create .mgmt_ip file: {e}")

    def _run_command(self, command: str, cwd: Optional[Path] = None):
        logging.info(f"Running command: {command}")
        log_file_path = Path.home() / ".local" / "bcocinero" / "bcocinero.log"
        try:
            p = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8"
            )
            if p.stdout:
                for line in p.stdout:
                    s_line = line.strip()
                    if s_line:
                        logging.debug(s_line)

            p.wait()

            if p.returncode != 0:
                raise subprocess.CalledProcessError(p.returncode, command)
        except Exception as e:
            logging.error(f"Command failed: {e}")
            raise

    def is_already_mounted(self) -> bool:
        return os.path.ismount(self.mnt_dir)

    def mount_iso(self) -> None:
        if self.is_already_mounted():
            logging.info(f"{self.mnt_dir} is already mounted.")
            return

        iso_files = list(self.home_dir.glob("*.iso"))
        if not iso_files:
            raise FileNotFoundError(f"No ISO file is found in {self.home_dir}")

        iso_path = iso_files[0]
        logging.info(f"Mounting {iso_path} to {self.mnt_dir}...")
        self._run_command(f"sudo mount -o loop {iso_path} {self.mnt_dir}")

    def extract_tarball(self) -> Path:
        tar_files = list(self.mnt_dir.glob("*.tar.gz"))
        if not tar_files:
            raise FileNotFoundError(f"No tarball is found in {self.mnt_dir}")

        tarball = tar_files[0]
        logging.info(f"Extracting {tarball.name} to {self.install_path}...")

        with tarfile.open(tarball) as t:
            root_dir = t.getmembers()[0].name.split('/')[0]
            t.extractall(path=self.install_path)

        self.install_root_dir = self.install_path / root_dir
        return self.install_root_dir

    def run_prep_script(self, work_dir: Path) -> None:
        script_path = work_dir / "prepare.sh"
        if not script_path.exists():
            raise FileNotFoundError(f"prepare.sh is not found in {work_dir}.")

        self._create_mgmt_ip_file(work_dir)
        logging.info("Running prepare.sh offline...")
        self._run_command("./prepare.sh offline", cwd=work_dir)

    def run_prep_gen(self) -> Generator[Tuple[float, str], None, None]:
        try:
            yield 0.1, "Checking the iso file..."
            self.mount_iso()
            yield 0.3, "Extracting the tarball..."
            extracted_dir = self.extract_tarball()
            yield 0.5, "Running prepare.sh scripts..."
            self.run_prep_script(extracted_dir)
            yield 1.0, "Prep process is completed successfully."
        except Exception as e:
            logging.error(f"Prep process is failed: {e}")
            raise


