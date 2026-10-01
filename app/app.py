import os
import socket

from flask import Flask, render_template
from waitress import serve

app = Flask(__name__)


@app.route("/")
def home():
    return render_template(
        "index.html",
        sample=os.environ.get("DEMO_SAMPLE", "unknown"),
        hostname=socket.gethostname(),
    )


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
