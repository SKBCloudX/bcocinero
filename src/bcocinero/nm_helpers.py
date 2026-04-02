import logging
import yaml
import libnmstate
from typing import Optional, List, Dict, Any, Tuple

logging.getLogger('libnmstate').setLevel(logging.ERROR)

def get_default_gateway() -> Dict[str, str]:
    state = libnmstate.show()
    routes = state.get("routes", {}).get("running", [])

    for route in routes:
        if route.get("destination") == "0.0.0.0/0":
            return {
                "gateway": route.get("next-hop-address"),
                "interface": route.get("next-hop-interface")
            }

    return None

def get_interface_info(name: str) -> Dict[str, Any]:
    state = libnmstate.show()
    return next(
        (iface for iface in state.get("interfaces", [])
            if iface.get("name") == name), {}
    )

def get_host_info() -> Dict[str, Any]:
    state = libnmstate.show()
    dns_resolver = state.get("dns-resolver", {}).get("running", {})
    return {
        "name": state.get("hostname", {}).get("running", ""),
        "nameserver": dns_resolver.get("server", [])
    }

def list_interfaces(iface_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    state = libnmstate.show()
    allowed = iface_types or ["ethernet", "bond", "vlan"]
    return [iface for iface in state.get("interfaces", []) if iface.get("type") in allowed]

def get_vlan_interfaces() -> List[Tuple[str, str, str, str, str]]:
    l_vlan = []
    for iface in list_interfaces(["vlan"]):
        vname = iface.get("name", "")
        vstate = iface.get("state", "")
        vconfig = iface.get("vlan", {})
        
        base = vconfig.get("base-iface", "")
        vid = str(vconfig.get("id", ""))
        
        ipv4_list = iface.get("ipv4", {}).get("address", [])
        ip_str = ipv4_list[0].get("ip", "") if ipv4_list else ""
        
        l_vlan.append((vname, base, vid, ip_str, vstate))
    return l_vlan

def get_bond_interfaces() -> List[Tuple[str, str, str, str]]:
    l_bond = []
    for iface in list_interfaces(["bond"]):
        bname = iface.get("name", "")
        bstate = iface.get("state", "")
        bconfig = iface.get("link-aggregation", {})
        
        bmode = bconfig.get("mode", "")
        bports = bconfig.get("port", [])
        
        l_bond.append((bname, "/".join(bports), bmode, bstate))
    return l_bond

def create_bond(name: str,
                ports: List[str],
                mode: str = "active-backup") -> Dict[str, Any]:
    interfaces = []
    for port in ports:
        interfaces.append({"name": port, "state": "up"})
        
    interfaces.append({
        "name": name,
        "type": "bond",
        "state": "up",
        "link-aggregation": {
            "mode": mode,
            "port": ports,
            "options": {"miimon": "100"}
        }
    })
    return {"interfaces": interfaces}

def create_vlan(name: str, base_iface: str, vlan_id: int, 
                ip: str = "", prefix: int = 24, gw: str = "") -> Dict[str, Any]:
    vlan_iface = {
        "name": name,
        "type": "vlan",
        "state": "up",
        "vlan": {
            "base-iface": base_iface,
            "id": vlan_id
        }
    }

    if ip:
        vlan_iface["ipv4"] = {
            "enabled": True,
            "address": [{"ip": ip.strip(), "prefix-length": prefix}],
            "dhcp": False
        }

    desired_state = {"interfaces": [vlan_iface]}

    if ip and gw:
        desired_state["routes"] = {
            "config": [
                {
                    "destination": "0.0.0.0/0",
                    "next-hop-address": gw.strip(),
                    "next-hop-interface": name
                }
            ]
        }
    return desired_state

def delete_interface(name: str) -> None:
    state = {"interfaces": [{"name": name, "state": "absent"}]}
    apply_state(state)

def get_interface_state(ifname: str) -> dict:
    state = libnmstate.show()
    for iface in state.get("interfaces", []):
        if iface["name"] == ifname:
            return iface
    raise ValueError(f"Interface {ifname} not found")

def set_hostname(hostname: str) -> Dict[str, Any]:
    return {
        "hostname": {
            "config": hostname
        }
    }

def set_dns_servers(servers: List[str]) -> Dict[str, Any]:
    return {
        "dns-resolver": {
            "config": {"server": servers}
        }
    }

def save_state(filename: str, state: Dict[str, Any]) -> None:
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            yaml.dump(state, f, allow_unicode=True)
    except Exception as e:
        print(f"Save failed: {e}")

def apply_state(state: Dict[str, Any]) -> None:
    try:
        libnmstate.apply(state)
    except Exception as e:
        raise RuntimeError(f"Apply failed: {e}")

