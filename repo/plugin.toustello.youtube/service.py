
import json
import secrets
import socket
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import xbmc
import xbmcaddon


ADDON = xbmcaddon.Addon()

STATE = {
    "server": None,
    "pin": None,
    "attempts": 0,
    "expires": 0,
    "timer": None,
}

LOCK = threading.Lock()
CONTROL_PORT = 8766


def log(message):
    xbmc.log("[TOUSTELLO TRANSFER] " + str(message), xbmc.LOGINFO)


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def stop_transfer():
    with LOCK:
        server = STATE["server"]
        timer = STATE["timer"]

        STATE["server"] = None
        STATE["pin"] = None
        STATE["attempts"] = 0
        STATE["expires"] = 0
        STATE["timer"] = None

    if timer:
        timer.cancel()

    if server:
        threading.Thread(
            target=server.shutdown,
            daemon=True
        ).start()

        server.server_close()

        log("Temporary transfer server stopped")


class UploadHandler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/key":
            self.send_json(404, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length <= 0 or length > 8192:
                self.send_json(400, {"error": "Invalid request"})
                return

            data = json.loads(
                self.rfile.read(length).decode("utf-8")
            )

            pin = str(data.get("pin", ""))
            api_key = str(data.get("api_key", "")).strip()

        except Exception:
            self.send_json(400, {"error": "Invalid JSON"})
            return

        with LOCK:
            valid = (
                STATE["server"] is not None
                and time.time() < STATE["expires"]
                and STATE["pin"] is not None
                and secrets.compare_digest(
                    pin,
                    STATE["pin"]
                )
            )

            if not valid:
                STATE["attempts"] += 1
                attempts = STATE["attempts"]
            else:
                attempts = 0

        if not valid:
            self.send_json(403, {
                "error": "Invalid PIN",
                "attempts_remaining": max(0, 5 - attempts)
            })

            if attempts >= 5:
                threading.Thread(
                    target=stop_transfer,
                    daemon=True
                ).start()

            return

        if not api_key or len(api_key) > 256:
            self.send_json(400, {"error": "Invalid API key"})
            return

        try:
            ADDON.setSetting("youtube_api_key", api_key)
        except Exception:
            self.send_json(500, {"error": "Could not save API key"})
            return

        self.send_json(200, {
            "success": True,
            "message": "API key saved successfully"
        })

        log("API key successfully saved")

        threading.Timer(
            1,
            stop_transfer
        ).start()


class ControlHandler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/start":
            self.send_error(404)
            return

        try:
            with LOCK:
                active = STATE["server"] is not None

            if not active:
                pin = "{:06d}".format(
                    secrets.randbelow(1000000)
                )

                server = ThreadingHTTPServer(
                    ("0.0.0.0", 0),
                    UploadHandler
                )

                server.daemon_threads = True

                timer = threading.Timer(
                    180,
                    stop_transfer
                )

                with LOCK:
                    STATE["server"] = server
                    STATE["pin"] = pin
                    STATE["attempts"] = 0
                    STATE["expires"] = time.time() + 180
                    STATE["timer"] = timer

                threading.Thread(
                    target=server.serve_forever,
                    daemon=True
                ).start()

                timer.start()

                log("Temporary transfer server started")

            with LOCK:
                server = STATE["server"]
                pin = STATE["pin"]

            ip = get_local_ip()

            if ip.startswith("127."):
                stop_transfer()
                raise Exception("No usable network connection")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            self.wfile.write(json.dumps({
                "ip": ip,
                "port": server.server_address[1],
                "pin": pin,
                "expires": 180
            }).encode("utf-8"))

        except Exception as error:
            log("Start error: " + str(error))
            self.send_error(500)


def main():
    server = ThreadingHTTPServer(
        ("127.0.0.1", CONTROL_PORT),
        ControlHandler
    )

    server.timeout = 1

    log("Local control server running")

    monitor = xbmc.Monitor()

    try:
        while not monitor.abortRequested():
            server.handle_request()
    finally:
        stop_transfer()
        server.server_close()


if __name__ == "__main__":
    main()
