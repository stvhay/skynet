#!/usr/bin/env python3
"""Fake Claude CLI for integration testing.

Standalone script (no mesh-server/agent-runtime imports) that simulates
a Claude CLI subprocess: reads env + MCP config, optionally sends a reply
to the controller, then calls the shutdown endpoint and exits.
"""

import argparse
import json
import os
import sys
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", default=None)
    parser.add_argument("--mcp-config", required=True)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--thinking-budget", type=int, default=None)
    args = parser.parse_args()

    agent_uuid = os.environ["MESH_AGENT_ID"]

    # Read MCP config to get server URL
    with open(args.mcp_config) as f:
        mcp_config = json.load(f)
    server_url = mcp_config["mcpServers"]["mesh"]["url"]
    base_url = server_url.rsplit("/mcp", 1)[0]

    headers = {"Content-Type": "application/json"}

    # Send reply if prompt was given
    if args.prompt:
        spawner_uuid = os.environ.get("MESH_SPAWNER_UUID", "controller")
        data = json.dumps({
            "to": spawner_uuid,
            "message": f"fake-agent-reply: {agent_uuid} processed prompt",
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/send", data=data, headers=headers, method="POST"
        )
        try:
            urllib.request.urlopen(req)
        except Exception as exc:
            print(f"fake_claude: send failed: {exc}", file=sys.stderr)

    # Shutdown
    req = urllib.request.Request(
        f"{base_url}/api/agents/{agent_uuid}/shutdown",
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
    except Exception as exc:
        print(f"fake_claude: shutdown failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
