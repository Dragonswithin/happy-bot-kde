"""A minimal stdio MCP server used as a child process by the test suite.

It implements just enough of the protocol for ``kde_ai_assistant.mcp_client``:
``initialize``, ``tools/list`` (paged, to exercise cursors) and ``tools/call``.
Its tools are chosen to provoke the client's edge cases:

- ``find_files``: returns JSON hits for the query; ``mode`` selects the
  output shape (``structured``, ``json_text``, ``plain_text``, ``error``).
- ``web_lookup``: a search-like tool worded as a web search.
- ``echo_env``: returns the value of one environment variable.
- ``sleep``: answers after ``seconds``, for timeout tests.
- ``crash``: exits without answering, for restart tests.

It also prints a non-JSON line on stdout and a line on stderr at start, as
real servers sometimes do, and sends a ``ping`` request to the client after
initialisation.
"""

import json
import os
import sys
import time

TOOLS = [
    {
        "name": "find_files",
        "description": "Search local files and documents by path and text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
                "mode": {"type": "string", "default": "structured"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_lookup",
        "description": "Search the web and return links.",
        "inputSchema": {
            "type": "object",
            "properties": {"q": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["q"],
        },
    },
    {
        "name": "echo_env",
        "description": "Return an environment variable.",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "sleep",
        "description": "Wait.",
        "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}, "required": ["seconds"]},
    },
    {"name": "crash", "description": "Exit.", "inputSchema": {"type": "object", "properties": {}}},
]


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def call(name, arguments):
    if name == "find_files":
        query = arguments.get("query", "")
        hits = [
            {"path": f"/tmp/fake/{query}-{index}.txt", "excerpt": f"match {index} for {query}"}
            for index in range(int(arguments.get("limit", 10)))
        ]
        payload = {"query": query, "hits": hits, "coverage": {"database_path": "/var/lib/fake/index.sqlite"}}
        mode = arguments.get("mode", "structured")
        if mode == "structured":
            return {"content": [{"type": "text", "text": "see structured"}], "structuredContent": payload}
        if mode == "json_text":
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}
        if mode == "plain_text":
            lines = [f"- {hit['path']}: {hit['excerpt']}" for hit in hits] + ["see https://example.org/help."]
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}
        return {"content": [{"type": "text", "text": "index is offline"}], "isError": True}
    if name == "web_lookup":
        return {"content": [{"type": "text", "text": json.dumps([{"url": "https://example.org/a", "title": "A"}])}]}
    if name == "echo_env":
        return {"content": [{"type": "text", "text": os.environ.get(arguments.get("name", ""), "")}]}
    if name == "sleep":
        time.sleep(float(arguments.get("seconds", 0)))
        return {"content": [{"type": "text", "text": "awake"}]}
    if name == "crash":
        sys.stderr.write("fatal: simulated crash\n")
        sys.stderr.flush()
        os._exit(3)
    return None


def main():
    print("fake server starting (this line is not JSON)", flush=True)
    sys.stderr.write("fake server stderr banner\n")
    sys.stderr.flush()
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        method, request_id = message.get("method"), message.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1"},
            }})
        elif method == "notifications/initialized":
            send({"jsonrpc": "2.0", "id": "server-ping-1", "method": "ping"})
        elif method == "tools/list":
            cursor = (message.get("params") or {}).get("cursor")
            start = int(cursor) if cursor else 0
            page = TOOLS[start:start + 2]
            result = {"tools": page}
            if start + 2 < len(TOOLS):
                result["nextCursor"] = str(start + 2)
            send({"jsonrpc": "2.0", "id": request_id, "result": result})
        elif method == "tools/call":
            params = message.get("params") or {}
            result = call(params.get("name"), params.get("arguments") or {})
            if result is None:
                send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown tool"}})
            else:
                send({"jsonrpc": "2.0", "id": request_id, "result": result})
        elif request_id is not None and method:
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "unknown method"}})


if __name__ == "__main__":
    main()
