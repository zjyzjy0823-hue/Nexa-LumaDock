def test_data_crud_ownership_and_cascade(client, users):
    a, b = users
    root = "/api/v1/data"
    assert client.get(f"{root}/collections").status_code == 401
    assert client.get(f"{root}/collections", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.post(f"{root}/collections", headers=a, json={"name": " "}).status_code == 422
    created = client.post(f"{root}/collections", headers=a, json={"name": "Books", "description": "Read"})
    assert created.status_code == 201
    cid = created.json()["id"]
    assert len(client.get(f"{root}/collections", headers=a).json()) == 1
    assert client.get(f"{root}/collections", headers=b).json() == []
    for method in (client.get, client.patch, client.delete):
        response = method(f"{root}/collections/{cid}", headers=b, **({"json": {"name": "x"}} if method == client.patch else {}))
        assert response.status_code == 404
    assert client.post(f"{root}/collections/{cid}/records", headers=b, json={"name": "X"}).status_code == 404
    assert client.get(f"{root}/collections/{cid}/records", headers=b).status_code == 404
    assert client.post(f"{root}/collections/{cid}/records", headers=a, json={"name": " "}).status_code == 422
    record = client.post(f"{root}/collections/{cid}/records", headers=a, json={"name": "Dune", "status": "reading", "category": "sci-fi", "data_json": {"pages": 400}})
    assert record.status_code == 201 and record.json()["dataJson"]["pages"] == 400
    rid = record.json()["id"]
    assert client.get(f"{root}/records/{rid}", headers=a).status_code == 200
    for method in (client.get, client.patch, client.delete):
        response = method(f"{root}/records/{rid}", headers=b, **({"json": {"name": "x"}} if method == client.patch else {}))
        assert response.status_code == 404
    assert client.patch(f"{root}/records/{rid}", headers=a, json={"name": "Dune 2"}).json()["name"] == "Dune 2"
    assert client.patch(f"{root}/collections/{cid}", headers=a, json={"name": "Novels"}).json()["name"] == "Novels"
    assert client.get(f"{root}/collections/{cid}", headers=a).json()["recordCount"] == 1
    assert client.get("/api/data", headers=a).json()["totalRecords"] == 1
    assert client.delete(f"{root}/collections/{cid}", headers=a).status_code == 204
    assert client.get(f"{root}/records/{rid}", headers=a).status_code == 404


def test_data_record_delete(client, users):
    a, _ = users
    cid = client.post("/api/v1/data/collections", headers=a, json={"name": "X"}).json()["id"]
    rid = client.post(f"/api/v1/data/collections/{cid}/records", headers=a, json={"name": "Y"}).json()["id"]
    assert client.delete(f"/api/v1/data/records/{rid}", headers=a).status_code == 204
    assert client.get(f"/api/v1/data/collections/{cid}", headers=a).json()["recordCount"] == 0
