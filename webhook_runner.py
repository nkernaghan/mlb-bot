"""Tiny HTTP server that lets n8n trigger the MLB bot via HTTP request."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess
import json
import threading


class BotHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/run":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode())

            # Run bot in background thread
            threading.Thread(target=run_bot, daemon=True).start()

        elif self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready"}).encode())

        elif self.path == "/last-run":
            try:
                with open("data/last_run.json", "r") as f:
                    data = json.load(f)
            except FileNotFoundError:
                data = {"status": "no runs yet"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[webhook] {args[0]}")


def run_bot():
    """Run the MLB bot and save results."""
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("[webhook] Starting MLB bot...")
    result = subprocess.run(
        ["python", "main.py"],
        capture_output=True, text=True, timeout=600
    )

    output = result.stdout + result.stderr
    # Parse results
    import re
    done_match = re.search(r"Done\. (\d+) total predictions: (\d+) BET, (\d+) LEAN", output)
    game_match = re.search(r"Found (\d+) games", output)
    pb_synced = "PocketBase sync complete" in output

    run_data = {
        "success": result.returncode == 0,
        "games": int(game_match.group(1)) if game_match else 0,
        "total_predictions": int(done_match.group(1)) if done_match else 0,
        "bets": int(done_match.group(2)) if done_match else 0,
        "leans": int(done_match.group(3)) if done_match else 0,
        "pb_synced": pb_synced,
        "output_tail": output.split("\n")[-20:],
    }

    from datetime import datetime
    run_data["ran_at"] = datetime.now().isoformat()

    os.makedirs("data", exist_ok=True)
    with open("data/last_run.json", "w") as f:
        json.dump(run_data, f, indent=2)

    status = "SUCCESS" if run_data["success"] else "FAILED"
    print(f"[webhook] Bot finished: {status} — {run_data['bets']} BET, {run_data['leans']} LEAN")


if __name__ == "__main__":
    port = 8095
    server = HTTPServer(("127.0.0.1", port), BotHandler)
    print(f"MLB Bot webhook runner listening on http://127.0.0.1:{port}")
    print(f"  POST /run     — trigger bot run")
    print(f"  GET  /status   — health check")
    print(f"  GET  /last-run — last run results")
    server.serve_forever()
