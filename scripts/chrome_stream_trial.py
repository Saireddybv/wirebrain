"""Disposable Windows CI only: exercise Chrome and the real parser against a loopback TLS fixture."""
import json
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def run(root, worker, store, stop_at):
    from playwright.sync_api import sync_playwright

    prompt = "Wirebrain synthetic stream trial"
    release = threading.Event()
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<title>Wirebrain local fixture</title>")

        def do_POST(self):
            if self.path != "/backend-api/conversation":
                self.send_error(404)
                return
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for n in range(1, 11):
                event = {"message":{"author":{"role":"assistant"}, "content":{
                    "content_type":"text", "parts":[f"chunk {n}/10"]}}}
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                self.wfile.flush()
                if n == stop_at:
                    release.wait(45)
                    return
                time.sleep(.8)

    with ThreadingHTTPServer(("127.0.0.1",0), Fixture) as server, sync_playwright() as driver:
        (root/"fixture-port").write_text(str(server.server_port))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        browser = driver.chromium.launch(channel="chrome", args=["--disable-quic",
            "--host-resolver-rules=MAP chatgpt.com 198.51.100.17", "--disable-background-networking"])
        try:
            page = browser.new_page()
            page.goto("https://chatgpt.com/")
            if page.title() != "Wirebrain local fixture":
                raise RuntimeError("Synthetic Chrome request did not reach the intercepted fixture")
            page.evaluate("""prompt => { window.received = ''; (async () => {
              const response = await fetch('/backend-api/conversation', {method:'POST',
                headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:[
                {author:{role:'user'},content:{parts:[prompt]}}]})});
              const reader=response.body.getReader(), decoder=new TextDecoder();
              for (;;) {const part=await reader.read(); if(part.done)break;
                window.received+=decoder.decode(part.value,{stream:true});}
            })().catch(()=>{}); }""", prompt)
            expected = f"chunk {stop_at}/10"
            page.wait_for_function("text => window.received.includes(text)", arg=expected, timeout=30000)
            with store.connect() as db:
                row = db.execute("SELECT response,status FROM conversations WHERE prompt=?", (prompt,)).fetchone()
            if not row or tuple(row) != (expected, "streaming"):
                raise RuntimeError("Chrome got data but the recorder did not capture the same live chunk")
            os.kill(worker, signal.SIGTERM)
            # Start a fresh browser connection immediately, before reset or driver cleanup.
            fresh = browser.new_context()
            check = fresh.new_page()
            check.goto("https://example.com/", timeout=25000)
            if "Example Domain" not in check.title():
                raise RuntimeError("New Chrome HTTPS navigation failed after recorder kill")
            (root/"stream-proof.json").write_text(json.dumps({"chrome_and_diary":expected,
                "status_before_kill":"streaming","fresh_https_before_reset":True}))
        finally:
            release.set()
            browser.close()
            server.shutdown()
