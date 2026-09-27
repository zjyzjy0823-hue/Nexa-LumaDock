def test_settings_auth_defaults_persistence_and_isolation(client, users):
    a, b = users
    assert client.get("/api/v1/settings").status_code == 401
    assert client.get("/api/v1/settings", headers={"Authorization": "Bearer invalid"}).status_code == 401
    defaults = client.get("/api/v1/settings", headers=a).json()
    assert defaults["theme"] == "system" and defaults["timezone"] == "Asia/Shanghai"
    assert defaults["notifications"]["events"]["deviceOffline"] is True
    saved = client.patch("/api/v1/settings", headers=a, json={"theme": "dark", "language": "en-US", "notifications": {"events": {"deviceOffline": False}, "channels": {"desktop": True}}})
    assert saved.status_code == 200
    assert client.get("/api/v1/settings", headers=a).json()["theme"] == "dark"
    assert client.get("/api/v1/settings", headers=a).json()["notifications"]["events"]["deviceOffline"] is False
    assert client.get("/api/v1/settings", headers=b).json()["theme"] == "system"
    assert client.patch("/api/v1/settings", headers=a, json={"theme": "unknown"}).status_code == 422


def test_account_username_avatar_and_password(client, users):
    a, b = users
    assert client.patch("/api/v1/account", json={"username": "newname"}).status_code == 401
    updated = client.patch("/api/v1/account", headers=a, json={"username": "  NewName  ", "avatar": "https://example.com/a.png"})
    assert updated.status_code == 200 and updated.json()["username"] == "NewName"
    assert updated.json()["avatar"] == "https://example.com/a.png"
    assert "password" not in updated.json() and "password_hash" not in updated.json()
    assert client.patch("/api/v1/account", headers=b, json={"username": "newname"}).status_code == 409
    assert client.patch("/api/v1/account", headers=a, json={"username": "x"}).status_code == 422
    assert client.post("/api/v1/account/password", headers=a, json={"current_password": "wrong", "new_password": "newpassword123"}).status_code == 400
    assert client.post("/api/v1/account/password", headers=a, json={"current_password": "password123", "new_password": "short"}).status_code == 422
    changed = client.post("/api/v1/account/password", headers=a, json={"current_password": "password123", "new_password": "newpassword123"})
    assert changed.status_code == 200 and "password" not in changed.json()
    assert client.post("/api/v1/auth/login", json={"username": "NewName", "password": "newpassword123"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": "NewName", "password": "password123"}).status_code == 401
