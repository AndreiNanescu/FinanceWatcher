import asyncio
import atexit
import threading

from dotenv import load_dotenv
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

from backend.mcp_server.agent import Agent
from .data_pipeline import main as pipeline

load_dotenv(Path(__file__).resolve().parent / ".env")

app = Flask(__name__)
CORS(app)

_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True, name="agent-loop").start()


def _run(coro):
    """Block the calling (Flask worker) thread until the coroutine completes."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()

_agent = Agent()
_agent_ready = False
_agent_init_lock = threading.Lock()


def _ensure_agent() -> bool:
    global _agent_ready
    if _agent_ready:
        return True
    with _agent_init_lock:
        if _agent_ready:
            return True
        try:
            _run(_agent.initialize_tools())
            _agent_ready = True
        except Exception as exc:
            app.logger.error("Agent initialisation failed: %s", exc)
    return _agent_ready


is_updating = False
status_lock = threading.Lock()

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "")

    session_id = (data.get("session_id") or "default").strip() or "default"

    if not message:
        return jsonify({"error": "No message provided"}), 400

    if not _ensure_agent():
        return jsonify({"error": "Agent not ready — is the MCP server running?"}), 503

    try:
        response = _run(_agent.ask(message, thread_id=session_id))
    except Exception as exc:
        app.logger.error("Agent error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"response": response})


@app.route("/api/update-data", methods=["POST"])
def update_data():
    def do_update():
        global is_updating
        with status_lock:
            is_updating = True
        try:
            pipeline(
                symbols=['AAPL', 'GOOGL', 'AMZN', 'NVDA', 'TSM', 'BLK', 'RTX', 'SPY', 'JPM', 'GS', 'XOM'],
                days=1,
                max_pages=5,
            )
        finally:
            with status_lock:
                is_updating = False

    with status_lock:
        if is_updating:
            return jsonify({"message": "Update already in progress"}), 429

    threading.Thread(target=do_update).start()
    return jsonify({"message": "Update triggered"}), 202


@app.route("/api/update-status", methods=["GET"])
def update_status():
    with status_lock:
        updating = is_updating
    return jsonify({"updating": updating})


@app.route("/")
def index():
    return jsonify({"message": "Backend is running!"})


atexit.register(lambda: _run(_agent.close()) if _agent_ready else None)

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)


