import os
import ipaddress
import platform
import socket
import time

import psutil

CLIENT_VERSION = "0.1.0"


def windows_name() -> str:
    version = platform.win32_ver()[1]
    try:
        build = int(version.split(".")[-1])
    except ValueError:
        build = 0
    return f"Windows {11 if build >= 22000 else platform.release()}"


def cpu_name() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()[:160]
    except (ImportError, OSError):
        return platform.processor()[:160] or None


def local_ipv4() -> str | None:
    lan_ranges = tuple(ipaddress.ip_network(network) for network in
                       ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    try:
        stats = psutil.net_if_stats()
        candidates = []
        for name, addresses in psutil.net_if_addrs().items():
            if not stats.get(name) or not stats[name].isup:
                continue
            for address in addresses:
                if address.family != socket.AF_INET:
                    continue
                ip = ipaddress.ip_address(address.address)
                if not any(ip in network for network in lan_ranges):
                    continue
                virtual = any(word in name.lower() for word in ("vmware", "virtual", "vethernet", "hyper-v", "wsl", "loopback"))
                candidates.append((virtual, address.address))
        if candidates:
            return sorted(candidates, key=lambda candidate: candidate[0])[0][1]
    except (OSError, ValueError):
        pass
    return None


def collect() -> dict:
    if platform.system() != "Windows":
        raise RuntimeError("The Device Client supports Windows only")
    memory = psutil.virtual_memory()
    system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\") + "\\"
    disk = psutil.disk_usage(system_drive)
    battery = psutil.sensors_battery()
    return {
        "hostname": socket.gethostname()[:120],
        "os": "Windows",
        "osVersion": windows_name(),
        "architecture": platform.machine()[:40],
        "cpuName": cpu_name(),
        "cpu": psutil.cpu_percent(interval=0.2),
        "memory": memory.percent,
        "memoryTotal": memory.total,
        "memoryUsed": memory.used,
        "disk": disk.percent,
        "diskTotal": disk.total,
        "diskUsed": disk.used,
        "battery": battery.percent if battery is not None else None,
        "uptimeSeconds": max(0, int(time.time() - psutil.boot_time())),
        "localIp": local_ipv4(),
        "clientVersion": CLIENT_VERSION,
    }
