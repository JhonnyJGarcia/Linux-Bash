# Linux-Bash

Small, practical scripts I use to set up and manage Linux machines in my home lab.

## Scripts

### `network/configura_rete_statica.py`

Interactive Python script that assigns a **static network configuration** (IP/CIDR, gateway, DNS, hostname) to a Linux machine.

- Lists the interfaces actually present on the host (read from `/sys/class/net`) with their link state, and lets you pick one
- Validates every input with Python's `ipaddress` module before touching the system
- **Auto-detects the network stack** and applies the config the right way:
  - **netplan** (Ubuntu ≥ 18.04) — writes `/etc/netplan/99-static-config.yaml` and runs `netplan apply`
  - **NetworkManager** — modifies the active connection via `nmcli`
  - **ifupdown** (`/etc/network/interfaces`, Debian legacy) — appends a static stanza and restarts networking
- Backs up any file it changes (`*.bak-<timestamp>`) and asks for confirmation with a summary first
- Only uses the Python standard library — nothing to install

Prompts are in Italian.

```bash
sudo python3 network/configura_rete_statica.py
```

> ⚠️ Changing the IP of a remote machine will drop your SSH session — run it from the console or be ready to reconnect on the new address.
