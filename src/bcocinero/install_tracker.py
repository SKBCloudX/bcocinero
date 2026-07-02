# src/bcocinero/install_tracker.py
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from textual.widgets.option_list import Option

from bcocinero.nm_helpers import ArtifactManager

am = ArtifactManager()

class InstallTracker:
    def __init__(self):
        self.install_root_dir = am.get_install_root()
        if self.install_root_dir:
            self.recipe_path = Path(self.install_root_dir) / ".recipe.yml"
        else:
            self.recipe_path = am.base_dir / ".recipe.yml"

    def _load_recipe_data(self) -> Optional[Dict]:
        if not self.recipe_path.exists():
            return None
        try:
            with open(self.recipe_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            return None

    def get_prep_status(self) -> str:
        data = self._load_recipe_data()
        if data is None:
            return "[yellow]Prep: It has not been prepared.[/]"

        install_section = data.get("install", {})

        prep_data = install_section.get("preparations", [])
        prep_items = [item["name"] for item in prep_data if "name" in item]
        prep_status_map = ({
            item["name"]: item.get("state", "") for item in prep_data
            if "name" in item
        })
        prep_lines = self._generate_section_markup(
            "Prep", prep_items, prep_status_map
        )

        return prep_lines

    def get_playbooks_status(self) -> List[Tuple[str, str]]:
        data = self._load_recipe_data()
        if data is None:
            return []

        install_section = data.get("install", {})
        result = []
        for item in install_section.get("playbooks", []):
            if "name" in item:
                result.append((item["name"], item.get("state", "")))

        return result

    def _generate_section_markup(self,
            label: str, items: List[str], status_map: Dict[str, str]) -> str:
        if not items:
            return f"[bold]{label}:[/] No tasks configured."

        title_str = f"[bold]{label}:[/] "

        for name in items:
            state = status_map.get(name, "")
            name_len = len(name)

            if state == "pass":
                title_str += f"[bold green]{name}[/]  "
            elif state == "fail":
                title_str += f"[bold red]{name}[/]  "
            else:
                title_str += f"{name}  "

        return f"{title_str}"
