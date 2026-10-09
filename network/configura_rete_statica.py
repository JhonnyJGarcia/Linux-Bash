#!/usr/bin/env python3
"""
configura_rete_statica.py

Script interattivo per assegnare una configurazione di rete statica
(IP, gateway, DNS, hostname) su una macchina Linux.

Rileva automaticamente il sistema di gestione rete in uso:
    - netplan            (Ubuntu >= 18.04)
    - NetworkManager      (nmcli)
    - /etc/network/interfaces  (Debian/Ubuntu "legacy")

Deve essere eseguito con privilegi di root (sudo).
"""

import ipaddress
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def err(msg: str) -> None:
    print(f"Errore: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, check=True):
    """Esegue un comando di sistema mostrando output in tempo reale."""
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def ask(prompt: str, validator=None, allow_empty=False) -> str:
    while True:
        value = input(f"{prompt}: ").strip()
        if not value and allow_empty:
            return value
        if not value:
            print("Il valore non può essere vuoto, riprova.")
            continue
        if validator is None or validator(value):
            return value
        print("Valore non valido, riprova.")


def is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_valid_cidr(value: str) -> bool:
    try:
        ipaddress.ip_interface(value)
        return True
    except ValueError:
        return False


def list_interfaces():
    """Legge le interfacce di rete realmente presenti sul dispositivo
    direttamente da /sys/class/net (funziona su qualsiasi distro/setup,
    senza dipendere dal comando 'ip')."""
    net_dir = Path("/sys/class/net")
    if not net_dir.exists():
        return []
    return sorted(p.name for p in net_dir.iterdir() if p.name != "lo")


def interface_state(name: str) -> str:
    try:
        return Path(f"/sys/class/net/{name}/operstate").read_text().strip()
    except Exception:
        return "sconosciuto"


def choose_interface() -> str:
    """Mostra un menu con le sole interfacce realmente presenti sul
    dispositivo (lette da /sys/class/net) e fa scegliere all'utente."""
    interfaces = list_interfaces()

    if not interfaces:
        err("Nessuna interfaccia di rete rilevata sul dispositivo.")

    print("Interfacce di rete rilevate su questo dispositivo:\n")
    for i, name in enumerate(interfaces, start=1):
        stato = interface_state(name)
        print(f"  {i}) {name}  [{stato}]")
    print()

    while True:
        scelta = input("Seleziona il numero dell'interfaccia da configurare: ").strip()
        if scelta.isdigit() and 1 <= int(scelta) <= len(interfaces):
            return interfaces[int(scelta) - 1]
        print("Scelta non valida, riprova.")


def detect_network_manager():
    if shutil.which("netplan") and Path("/etc/netplan").is_dir():
        return "netplan"
    if shutil.which("nmcli"):
        try:
            status = subprocess.check_output(
                ["systemctl", "is-active", "NetworkManager"], text=True
            ).strip()
            if status == "active":
                return "networkmanager"
        except Exception:
            pass
    if Path("/etc/network/interfaces").exists():
        return "interfaces"
    return None


def backup_file(path: Path):
    if path.exists():
        backup = path.with_suffix(path.suffix + f".bak-{int(time.time())}")
        shutil.copy2(path, backup)
        print(f"Backup creato: {backup}")


def apply_netplan(iface, static_ip, gateway, dns_list):
    config_path = Path("/etc/netplan/99-static-config.yaml")
    dns_yaml = ", ".join(dns_list)

    content = f"""network:
  version: 2
  ethernets:
    {iface}:
      dhcp4: no
      addresses: [{static_ip}]
      routes:
        - to: default
          via: {gateway}
      nameservers:
        addresses: [{dns_yaml}]
"""
    backup_file(config_path)
    config_path.write_text(content)
    config_path.chmod(0o600)
    run(["netplan", "apply"])
    print(f"Configurazione netplan scritta in {config_path} e applicata.")


def apply_networkmanager(iface, static_ip, gateway, dns_list):
    # trova la connessione attiva collegata all'interfaccia
    conn_name = iface
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
            text=True,
        )
        for line in out.splitlines():
            name, device = line.split(":", 1)
            if device == iface:
                conn_name = name
                break
    except Exception:
        pass

    dns_str = " ".join(dns_list)

    run([
        "nmcli", "connection", "modify", conn_name,
        "ipv4.addresses", static_ip,
        "ipv4.gateway", gateway,
        "ipv4.dns", dns_str,
        "ipv4.method", "manual",
    ])
    run(["nmcli", "connection", "down", conn_name], check=False)
    run(["nmcli", "connection", "up", conn_name])
    print(f"Configurazione NetworkManager applicata alla connessione '{conn_name}'.")


