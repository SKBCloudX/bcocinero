import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bcocinero.nm_helpers import ArtifactManager

am = ArtifactManager()

class InstallTracker:
    def __init__(self):
        self.install_root_dir = am.get_install_root()
        self.recipe_path = Path(self.install_root_dir) / ".recipe.yml"

    def _load_recipe_data(self) -> Optional[Dict]:
        if not self.recipe_path.exists():
            return None
        try:
            with open(self.recipe_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            return None

    def get_progress_markup(self) -> Tuple[str, str]:
        data = self._load_recipe_data()
        
        if data is None:
            return (
                "[yellow]No installation has been initiated yet.[/]", ""
            )

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

        cook_data = install_section.get("playbooks", [])
        cook_items = [item["name"] for item in cook_data if "name" in item]
        cook_status_map = ({
            item["name"]: item.get("state", "") for item in cook_data 
            if "name" in item
        })
        cook_lines = self._generate_section_markup(
            "Cook", cook_items, cook_status_map
        )
        return (prep_lines, cook_lines)

    def _generate_section_markup(self,
            label: str, items: List[str], status_map: Dict[str, str]) -> str:
        if not items:
            return f"[bold]{label}:[/] [white]No tasks configured.[/]"

        title_str = f"[bold]{label}:[/] "
        bar_str = " " * (len(label) + 2)

        for name in items:
            state = status_map.get(name, "")
            name_len = len(name)

            if state == "pass":
                title_str += f"[green]{name}[/]  "
                bar_str += "[green]" + "=" * name_len + "[/]" + "  "
            elif state == "running":
                title_str += f"[yellow]{name}[/]  "
                bar_str += "[yellow]" + "-" * name_len + "[/]" + "  "
            elif state == "fail":
                title_str += f"[bold red]{name}[/]  "
                bar_str += "[bold red]" + "x" * name_len + "[/]" + "  "
            else:
                title_str += f"[white]{name}[/]  "
                bar_str += " " * name_len + "  "

        return f"{title_str}\n{bar_str}"
