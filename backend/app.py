from flask import Flask, request, jsonify
from flask_cors import CORS
from .llm import Llama3
from .rag import ChromaMarketNews

app = Flask(__name__)
CORS(app)

chroma = ChromaMarketNews()
llm = Llama3(chroma)

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "")
    if not message:
        return jsonify({"error": "No message provided"}), 400

    response = llm.ask(message)
    return jsonify({"response": response})

@app.route("/")
def index():
    return jsonify({"message": "Backend is running!"})

if __name__ == "__main__":
    app.run(debug=True)
