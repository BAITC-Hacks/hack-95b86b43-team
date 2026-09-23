"""Local launcher: bind once, reuse this API, never kill a foreign process."""

import argparse
import json
import socket
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def is_our_server(port: int) -> bool:
    opener = build_opener(ProxyHandler({}))
    try:
        def get(path):
            with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                return json.load(response)
        health = get("/health")
        schema = get("/openapi.json")
        return health.get("status") == "ok" and schema.get("info", {}).get("title") == "HACKALEM procurement"
    except (URLError, OSError, ValueError, AttributeError):
        return False


def serve(port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            if is_our_server(port):
                print(f"Backend already running: http://127.0.0.1:{port}/", flush=True)
                return 0
            print(f"Cannot bind port {port}: {exc}. Another service may own it. "
                  "Use --port 8001; no processes were stopped.", flush=True)
            return 1
        import uvicorn
        listener.listen(128)
        print(f"Backend: http://127.0.0.1:{port}/ | Stop: Ctrl+C", flush=True)
        server = uvicorn.Server(uvicorn.Config("backend.main:app", host="127.0.0.1", port=port))
        # Pass the bound socket so there is no check-then-bind race.
        server.run(sockets=[listener])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        return serve(args.port)
    except ModuleNotFoundError as exc:
        print(f"Missing dependency {exc.name}. Install with: python -m pip install -e \".[dev]\"")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
