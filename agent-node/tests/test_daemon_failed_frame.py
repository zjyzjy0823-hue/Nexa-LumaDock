import asyncio
import json
from unittest.mock import AsyncMock, Mock

from agent_node.adapters.mock import MockAdapter
from agent_node.config import DirectTransferConfig, NodeConfig
from agent_node.daemon import AgentNodeDaemon


def test_handle_command_sends_failed_frame_when_adapter_raises(tmp_path, monkeypatch):
    config = NodeConfig(
        core_url="http://127.0.0.1:48197",
        node_token="test-node-token",
        allowed_roots=(tmp_path,),
        direct=DirectTransferConfig(enabled=False),
    )
    adapter = MockAdapter(config.allowed_roots)
    send_prompt = AsyncMock(side_effect=ValueError("adapter prompt failed"))
    monkeypatch.setattr(adapter, "send_prompt", send_prompt)
    daemon = AgentNodeDaemon(config, adapters={"mock": adapter}, staging_dir=tmp_path / "stage")
    ws = Mock(send=AsyncMock())

    asyncio.run(daemon.handle_command(ws, {
        "type": "prompt.send",
        "provider": "mock",
        "sessionId": "session-1",
        "requestId": "prompt-1",
        "text": "hello",
    }))

    send_prompt.assert_awaited_once()
    ws.send.assert_awaited_once()
    frame = json.loads(ws.send.await_args.args[0])
    assert frame["type"] == "Failed"
    assert frame["code"] == "node_execution_error"
    assert frame["requestId"] == "prompt-1"
    assert frame["message"] == "adapter prompt failed"