def apply_interfaces(iface, static_ip, gateway, dns_list):
    path = Path("/etc/network/interfaces")
    backup_file(path)

    net_if = ipaddress.ip_interface(static_ip)
    ip_addr = str(net_if.ip)
    netmask = str(net_if.netmask)
    dns_str = " ".join(dns_list)

    block = f"""
# Configurazione statica aggiunta da configura_rete_statica.py
auto {iface}
iface {iface} inet static
    address {ip_addr}
    netmask {netmask}
    gateway {gateway}
    dns-nameservers {dns_str}
"""
    with path.open("a") as f:
        f.write(block)

    try:
        run(["systemctl", "restart", "networking"])
    except Exception:
        run(["service", "networking", "restart"], check=False)

    print(f"Configurazione aggiunta a {path} e servizio di rete riavviato.")


def main():
    if os.geteuid() != 0:
        err("Questo script deve essere eseguito con sudo/root.")

    print("=== Configurazione rete statica ===\n")

    iface = choose_interface()

    static_ip = ask(
        "Indirizzo IP con prefisso CIDR (es. 192.168.1.50/24)",
        validator=is_valid_cidr,
    )
    gateway = ask("Gateway (es. 192.168.1.1)", validator=is_valid_ip)
    dns1 = ask("DNS primario (es. 8.8.8.8)", validator=is_valid_ip)
    dns2 = ask(
        "DNS secondario (invio per saltare)",
        validator=is_valid_ip,
        allow_empty=True,
    )
    new_hostname = ask(
        "Hostname da impostare (invio per lasciare invariato)",
        allow_empty=True,
    )

    dns_list = [dns1] + ([dns2] if dns2 else [])

    print("\nRiepilogo configurazione:")
    print(f"  Interfaccia : {iface}")
    print(f"  IP/CIDR     : {static_ip}")
    print(f"  Gateway     : {gateway}")
    print(f"  DNS         : {', '.join(dns_list)}")
    if new_hostname:
        print(f"  Hostname    : {new_hostname}")

    confirm = input("\nConfermi e procedo con la configurazione? [s/N] ").strip().lower()
    if confirm != "s":
        print("Operazione annullata.")
        return

    if new_hostname:
        try:
            run(["hostnamectl", "set-hostname", new_hostname])
        except Exception:
            Path("/etc/hostname").write_text(new_hostname + "\n")
        print(f"Hostname impostato a: {new_hostname}")

    manager = detect_network_manager()
    if manager == "netplan":
        print("Rilevato: netplan")
        apply_netplan(iface, static_ip, gateway, dns_list)
    elif manager == "networkmanager":
        print("Rilevato: NetworkManager (nmcli)")
        apply_networkmanager(iface, static_ip, gateway, dns_list)
    elif manager == "interfaces":
        print("Rilevato: /etc/network/interfaces (legacy)")
        apply_interfaces(iface, static_ip, gateway, dns_list)
    else:
        err("Nessun sistema di gestione rete supportato rilevato (netplan / NetworkManager / interfaces).")

    print(f"\nFatto. Verifica con: ip addr show {iface}")


if __name__ == "__main__":
    main()
