import os
import subprocess
import tarfile
import logging
from pathlib import Path
from typing import Optional

class Prep:
    def __init__(self,
                 target_mnt: str = "/mnt",
                 install_path: Optional[str] = None):
        self.home_dir = Path.home()
        self.mnt_dir = Path(target_mnt)
        self.install_path = (
            Path(install_path) if install_path else self.home_dir
        )

        logging.basicConfig(level=logging.INFO,
                            format='%(levelname)s: %(message)s')

    def _run_command(self, command: str, cwd: Optional[Path] = None):
        logging.info(f"Running command: {command}")
        return subprocess.run(command, shell=True, cwd=cwd, check=True)

    def is_already_mounted(self) -> bool:
        return os.path.ismount(self.mnt_dir)

    def mount_iso(self) -> None:
        if self.is_ready_mounted():
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
        logging.info(f"Extracting {tarball.name} to {self.install_Path}...")

        with tarfile.open(tarball) as t:
            root_dir = t.getmembers()[0].name.split('/')[0]
            t.extractall(path=self.install_path)

        return self.install_path / root_dir

    def run_prep_script(self, work_dir: Path) -> None:
        script_path = work_dir / "prepare.sh"
        if not script_path.exists():
            raise FileNotFoundError(f"prepare.sh is not found in {work_dir}.")
        logging.info("Running prepare.sh offline...")
        self._run_command("./prepare.sh offline", cwd=work_dir)

    def run_prep(self) -> None:
        try:
            self.mount_iso()
            extracted_dir = self.extract_package()
            self.run_prep_script(extracted_dir)
            logging.info("Prep process is completed successfully.")
        except Exception as e:
            logging.error(f"Prep process is failed: {e}")
            raise


