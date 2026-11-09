"""Run locally with a threaded WSGI server, without Flask's debugger."""

import os

from waitress import serve

from app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"FlaskGPT : http://127.0.0.1:{port}", flush=True)
    serve(app, host="127.0.0.1", port=port, threads=8)
