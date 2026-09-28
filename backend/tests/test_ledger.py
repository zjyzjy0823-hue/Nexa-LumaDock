def test_ledger_crud_summary_ownership_and_validation(client, users):
    a, b = users
    root = "/api/v1/ledger"
    assert client.get(f"{root}/categories").status_code == 401
    assert client.get(f"{root}/summary", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post(f"{root}/categories", headers=a, json={"name": "x", "type": "other"}).status_code == 422
    category = client.post(f"{root}/categories", headers=a, json={"name": "Food", "type": "expense"})
    assert category.status_code == 201
    cid = category.json()["id"]
    for method in (client.get, client.patch, client.delete):
        response = method(f"{root}/categories/{cid}", headers=b, **({"json": {"name": "x"}} if method == client.patch else {}))
        assert response.status_code == 404
    assert client.patch(f"{root}/categories/{cid}", headers=a, json={"name": "Dining"}).json()["name"] == "Dining"
    payload = {"category_id": cid, "type": "expense", "amount": "12.34", "description": "Lunch", "occurred_at": "2026-09-15T12:00:00"}
    assert client.post(f"{root}/transactions", headers=a, json={**payload, "amount": "0"}).status_code == 422
    assert client.post(f"{root}/transactions", headers=a, json={**payload, "amount": "0.001"}).status_code == 422
    assert client.post(f"{root}/transactions", headers=b, json=payload).status_code == 404
    expense = client.post(f"{root}/transactions", headers=a, json=payload)
    assert expense.status_code == 201 and expense.json()["amount"] == "12.34"
    tid = expense.json()["id"]
    for method in (client.get, client.patch, client.delete):
        response = method(f"{root}/transactions/{tid}", headers=b, **({"json": {"description": "x"}} if method == client.patch else {}))
        assert response.status_code == 404
    assert client.patch(f"{root}/transactions/{tid}", headers=a, json={"description": "Dinner"}).json()["description"] == "Dinner"
    income = client.post(f"{root}/transactions", headers=a, json={"type": "income", "amount": "100.00", "description": "Pay", "occurred_at": "2026-09-20T12:00:00"})
    assert income.status_code == 201
    assert client.post(f"{root}/transactions", headers=a, json={**payload, "type": "income"}).status_code == 422
    summary = client.get(f"{root}/summary?month=2026-09", headers=a).json()
    assert summary["income"] == "100.00" and summary["expense"] == "12.34" and summary["balance"] == "87.66"
    assert summary["categories"][0]["name"] == "Dining"
    assert client.get(f"{root}/summary?month=2026-08", headers=a).json()["expense"] == "0"
    assert client.get(f"{root}/summary?month=2026-13", headers=a).status_code == 422
    assert client.get(f"{root}/summary?month=2026-09", headers=b).json()["income"] == "0"
    assert client.delete(f"{root}/categories/{cid}", headers=a).status_code == 204
    assert client.get(f"{root}/transactions/{tid}", headers=a).json()["categoryId"] == cid
    assert client.get(f"{root}/categories/{cid}", headers=a).status_code == 404
    assert client.delete(f"{root}/transactions/{tid}", headers=a).status_code == 204
    assert client.delete(f"{root}/transactions/{income.json()['id']}", headers=a).status_code == 204
    assert client.get(f"{root}/transactions", headers=a).json() == []
