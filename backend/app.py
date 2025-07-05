import threading

from flask import Flask, request, jsonify
from flask_cors import CORS
from backend.llm import Llama3
from backend.data import ChromaClient
from .data_pipeline import main as pipeline

app = Flask(__name__)
CORS(app)

chroma = ChromaClient()
llm = Llama3(chroma)

is_updating = False
status_lock = threading.Lock()
llm_lock = threading.Lock()

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "")
    if not message:
        return jsonify({"error": "No message provided"}), 400

    with llm_lock:
        response = llm.ask(message)

    return jsonify({"response": response})

@app.route("/api/update-data", methods=["POST"])
def update_data():
    def do_update():
        global chroma, llm, is_updating
        with status_lock:
            is_updating = True
        try:
            pipeline(
                symbols=['AAPL', 'GOOGL', 'AMZN', 'NVDA', 'TSM', 'BLK', 'RTX', 'SPY', 'JPM', 'GS', 'XOM'],
                days=1,
                max_pages=5,
                chroma_obj=chroma
            )
            with llm_lock:
                llm = Llama3(chroma)
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

if __name__ == "__main__":
    app.run(debug=True)

