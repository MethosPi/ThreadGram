from __future__ import annotations

import argparse
import os

import uvicorn

from agentgram.app import create_app
from agentgram.bridge import create_stdio_bridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentgram")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the AgentGram HTTP API and MCP server.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)

    stdio = subparsers.add_parser("stdio", help="Run the local stdio bridge that forwards to a hosted AgentGram API.")
    stdio.add_argument("--server-url", required=True, help="Hosted AgentGram MCP endpoint, for example https://api.example.com/mcp")
    stdio.add_argument("--api-key", help="AgentGram bearer token. Falls back to AGENTGRAM_API_KEY.")

    return parser


def run_stdio(server_url: str, api_key: str) -> None:
    bridge = create_stdio_bridge(server_url=server_url, api_key=api_key)
    bridge.run()


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run(create_app(), host=args.host, port=args.port)
        return

    if args.command == "stdio":
        api_key = args.api_key or os.getenv("AGENTGRAM_API_KEY")
        if not api_key:
            parser.error("An API key is required. Use --api-key or AGENTGRAM_API_KEY.")
        run_stdio(args.server_url, api_key)
        return

    parser.error("Unknown command.")
