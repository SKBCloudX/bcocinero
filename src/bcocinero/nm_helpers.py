import logging
import subprocess
import yaml
import libnmstate
import configparser
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

# set libnmstate log level
logging.getLogger('libnmstate').setLevel(logging.ERROR)

class ArtifactManager:
    """load config file and set artifacts directory."""
    
    def __init__(self) -> None:
        self.base_dir: Path = Path.home() / ".local/bcocinero"
        self.jefe_file: Path = self.base_dir / "JEFE"
        self.artifact_dir = self.get_artifact_dir()

    def get_artifact_dir(self) -> Path:
        """return artifacts_dir path."""
        artifact_dir = self.base_dir / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        return artifact_dir

    def save_state(self, filename: str, state: Dict[str, Any]) -> Path:
        """save network state to yaml file."""
        target: Path = self.artifact_dir / filename
        with open(target, 'w', encoding='utf-8') as f:
            yaml.dump(state, f, default_flow_style=False, allow_unicode=True)
        return target

class ProfileType(Enum):
    SERVICE = "service"
    MANAGEMENT = "management"
    STORAGE = "storage"
    PROVIDER = "provider"
    NONE = ""

    @classmethod
    def list_values(cls, type: str = "all") -> List[str]:
        l_values = [item.value for item in cls if item != cls.NONE]
        if type == "vlan":
            l_values.remove("provider")

        return l_values

class NodeRole(Enum):
    HEAD = "HeadControl"
    CONTROL = "Control"
    COMPUTE = "Compute"
    STORAGE = "Storage"
    NONE = ""

    @property
    def is_control_type(self) -> bool:
        return self in (NodeRole.HEAD, NodeRole.CONTROL)

    @classmethod
    def has_value(cls, value: str) -> bool:
      return value in [ item.value for item in cls]

