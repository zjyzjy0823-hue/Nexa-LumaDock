import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    text: str


def execute_task(title: str, description: str, timeout: int = 600) -> ExecutionResult:
    prompt = f"Task: {title}\n\nInstructions:\n{description}" if description else f"Task: {title}"
    command = shutil.which("openclaw")
    if command is None:
        raise RuntimeError("OpenClaw command not found")
    try:
        result = subprocess.run(
            [command, "agent", "exec", "--message-file", "-", "--json", "--timeout", str(timeout)],
            input=prompt, text=True, capture_output=True, timeout=timeout + 15, check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("OpenClaw command not found") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("OpenClaw execution timed out") from error
    except OSError as error:
        raise RuntimeError("OpenClaw unavailable") from error
    if result.returncode != 0:
        raise RuntimeError(f"OpenClaw execution failed (exit {result.returncode})")
    try:
        envelope = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise RuntimeError("OpenClaw returned invalid JSON") from error
    if not isinstance(envelope, dict) or envelope.get("ok") is not True or envelope.get("status") != "ok" or not isinstance(envelope.get("final"), str):
        raise RuntimeError("OpenClaw returned an invalid result")
    return ExecutionResult(text=envelope["final"])
