"""A minimal MCP client for a Mensara Mind over Streamable HTTP, standard library only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"


class MindError(RuntimeError):
    """A tool call that failed or returned ok: false."""


class Mind:
    def __init__(self, url: str, token, timeout: float = 300.0):
        """``token`` is a string, or a callable ``token(force_refresh: bool) -> str``."""
        self.url, self.timeout = url, timeout
        self._token = token if callable(token) else (lambda force=False: token)
        self.session: str | None = None
        self._id = 0
        self._call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                  "clientInfo": {"name": "mensara-longmemeval", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, payload: dict, retried: bool = False):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "Authorization": f"Bearer {self._token(retried)}",
                   "MCP-Protocol-Version": PROTOCOL}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, json.dumps(payload).encode("utf-8"), headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self.session = resp.headers.get("Mcp-Session-Id") or self.session
                body = resp.read().decode("utf-8")
                kind = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and not retried:
                return self._post(payload, retried=True)
            raise MindError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
        if not body.strip():
            return None
        if "text/event-stream" in kind:
            # A single response arrives as one or more `data:` lines; keep the JSON-RPC reply.
            replies = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]
            replies = [r for r in replies if "id" in r]
            return replies[-1] if replies else None
        return json.loads(body)

    def _call(self, method: str, params: dict):
        self._id += 1
        reply = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        if reply is None or "error" in reply:
            raise MindError(f"{method}: {reply and reply.get('error')}")
        return reply["result"]

    def tool(self, name: str, **arguments):
        """Call one tool and return its decoded JSON result."""
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        try:
            data = json.loads(text) if text else result.get("structuredContent")
        except ValueError:
            data = {"ok": False, "error": text}
        if result.get("isError") or (isinstance(data, dict) and data.get("ok") is False):
            raise MindError(f"{name}: {str(data)[:500]}")
        return data
