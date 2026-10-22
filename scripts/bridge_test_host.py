"""JSON-lines backend for headless DOM tests. No HTTP server, desktop API or live credentials."""

import json
import sys
from pathlib import Path

from canvas_agent.web_bridge import Bridge
from canvas_agent.web_qa import seed

root = Path(sys.argv[1])
seed(root)
bridge = Bridge(root, qa=True)
for line in sys.stdin:
    try:
        request = json.loads(line)
        result = bridge.invoke(request["method"], request["params"])
    except Exception:
        result = {"ok": False, "error": "test_protocol_error"}
    print(json.dumps(result, ensure_ascii=False), flush=True)
