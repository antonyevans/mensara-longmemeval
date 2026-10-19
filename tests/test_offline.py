"""Offline checks: no Mind, model or network needed.  python -m unittest discover tests"""

import hashlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from lme_mind import dataset, mind as minds
from lme_mind.mcp import Mind
from lme_mind.rubric import get_anscheck_prompt
from lme_mind.summary import summarize, wilson

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "2026-10-17-m36"


class Rubric(unittest.TestCase):
    # sha256 prefixes of the official function's output for ("Q?", "A.", "R."), checked
    # against src/evaluation/evaluate_qa.py in xiaowu0162/LongMemEval on 2026-10-19.
    EXPECTED = {"single-session-user": "66896bfd8f9aa8fd", "multi-session": "66896bfd8f9aa8fd",
                "single-session-assistant": "66896bfd8f9aa8fd",
                "temporal-reasoning": "2c6e336f0319b773", "knowledge-update": "3d614586a71dc7c2",
                "single-session-preference": "f1cfd746eafcdac8"}

    def test_prompts_match_official(self):
        for kind, want in self.EXPECTED.items():
            got = hashlib.sha256(get_anscheck_prompt(kind, "Q?", "A.", "R.").encode()).hexdigest()
            self.assertEqual(got[:16], want, kind)
        abstain = get_anscheck_prompt("multi-session", "Q?", "A.", "R.", abstention=True)
        self.assertEqual(hashlib.sha256(abstain.encode()).hexdigest()[:16], "059b12ca3ff08641")


class Render(unittest.TestCase):
    def test_session_file_format(self):
        row = {"haystack_session_ids": ["b", "a"],
               "haystack_dates": ["2023/05/27 (Sat) 18:42", "2023/05/13 (Sat) 09:10"],
               "haystack_sessions": [[{"role": "user", "content": "Second"}],
                                     [{"role": "user", "content": "First\r\nline"},
                                      {"role": "assistant", "content": "Reply"}]]}
        files = dataset.sessions(row)
        self.assertEqual([n for n, _ in files], ["session-000.md", "session-001.md"])
        self.assertEqual(files[0][1], (
            '---\npromotion: approved\nstatus: active\ncreated: "2023-05-13"\n'
            'source: "imported conversation history"\nimportance: "medium"\nttl: "never"\n'
            'protected: false\ntags: ["conversation-history"]\nsource_session_slot: 0\n---\n\n'
            "# Imported conversation session 000\n\nOriginal session time: 2023/05/13 (Sat) 09:10\n\n"
            "**user:**\n\nFirst\nline\n\n**assistant:**\n\nReply\n"))


class Summary(unittest.TestCase):
    def test_published_numbers(self):
        rows = [json.loads(l) for l in (RESULTS / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
        recs = [{"question_id": r["question_id"], "question_type": r["question_type"],
                 "correct": r["autoeval_label"]} for r in rows]
        untuned = set(json.loads((RESULTS / "untuned-question-ids.json").read_text()))
        got = summarize(recs, untuned)
        published = json.loads((RESULTS / "summary.json").read_text())
        self.assertEqual(got["ALL"], published["ALL"])
        self.assertEqual(got["untuned"]["correct"], 95)
        for kind in ("multi-session", "temporal-reasoning", "knowledge-update", "abstention"):
            self.assertEqual(got[kind], published[kind], kind)

    def test_wilson(self):
        self.assertEqual(wilson(472, 500), [92.0, 96.1])


class _Fake(BaseHTTPRequestHandler):
    """A two-tool MCP server: replies as SSE to tools/call, JSON otherwise."""
    files = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.headers["Authorization"] == "Bearer t0k"
        if "id" not in msg:
            self.send_response(202)
            self.end_headers()
            return
        if msg["method"] == "initialize":
            result, sse = {"protocolVersion": "2025-06-18", "capabilities": {}}, False
        else:
            name, args = msg["params"]["name"], msg["params"]["arguments"]
            if name == "propose_write":
                for c in args["changes"]:
                    if c["op"] == "delete":
                        self.files.pop(c["path"], None)
                    else:
                        self.files[c["path"]] = c["content"]
                data = {"ok": True, "status": "applied", "proposal_id": "p1"}
            else:
                data = {"ok": True, "files": [{"path": p, "memory": {"revision": "r"}}
                                              for p in sorted(self.files)]}
            result, sse = {"content": [{"type": "text", "text": json.dumps(data)}]}, True
        body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        self.send_response(200)
        self.send_header("Mcp-Session-Id", "s1")
        self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
        self.end_headers()
        self.wfile.write((f"event: message\ndata: {body}\n\n" if sse else body).encode())


class Client(unittest.TestCase):
    def test_import_and_clear_round_trip(self):
        server = HTTPServer(("127.0.0.1", 0), _Fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            m = Mind(f"http://127.0.0.1:{server.server_port}/mcp", "t0k")
            minds.import_sessions(m, "h", [("session-000.md", "a"), ("session-001.md", "b")])
            self.assertEqual(sorted(_Fake.files), ["h/session-000.md", "h/session-001.md"])
            minds.clear(m, "h")
            self.assertEqual(_Fake.files, {})
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
