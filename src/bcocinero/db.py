import logging
import rqdb
from typing import List, Dict, Any

DEFAULT_URLS = ["127.0.0.1:4001"]

class BcocineroDB:
    def __init__(self, urls: List[str] = DEFAULT_URLS):
        self.conn = rqdb.connect(urls)
        self.cursor = self.conn.cursor()

    def initialize_schema(self) -> bool:
        logging.info("Initializing rqlite schema...")
        schemas = [
        """CREATE TABLE IF NOT EXISTS hosts (
            machine_id TEXT PRIMARY KEY,
            hostname TEXT,
            role TEXT,
            mgmt_ip TEXT UNIQUE,
            nameservers TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS bonds (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          machine_id TEXT NOT NULL,
          name TEXT NOT NULL,
          mode TEXT,
          ports TEXT,
          FOREIGN KEY (machine_id) REFERENCES hosts(machine_id) ON DELETE CASCADE,
          UNIQUE(machine_id, name)
        )""",
        """CREATE TABLE IF NOT EXISTS vlans (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          machine_id TEXT NOT NULL,
          name TEXT NOT NULL,
          base_iface TEXT,
          vlan_id INTEGER,
          profile TEXT,
          ip TEXT,
          FOREIGN KEY (machine_id) REFERENCES hosts(machine_id) ON DELETE CASCADE,
          UNIQUE(machine_id, name)
        )"""
        ]
        try:
            for s in schemas:
                self.cursor.execute(s)
            logging.info("Schema initialization is succeeded.")
            return True
        except Exception as e:
            logging.error(f"Schema initializationis failed: {e}")
            return False

    def upsert_host(self, **kwargs) -> None:
        sql = """
        INSERT INTO hosts 
            (machine_id, hostname, role, mgmt_ip, nameservers, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(machine_id) DO UPDATE SET
            hostname=excluded.hostname,
            role=excluded.role,
            mgmt_ip=excluded.mgmt_ip,
            nameservers=excluded.nameservers,
            updated_at=excluded.updated_at
        """
        try:
            machine_id = kwargs.get("machine_id")
            hostname = kwargs.get("hostname")
            role = kwargs.get("role", "")
            mgmt_ip = kwargs.get("mgmt_ip", "")
            ns = kwargs.get("nameservers", [])
            s_ns = ",".join(ns)
            if not machine_id:
                logging.error("Fail to upsert host: 'machine_id' is missing.")
                return

            self.cursor.execute(
                sql, [machine_id,  hostname, role, mgmt_ip, s_ns]
            )
            logging.info(f"Succeed to upsert host: {hostname}")
        except Exception as e:
            logging.error(f"Fail to upsert host {hostname}: {e}")

    def upsert_bond(self, **kwargs) -> None:
        sql = """
        INSERT INTO bonds (machine_id, name, mode, ports)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(machine_id, name) DO UPDATE SET
            mode=excluded.mode,
            ports=excluded.ports
        """
        lag_info = kwargs.get("link-aggregation", {})
        mode = lag_info.get("mode")
        ports = lag_info.get("port", [])
        s_ports = ",".join(ports) if isinstance(ports, list) else ""

        try:
            self.cursor.execute(sql, [
                kwargs.get("machine_id"), kwargs.get("name"),
                mode, s_ports
            ])
            logging.info(f"Succeed to upsert bond: {kwargs.get('name')}")
        except Exception as e:
            logging.error(f"Upsert bond error: {e}")

    def upsert_vlan(self, **kwargs) -> None:
        sql = """
        INSERT INTO vlans
            (machine_id, name, base_iface, vlan_id, profile, ip)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(machine_id, name) DO UPDATE SET
            base_iface=excluded.base_iface,
            vlan_id=excluded.vlan_id,
            profile=excluded.profile,
            ip=excluded.ip
        """
        vlan_info = kwargs.get("vlan", {})
        vlan_id = vlan_info.get("id")
        base_iface = vlan_info.get("base-iface")
        ipv4_addrs = kwargs.get("ipv4", {}).get("address", [])
        ip = ipv4_addrs[0].get("ip") if ipv4_addrs else ""

        try:
            self.cursor.execute(sql, [
                kwargs.get("machine_id"), kwargs.get("name"),
                base_iface, vlan_id,
                kwargs.get("profile-name"), ip
            ])
            logging.info(f"Succeed to upsert vlan: {kwargs.get('name')}")
        except Exception as e:
            logging.error(f"Upsert vlan error: {e}")

