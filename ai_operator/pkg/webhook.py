from flask import Flask, request, jsonify
import threading
import json
import logging
from pathlib import Path
import os

logger = logging.getLogger("ai_operator.webhook")
app = Flask(__name__)


@app.route("/alert", methods=["POST"])
def receive_alert():
    try:
        payload = request.get_json(force=True)
        # Minimal demo behavior: write the last alert to a file for the operator to pick up
        out_path = Path(os.getenv("ALERT_WEBHOOK_DUMP", "/tmp/last_alert.json"))
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # best-effort: parent may not exist or be writable
            pass
        with open(out_path, "w") as f:
            f.write(json.dumps(payload))
        logger.info("Received webhook alert and wrote to %s", out_path)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.exception("Failed to handle webhook alert")
        return jsonify({"error": str(e)}), 500


def run_webhook_server(port: int = 5001):
    # Run Flask in a background daemon thread so kopf can continue running
    def _run():
        # Disable Flask startup messages; rely on logger
        app.run(host="0.0.0.0", port=port, debug=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("Webhook server started on :%d (thread %s)", port, t.name)
