from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os

MESSAGE = os.environ.get("API_MESSAGE", "assessment sessions api")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/api2", "/api2/", "/api2/health"):
            body = json.dumps({"service": "api2", "status": "ok", "message": MESSAGE}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        return

if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()
