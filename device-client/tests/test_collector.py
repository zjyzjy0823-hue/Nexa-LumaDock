from types import SimpleNamespace

import collector


def test_collect_without_battery(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    monkeypatch.setattr(collector.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(collector, "windows_name", lambda: "Windows 11")
    monkeypatch.setattr(collector, "cpu_name", lambda: "CPU")
    monkeypatch.setattr(collector, "local_ipv4", lambda: None)
    monkeypatch.setattr(collector.psutil, "virtual_memory", lambda: SimpleNamespace(percent=50, total=1000, used=500))
    monkeypatch.setattr(collector.psutil, "disk_usage", lambda _: SimpleNamespace(percent=25, total=2000, used=500))
    monkeypatch.setattr(collector.psutil, "sensors_battery", lambda: None)
    monkeypatch.setattr(collector.psutil, "cpu_percent", lambda **_: 12)
    monkeypatch.setattr(collector.psutil, "boot_time", lambda: 100)
    monkeypatch.setattr(collector.time, "time", lambda: 200)
    result = collector.collect()
    assert result["battery"] is None
    assert (result["memory"], result["memoryTotal"], result["memoryUsed"]) == (50, 1000, 500)
    assert (result["disk"], result["diskTotal"], result["diskUsed"]) == (25, 2000, 500)
    assert result["uptimeSeconds"] == 100
    assert {"hostname", "os", "osVersion", "architecture", "cpuName", "cpu", "localIp", "clientVersion"}.issubset(result)
