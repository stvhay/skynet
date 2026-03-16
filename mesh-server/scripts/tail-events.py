#!/usr/bin/env python3
"""Live tail of mesh event log with colored output."""

import json
import os
import sys
import time

COLORS = {
    "AgentRegistered": "\033[32m",   # green
    "AgentDeregistered": "\033[31m", # red
    "MessageEnqueued": "\033[36m",   # cyan
    "MessageDrained": "\033[33m",    # yellow
}
RESET = "\033[0m"
DIM = "\033[2m"

def fmt(e):
    t = e["type"]
    c = COLORS.get(t, "")
    ts = time.strftime("%H:%M:%S", time.localtime(e.get("timestamp", 0)))

    if t == "AgentRegistered":
        return f"{c}+ REGISTER{RESET}  {e['uuid'][:12]}"
    elif t == "AgentDeregistered":
        return f"{c}- SHUTDOWN{RESET}  {e['uuid'][:12]}"
    elif t == "MessageEnqueued":
        fr = e["from_uuid"][:8]
        to = e["to_uuid"][:8]
        msg = (e.get("message") or "")[:120]
        return f"{c}> MSG {fr}\u2192{to}{RESET}: {msg}"
    elif t == "MessageDrained":
        return f"{DIM}  drained{RESET}"
    else:
        return f"  {t}: {json.dumps(e)[:80]}"

def tail(path):
    # Print existing events
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.strip():
                    print(f"{DIM}{fmt(json.loads(line))}")
        print(f"{RESET}--- live tail ---")

    # Follow new events
    with open(path) as f:
        f.seek(0, 2)  # end of file
        while True:
            line = f.readline()
            if line.strip():
                e = json.loads(line)
                ts = time.strftime("%H:%M:%S", time.localtime(e.get("timestamp", 0)))
                print(f"{DIM}{ts}{RESET} {fmt(e)}")
            else:
                time.sleep(0.2)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else ".mesh/events.jsonl"
    try:
        tail(path)
    except KeyboardInterrupt:
        pass
