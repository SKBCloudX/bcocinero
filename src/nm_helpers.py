import logging
import yaml
import libnmstate
from typing import Optional, List, Dict, Any, Tuple

# libnmstate 로그 레벨 설정
logging.getLogger('libnmstate').setLevel(logging.ERROR)

def get_interface_info(name: str) -> Dict[str, Any]:
    """특정 인터페이스의 상세 정보 반환"""
    state = libnmstate.show()
    return next(
        (iface for iface in state.get("interfaces", [])
            if iface.get("name") == name), {}
    )

def get_host_info() -> Dict[str, Any]:
    """호스트 이름 및 DNS 정보 반환"""
    state = libnmstate.show()
    dns_resolver = state.get("dns-resolver", {}).get("running", {})
    return {
        "name": state.get("hostname", {}).get("running", ""),
        "nameserver": dns_resolver.get("server", [])
    }

def list_interfaces(iface_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """인터페이스 목록 필터링 반환"""
    state = libnmstate.show()
    allowed = iface_types or ["ethernet", "bond", "vlan"]
    return [iface for iface in state.get("interfaces", []) if iface.get("type") in allowed]

def get_vlan_interfaces() -> List[Tuple[str, str, str, str, str]]:
    """VLAN 인터페이스 정보 목록 반환 (DataTable용)"""
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
    """Bond 인터페이스 정보 목록 반환 (DataTable용)"""
    l_bond = []
    for iface in list_interfaces(["bond"]):
        bname = iface.get("name", "")
        bstate = iface.get("state", "")
        bconfig = iface.get("link-aggregation", {})
        
        bmode = bconfig.get("mode", "")
        bports = bconfig.get("port", [])
        
        l_bond.append((bname, "/".join(bports), bmode, bstate))
    return l_bond

def create_bond(name: str, ports: List[str], mode: str = "active-backup") -> Dict[str, Any]:
    """Bond 생성을 위한 상태 딕셔너리 생성"""
    interfaces = []
    # 슬레이브 포트들 활성화
    for port in ports:
        interfaces.append({"name": port, "state": "up"})
        
    # 본딩 인터페이스 설정
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
    """VLAN 생성을 위한 상태 딕셔너리 생성"""
    vlan_iface = {
        "name": name,
        "type": "vlan",
        "state": "up",
        "vlan": {
            "base-iface": base_iface,
            "id": vlan_id
        }
    }

    if ip.strip():
        vlan_iface["ipv4"] = {
            "enabled": True,
            "address": [{"ip": ip, "prefix-length": prefix}],
            "dhcp": False
        }
        # 게이트웨이는 전역 routes가 아닌 인터페이스 레벨에서도 가능하지만, 
        # libnmstate 표준에 따라 routes로 분리하는 것이 안정적입니다.

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
    """인터페이스 삭제 (absent 상태 적용)"""
    state = {"interfaces": [{"name": name, "state": "absent"}]}
    apply_state(state)

def get_interface_state(ifname: str) -> dict:
    state = libnmstate.show()
    for iface in state.get("interfaces", []):
        if iface["name"] == ifname:
            return iface
    raise ValueError(f"Interface {ifname} not found")

def set_hostname(hostname: str) -> Dict[str, Any]:
    """호스트네임 설정 딕셔너리 생성"""
    return {
        "hostname": {
            "running": hostname,
            "config": hostname
        }
    }

def set_dns_servers(servers: List[str]) -> Dict[str, Any]:
    """DNS 서버 설정 딕셔너리 생성"""
    return {
        "dns-resolver": {
            "config": {"server": servers}
        }
    }

def save_state(filename: str, state: Dict[str, Any]) -> None:
    """상태를 YAML 파일로 저장"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            yaml.dump(state, f, allow_unicode=True)
    except Exception as e:
        print(f"Save failed: {e}")

def apply_state(state: Dict[str, Any]) -> None:
    """libnmstate를 통해 상태 적용"""
    try:
        libnmstate.apply(state)
    except Exception as e:
        raise RuntimeError(f"Apply failed: {e}")

