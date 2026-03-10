import logging
import yaml
import libnmstate

from typing import Optional
from libnmstate.schema import DNS, HostNameState
from libnmstate.schema import (
    Interface,
    InterfaceIPv4,
    InterfaceState,
    InterfaceType,
    Bond,
    VLAN,
)

logging.getLogger('libnmstate').setLevel(logging.ERROR)


def get_interface_info(name: str) -> dict:
    state = libnmstate.show()
    d_iface = next(
        (iface for iface in state.get(Interface.KEY, [])
            if iface.get(Interface.NAME, "") == name), {}
    )
    return d_iface
    
def get_host_info() -> dict:
    state = libnmstate.show()
    d_host = dict()
    d_host["name"] = state["hostname"]["running"]
    d_host["nameserver"] = state["dns-resolver"]["running"]["server"]

    return d_host

def list_interfaces(iface_type: list = []) -> list[dict]:
    state = libnmstate.show()
    l_allowed_types = ["ethernet", "bond", "vlan"]
    if iface_type:
        l_allowed_types = iface_type
    return [iface for iface 
        in state.get("interfaces", []) if iface["type"] in l_allowed_types]

def get_bond_interfaces() -> list[tuple]:
    l_iface = list_interfaces(["bond"])
    l_bond = []
    for iface in l_iface:
        bname = iface.get(Interface.NAME)
        bstate = iface.get(Interface.STATE)
        bmode = ""
        bports = []
        bconfig = iface.get(Bond.CONFIG_SUBTREE, {})
        if bconfig:
            bmode = bconfig.get(Bond.MODE, "")
            l_ports = bconfig.get(Bond.PORTS_CONFIG_SUBTREE, [])
            bports = [p["name"] for p in l_ports]
        l_bond.append((bname, "/".join(bports), bmode, bstate))

    return l_bond

def delete_bond_interface(bname: str) -> None:
    state = {
        "interfaces": [
            {
                "name": bname,
                "type": "bond",
                "state": "absent"
            }
        ]
    }
    apply_state(state)

def get_interface_state(ifname: str) -> dict:
    state = libnmstate.show()
    for iface in state.get("interfaces", []):
        if iface["name"] == ifname:
            return iface
    raise ValueError(f"Interface {ifname} not found")

def build_static_ipv4_state(ifname: str, address: str, prefix: int, gateway: str) -> dict:
    iface_state = {
        "name": ifname,
        "type": "ethernet",
        "state": "up",
        "ipv4": {
            "enabled": True,
            "address": [{"ip": address, "prefix-length": prefix}],
        },
    }
    if gateway:
        iface_state["ipv4"]["gateway"] = gateway
    return {"interfaces": [iface_state]}

def set_hostname(hostname: str) -> dict:
    d_state = {}
    d_hostname = {
        HostNameState.CONFIG: hostname
    }
    d_state[HostNameState.KEY] = d_hostname

    return d_state

def set_dns_servers(servers: list[str], 
    search_domains: Optional[list[str]] = None) -> dict:

    d_state = {}

    dns_config = {
        DNS.CONFIG: {
            DNS.SERVER: servers,
        }
    }

    if search_domains:
        dns_config[DNS.CONFIG][DNS.SEARCH] = search_domains

    d_state[DNS.KEY] = dns_config

    return d_state

def create_bond(
    name: str,
    ports: list[str],
    mode: str = "active-standby") -> dict:
    d_state = {
        Interface.KEY: []
    }
    for iface in ports:
        d_state[Interface.KEY].append(
            {
                Interface.NAME: iface,
                Interface.TYPE: InterfaceType.ETHERNET,
                Interface.STATE: InterfaceState.UP,
            }
        )
    d_state[Interface.KEY].append(
        {
            Interface.NAME: name,
            Interface.TYPE: InterfaceType.BOND,
            Interface.STATE: InterfaceState.UP,
            Bond.CONFIG_SUBTREE: {
                Bond.MODE: mode,
                Bond.PORT: ports,
                Bond.OPTIONS_SUBTREE: {
                    "miimon": "100",
                },
            },
        }
    )

    return d_state

def save_state(filename: str, state: dict) -> None:
    with open(filename, 'w', encoding='utf-8') as f:
        yaml.dump(state, f, allow_unicode=True)

def apply_state(state: dict) -> None:
    libnmstate.apply(state)

