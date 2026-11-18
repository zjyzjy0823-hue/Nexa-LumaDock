"""Studiolo Agent Node 命令行入口。"""

import argparse
import asyncio
import logging

from .config import load_node_config
from .daemon import AgentNodeDaemon


def main() -> None:
    parser = argparse.ArgumentParser(description="Studiolo Multi-Device Agent Node")
    parser.add_argument("--config", default=None, help="Path to config.json (optional if env vars are set)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [agent-node] %(levelname)s %(message)s")
    config = load_node_config(args.config)
    daemon = AgentNodeDaemon(config)
    asyncio.run(daemon.run_forever())


if __name__ == "__main__":
    main()
