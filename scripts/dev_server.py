"""Serveur local : sert web/ et l'agent IA sur http://localhost:8000

    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/dev_server.py
"""
import importlib.util
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Charge un fichier .env à la racine du projet (ignoré par Git), ex. : ANTHROPIC_API_KEY=sk-ant-...
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

WEB = Path(os.environ.get("WEB_DIR", Path(__file__).resolve().parent.parent / "web"))
os.environ.setdefault("AGENT_DB", str(WEB / "data" / "observatoire.duckdb"))
spec = importlib.util.spec_from_file_location("agent", Path(__file__).resolve().parent.parent / "web" / "api" / "agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path.startswith("/api/agent"):
            return agent.handler.do_POST(self)
        self.send_error(404)

    _send = agent.handler._send


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"http://localhost:{port}")
    ThreadingHTTPServer(("", port), partial(Handler, directory=str(WEB))).serve_forever()