class NetworkManager:
    """Class for reading and setting of network interfaces"""

    def __init__(self) -> None:
        self.am = ArtifactManager()

    def show_state(self) -> Dict[str, Any]:
        """show the current network state."""
        return libnmstate.show()

    def apply_state(self, state: Dict[str, Any]) -> None:
        """apply the configured network state."""
        try:
            libnmstate.apply(state)
        except Exception as e:
            raise RuntimeError(f"Fail to apply the state: {e}")

    # Read operations
    def get_machine_id(self) -> Optional[str]:
        try:
            with open("/etc/machine-id", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

    def get_interface_by_profile(self, profile_name: str) -> Optional[str]:
        """get interface by profile-name"""
        try:
            state = self.show_state()
            interfaces = state.get("interfaces", [])

            for iface in interfaces:
                if iface.get("profile-name", "") == profile_name:
                    return iface
            return None
        except Exception as e:
            return None

    def get_mgmt_ip(self) -> Optional[str]:
        iface = self.get_interface_by_profile(ProfileType.MANAGEMENT.value)
        my_mgmt_ip = None

        if iface:
            ipv4_info = iface.get("ipv4", {})
            addresses = ipv4_info.get("address", [])

            if addresses:
                my_mgmt_ip = addresses[0].get("ip")

        return my_mgmt_ip

    def get_host_info(self) -> Dict[str, Any]:
        """get hostname and nameservers."""
        state = self.show_state()
        dns_resolver = state.get("dns-resolver", {}).get("running", {})
        role = ""
        hc_ip = None
        mgmt_ip = self.get_mgmt_ip()
        machine_id = self.get_machine_id()

        try:
            result = subprocess.run(
                ["sudo", "hostnamectl", "deployment"],
                capture_output=True,
                text=True,
                check=True
            )
            if NodeRole.has_value(result.stdout.strip()):
                role = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        if self.am.jefe_file.exists():
            try:
                content = self.am.jefe_file.read_text(encoding="utf-8").strip()
                if content:
                    hc_ip = content
            except OSError:
                pass

        return {
            "machine_id": machine_id,
            "hostname": state.get("hostname", {}).get("running", ""),
            "nameservers": dns_resolver.get("server", []),
            "role": role,
            "hc_ip": hc_ip,
            "mgmt_ip": mgmt_ip
        }

    def get_default_gateway(self) -> Optional[Dict[str, str]]:
        state = self.show_state()
        routes = state.get("routes", {}).get("running", [])
        for route in routes:
            if route.get("destination") == "0.0.0.0/0":
                return {
                    "gateway": route.get("next-hop-address"),
                    "interface": route.get("next-hop-interface")
                }
        return None

    def get_interface_info(self, name: str) -> Dict[str, Any]:
        """return the interface info."""
        state = self.show_state()
        return next(
            (iface for iface in state.get("interfaces", [])
                if iface.get("name") == name), {}
        )

    def list_interfaces(self,
            iface_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        state = self.show_state()
        allowed = iface_types or ["ethernet", "bond", "vlan"]
        return [
            iface for iface in state.get("interfaces", [])
            if iface.get("type") in allowed
        ]

    def get_vlan_interfaces(self) -> List[Tuple[str, str, str, str, str]]:
        l_vlan: List[Tuple[str, str, str, str, str]] = []
        for iface in self.list_interfaces(["vlan"]):
            vconfig = iface.get("vlan", {})
            ipv4_list = iface.get("ipv4", {}).get("address", [])
            ip = ipv4_list[0].get("ip", "") if ipv4_list else ""
            prefix = ipv4_list[0].get("prefix-length", "") if ipv4_list else ""
            ip_str = f"{ip}/{prefix}"
            
            l_vlan.append((
                iface.get("name", ""),
                iface.get("profile-name", ""),
                vconfig.get("base-iface", ""),
                str(vconfig.get("id", "")),
                ip_str,
                iface.get("state", "")
            ))
        return l_vlan

    def get_bond_interfaces(self) -> List[Tuple[str, str, str, str]]:
        l_bond: List[Tuple[str, str, str, str]] = []
        for iface in self.list_interfaces(["bond"]):
            bconfig = iface.get("link-aggregation", {})
            l_bond.append((
                iface.get("name", ""),
                iface.get("profile-name", "-"),
                "/".join(bconfig.get("port", [])),
                bconfig.get("mode", ""),
                iface.get("state", "")
            ))
        return l_bond

    # execute operations
    def set_hostname(self, hostname: str) -> Dict[str, Any]:
        """return hostname desired state."""
        return {
            "hostname": {
                "config": hostname
            }
        }

    def set_role(self, role: str) -> Tuple[bool, str]:
        """set host role using hostnamectl deployment."""
        try:
            result = subprocess.run(
                ["sudo", "hostnamectl", "deployment", role],
                check=True,
                capture_output=True,
                text=True
            )
            if role == NodeRole.HEAD.value:
                from bjefe.main import BjefeDaemon
                bjd = BjefeDaemon()
                bjd.setup_systemd_service()
            else:
                from bcocinerod.main import BcocineroDaemon
                bcd = BcocineroDaemon()
                bcd.setup_systemd_service()
            return (True, f"Succeed to set the role: {role}")
        except subprocess.CalledProcessError as e:
            return (False, str(e))
        except FileNotFoundError:
            return (False, "hostnamectl command not found.")

    def set_head_control_ip(self, hc_ip: str) -> Tuple[bool, str]:
        try:
            with open(self.am.jefe_file, "w", encoding="utf-8") as f:
                f.write(hc_ip)

            return (True, f"Succeed to save the Head Control IP.")
        except OSError as e:
            return (False, f"Fail to save the Head Control IP: {e.strerror}")

    def set_dns_servers(self, servers: List[str]) -> Dict[str, Any]:
        """return nameservers desired state."""
        return {
            "dns-resolver": {
                "config": {"server": servers}
            }
        }

    def create_bond_state(self,
                          name: str,
                          ports: List[str],
                          mode: str = "active-backup",
                          is_provider: bool = False) -> Dict[str, Any]:
        interfaces = [{"name": port, "state": "up"} for port in ports]
        bond_interface = {
            "name": name,
            "type": "bond",
            "state": "up",
            "link-aggregation": {
                "mode": mode,
                "port": ports,
                "options": {"miimon": "100"}
            }
        }
        bond_interface["profile-name"] = name
        if is_provider:
            bond_interface["profile-name"] = "provider"

        interfaces.append(bond_interface)

        return {"interfaces": interfaces}

    def create_vlan_state(self, name: str, base_iface: str, vlan_id: int, 
                          ip: str = "", prefix: int = 24,
                          gw: str = "", profile: str = "") -> Dict[str, Any]:
        vlan_iface: Dict[str, Any] = {
            "name": name, "type": "vlan", "state": "up",
            "vlan": {"base-iface": base_iface, "id": vlan_id}
        }
        if profile:
            vlan_iface["profile-name"] = profile
        if ip:
            vlan_iface["ipv4"] = {
                "enabled": True,
                "address": [{"ip": ip.strip(), "prefix-length": prefix}],
                "dhcp": False
            }

        desired_state = {"interfaces": [vlan_iface]}
        if ip and gw:
            desired_state["routes"] = {
                "config": [{
                    "destination": "0.0.0.0/0",
                    "next-hop-address": gw.strip(),
                    "next-hop-interface": name
                }]
            }
        return desired_state

    def delete_interface_state(self, name: str) -> Dict[str, Any]:
        return {"interfaces": [{"name": name, "state": "absent"}]}

