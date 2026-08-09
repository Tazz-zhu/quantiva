#!/usr/bin/env python3
"""?? Web ?????? http://127.0.0.1:8686??"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn

from quant.web.server import app


def main() -> None:
    parser = argparse.ArgumentParser(description="?????? Web ???")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8686)
    parser.add_argument("--reload", action="store_true", help="????????")
    parser.add_argument("--no-open", action="store_true", help="????????")
    parser.add_argument("--prod", action="store_true", help="?????0.0.0.0 + ?????????")
    parser.add_argument("--ssl-certfile", default=None, help="TLS ??????? HTTPS?")
    parser.add_argument("--ssl-keyfile", default=None, help="TLS ????")
    args = parser.parse_args()
    if args.prod:
        args.host = "0.0.0.0"
        args.no_open = True
    url = f"http://{args.host}:{args.port}"
    print(f"Quantiva ?????: {url}  (prod={args.prod})")
    if not args.no_open:
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload,
                access_log=False if args.prod else True,
                ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile)


if __name__ == "__main__":
    main()
