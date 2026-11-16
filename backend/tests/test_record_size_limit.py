import json

import pytest


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("size", [65536, 65537])
def test_record_data_json_utf8_size_limit(client, users, method, size):
    owner, _ = users
    cid = client.post("/api/v1/data/collections", headers=owner, json={"name": "Size limit"}).json()["id"]
    endpoint = f"/api/v1/data/collections/{cid}/records"
    if method == "PATCH":
        rid = client.post(endpoint, headers=owner, json={"name": "Before"}).json()["id"]
        endpoint = f"/api/v1/data/records/{rid}"
    # Include multibyte text: this is the serialized UTF-8 size, not characters.
    prefix = {"text": "中"}
    overhead = len(json.dumps(prefix, ensure_ascii=False).encode("utf-8"))
    data = {"text": "中" + "x" * (size - overhead)}
    assert len(json.dumps(data, ensure_ascii=False).encode("utf-8")) == size
    payload = {"data_json": data, **({"name": "Record"} if method == "POST" else {})}
    result = client.request(method, endpoint, headers=owner, json=payload)
    assert result.status_code == (422 if size > 65536 else 201 if method == "POST" else 200)
    if size > 65536:
        assert "65536" in result.text and "byte" in result.text.lower()
        if method == "PATCH":
            assert client.get(endpoint, headers=owner).json()["dataJson"] == {}
    else:
        assert result.json()["dataJson"] == data
