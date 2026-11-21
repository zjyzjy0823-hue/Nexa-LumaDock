import asyncio

import httpx

from agent_node.port_preview import PortPreviewManager


def test_loopback_preview_redeems_ticket_once_and_keeps_upstream_private():
    async def run():
        records: list[str] = []

        async def upstream(reader, writer):
            try:
                content = await reader.readuntil(b"\r\n\r\n")
                records.append(content.decode())
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 12\r\nSet-Cookie: upstream=private\r\nConnection: close\r\n\r\nNODE_PREVIEW")
                await writer.drain()
            except asyncio.IncompleteReadError:
                pass  # The preview manager probes TCP before opening the lease.
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        manager = PortPreviewManager()
        async with server:
            try:
                target = server.sockets[0].getsockname()[1]
                link = await manager.open("mock", "preview", "127.0.0.1", target)
                origin = str(httpx.URL(link).copy_with(path="/"))
                async with httpx.AsyncClient(trust_env=False) as client, httpx.AsyncClient(trust_env=False) as other:
                    assert (await client.get(origin)).status_code == 403
                    assert (await client.get(link)).status_code == 303
                    assert (await other.get(link)).status_code == 403
                    response = await client.get(origin + "assets/test?hello=world", headers={"Authorization": "Bearer must-not-forward"})
                    assert response.text == "NODE_PREVIEW"
                    assert "set-cookie" not in response.headers
                    assert records[0].startswith("GET /assets/test?hello=world ")
                    assert "authorization:" not in records[0].lower() and "cookie:" not in records[0].lower()
                    assert (await client.post(origin, headers={"Origin": "https://elsewhere.invalid"})).status_code == 403
                    assert (await client.get(link)).status_code == 303
                    assert len(records) == 1
            finally:
                await manager.close()

    asyncio.run(run())
