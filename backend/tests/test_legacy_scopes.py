def test_legacy_scoped_api_keys_read_real_owner_data(client, users):
    a, b = users
    client.post("/api/v1/data/collections", headers=a, json={"name": "Private"})
    client.post("/api/v1/automations", headers=a, json={"name": "Private workflow"})
    client.post("/api/v1/data/collections", headers=b, json={"name": "Other"})
    for scope, path, field, expected in (
        ("Data", "/api/data", "collections", "Private"),
        ("Automation", "/api/automation", "workflows", "Private workflow"),
    ):
        response = client.post("/api/api-keys", headers=a, json={"name": f"{scope} key", "scopes": [scope], "expires_in_days": None})
        assert response.status_code == 201
        key_headers = {"Authorization": f"Bearer {response.json()['secret']}"}
        own = client.get(path, headers=key_headers)
        assert own.status_code == 200
        assert own.json()[field][0]["name"] == expected
        other_path = "/api/automation" if scope == "Data" else "/api/data"
        assert client.get(other_path, headers=key_headers).status_code == 403
    read = client.post("/api/api-keys", headers=a, json={"name": "Read key", "scopes": ["Read"], "expires_in_days": None})
    read_headers = {"Authorization": f"Bearer {read.json()['secret']}"}
    assert client.get("/api/data", headers=read_headers).json()["collections"][0]["name"] == "Private"
    assert client.get("/api/automation", headers=read_headers).json()["workflows"][0]["name"] == "Private workflow"
