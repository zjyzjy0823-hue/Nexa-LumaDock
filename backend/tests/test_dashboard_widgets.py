"""The Dashboard reads these user-scoped business endpoints through existing stores."""


def dashboard_data(client, headers):
    websites = client.get("/api/v1/websites?sort=recent", headers=headers).json()
    devices = client.get("/api/v1/devices", headers=headers).json()
    agents = client.get("/api/v1/agents", headers=headers).json()
    collections = client.get("/api/v1/data/collections", headers=headers).json()
    workflows = client.get("/api/v1/automations", headers=headers).json()
    ledger = client.get("/api/v1/ledger/summary?month=2026-09", headers=headers).json()
    return websites, devices, agents, collections, workflows, ledger


def test_dashboard_widget_sources_are_empty_and_user_scoped(client, users):
    a, b = users
    for path in ("/api/v1/websites", "/api/v1/devices", "/api/v1/agents",
                 "/api/v1/data/collections", "/api/v1/automations", "/api/v1/ledger/summary"):
        assert client.get(path).status_code == 401

    for user in (a, b):
        sites, devices, agents, collections, workflows, ledger = dashboard_data(client, user)
        assert (sites, devices, agents, collections, workflows) == ([], [], [], [], [])
        assert (ledger["income"], ledger["expense"], ledger["balance"]) == ("0", "0", "0")

    for name in ("Site 1", "Site 2"):
        website = client.post("/api/v1/websites", headers=a, json={"name": name, "url": "https://example.com"})
        assert website.status_code == 201
        assert client.post(f"/api/v1/websites/{website.json()['id']}/visit", headers=a).status_code == 200
    device_ids = []
    for name in ("Laptop", "Server"):
        result = client.post("/api/v1/devices", headers=a, json={"name": name, "system": "Linux", "ip": "127.0.0.1"})
        assert result.status_code == 201
        device_ids.append(result.json()["id"])
    assert client.post(f"/api/v1/devices/{device_ids[0]}/heartbeat", headers=a,
                       json={"cpu": 24, "memory": 40, "disk": 55}).status_code == 200
    assert client.post("/api/v1/agents", headers=a, json={"name": "Assistant"}).status_code == 201
    for name in ("Projects", "Assets"):
        collection = client.post("/api/v1/data/collections", headers=a, json={"name": name})
        assert collection.status_code == 201
        assert client.post(f"/api/v1/data/collections/{collection.json()['id']}/records", headers=a,
                           json={"name": f"{name} record"}).status_code == 201
    workflow = client.post("/api/v1/automations", headers=a, json={"name": "Manual check"})
    assert workflow.status_code == 201
    assert client.post(f"/api/v1/automations/{workflow.json()['id']}/test-run", headers=a).status_code == 201
    for kind, amount in (("income", "100.00"), ("expense", "12.34")):
        assert client.post("/api/v1/ledger/transactions", headers=a, json={
            "type": kind, "amount": amount, "description": kind, "occurred_at": "2026-09-20T12:00:00"
        }).status_code == 201

    sites, devices, agents, collections, workflows, ledger = dashboard_data(client, a)
    assert len([site for site in sites if site["lastVisitedAt"]]) == 2
    assert len(devices) == 2 and sum(item["online"] for item in devices) == 1
    assert sum(not item["online"] for item in devices) == 1
    assert len(agents) == 1 and agents[0]["status"] == "offline" and agents[0]["enabled"] is True
    assert len(collections) == 2 and sum(item["recordCount"] for item in collections) == 2
    assert len(workflows) == 1 and workflows[0]["enabled"] is True
    assert len(client.get(f"/api/v1/automations/{workflows[0]['id']}/executions", headers=a).json()) == 1
    assert (ledger["income"], ledger["expense"], ledger["balance"]) == ("100.00", "12.34", "87.66")

    sites, devices, agents, collections, workflows, ledger = dashboard_data(client, b)
    assert (sites, devices, agents, collections, workflows) == ([], [], [], [], [])
    assert (ledger["income"], ledger["expense"], ledger["balance"]) == ("0", "0", "0")
