def test_automation_crud_history_validation_and_isolation(client, users):
    a, b = users
    root = "/api/v1/automations"
    assert client.get(root).status_code == 401
    assert client.get(root, headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post(root, headers=a, json={"name": "x", "trigger_type": "shell"}).status_code == 422
    payload = {"name": "Daily check", "trigger_type": "schedule", "trigger_config_json": {"cron": "0 9 * * *"},
               "workflow_json": [{"kind": "WHEN", "text": "09:00"}]}
    created = client.post(root, headers=a, json=payload)
    assert created.status_code == 201
    id = created.json()["id"]
    assert client.get(f"{root}/{id}", headers=a).json()["triggerConfigJson"]["cron"] == "0 9 * * *"
    assert client.get(f"{root}/{id}", headers=a).json()["workflowJson"][0]["kind"] == "WHEN"
    assert client.get(root, headers=b).json() == []
    for method in (client.get, client.patch, client.delete):
        response = method(f"{root}/{id}", headers=b, **({"json": {"enabled": False}} if method == client.patch else {}))
        assert response.status_code == 404
    assert client.get(f"{root}/{id}/executions", headers=b).status_code == 404
    assert client.post(f"{root}/{id}/test-run", headers=b).status_code == 404
    updated = client.patch(f"{root}/{id}", headers=a, json={"enabled": False, "workflow_json": [{"kind": "DO", "text": "Notify"}]})
    assert updated.status_code == 200 and updated.json()["enabled"] is False
    assert updated.json()["workflowJson"][0]["kind"] == "DO"
    run = client.post(f"{root}/{id}/test-run", headers=a)
    assert run.status_code == 201 and run.json()["status"] == "success"
    assert run.json()["resultJson"] == {"simulated": True}
    assert run.json()["startedAt"] and run.json()["finishedAt"]
    assert len(client.get(f"{root}/{id}/executions", headers=a).json()) == 1
    assert client.get("/api/automation", headers=a).json()["total"] == 1
    assert client.delete(f"{root}/{id}", headers=a).status_code == 204
    assert client.get(f"{root}/{id}/executions", headers=a).status_code == 404
