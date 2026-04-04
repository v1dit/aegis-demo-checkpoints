from __future__ import annotations

ZONE_ORDER = ["public", "app", "data", "admin"]
ENTERPRISE_ZONE_ORDER = ["public", "app", "data", "admin", "identity", "saas"]

SERVICE_CATALOG = [
    "web",
    "api",
    "auth",
    "db",
    "cache",
    "dns",
    "ssh",
    "queue",
]

ASSET_SERVICE_CATALOG = {
    "endpoint": ["web", "dns", "ssh"],
    "server": ["web", "api", "auth", "db", "cache", "dns", "ssh", "queue"],
    "idp": ["auth", "api", "dns"],
    "crm_saas": ["web", "api", "queue"],
    "integration_service": ["api", "queue", "auth"],
    "data_store": ["db", "cache", "api"],
}

VULN_CATALOG = {
    "web": ["SYNTH-CVE-2026-1001", "SYNTH-CVE-2026-1002"],
    "api": ["SYNTH-CVE-2026-1101", "SYNTH-CVE-2026-1102"],
    "auth": ["SYNTH-CVE-2026-1201"],
    "db": ["SYNTH-CVE-2026-1301", "SYNTH-CVE-2026-1302"],
    "cache": ["SYNTH-CVE-2026-1401"],
    "dns": ["SYNTH-CVE-2026-1501"],
    "ssh": ["SYNTH-CVE-2026-1601"],
    "queue": ["SYNTH-CVE-2026-1701"],
}

MITRE_TACTIC_BY_ACTION = {
    "scan_host": "Reconnaissance",
    "enumerate_service": "Reconnaissance",
    "exploit_vulnerability": "Initial Access",
    "lateral_move": "Lateral Movement",
    "privilege_escalate": "Credential Access",
    "exfiltrate_data": "Exfiltration",
    "monitor_host": "Defense Evasion",
    "patch_service": "Defense Evasion",
    "isolate_host": "Defense Evasion",
    "block_connection": "Defense Evasion",
    "rotate_credentials": "Defense Evasion",
    "deploy_deception": "Defense Evasion",
    "step_marker": "Execution",
}
