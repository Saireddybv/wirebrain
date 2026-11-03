"""Private stdin control channel from the Windows tray; stdout contains only the port."""
import contextlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .cli import DEFAULTS

from .gateway import serve
from .store import Store


class Recorder:
    """Own at most one recorder. A pause during Windows onboarding stays pending."""
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.worker = None
        self.cancel = None
        self.closed = False

    def start(self, consent=False):
        with self.lock:
            if self.closed:
                raise ValueError("Wirebrain is closing.")
            if self.worker is not None and self.worker.poll() is None:
                return {"ok":True}
            if self.store.capture_state().get("running"):
                return {"ok":True}
            authorized = (self.store.home/"local-capture-authorized").exists()
            if not authorized and not consent:
                raise ValueError("Open the Wirebrain tray menu and choose Turn on recording to approve first-time setup.")
            args = [sys.executable,"-I","-m","wirebrain","--home",str(self.store.home),"capture","--local-capture"]
            if not authorized:
                args.append("--install-ca")
            self.store.capture_state({"running":False,"starting":True,"heartbeat":time.time()})
            with (self.store.home/"capture-runtime.log").open("ab") as log:
                self.worker = subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,
                    env={**os.environ,"WIREBRAIN_DESKTOP_ENROLL":"1"},
                    stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            self.cancel = threading.Event()
            worker, cancel = self.worker, self.cancel
            def watch():
                while worker.poll() is None:
                    if cancel.is_set():
                        self.store.capture_stop(True)
                    time.sleep(.25)
                with self.lock:
                    if self.worker is worker and worker.returncode:
                        self.store.capture_state({"running":False,"starting":False,
                            "error":"Recording did not start or cleanup needs attention. Check capture-runtime.log."})
            threading.Thread(target=watch, daemon=False).start()
            return {"ok":True}

    def pause(self, closing=False):
        with self.lock:
            self.closed |= closing
            if self.cancel:
                self.cancel.set()
            if not closing or (self.worker and self.worker.poll() is None):
                self.store.capture_stop(True)

    def stopping(self):
        with self.lock:
            return bool(self.cancel and self.cancel.is_set() and self.worker and self.worker.poll() is None)


def main():
    store = Store(os.environ.get("WIREBRAIN_HOME") or Path.home()/".wirebrain")
    recorder = Recorder(store)
    output = sys.stdout
    def ready(server):
        print(server.server_port, file=output, flush=True)
        def control():
            try:
                for line in sys.stdin:
                    action = line.strip()
                    if action == "pause":
                        recorder.pause()
                    elif action == "record":
                        recorder.start(consent=True)
            finally:
                recorder.pause(closing=True)
                server.shutdown()
        threading.Thread(target=control, name="desktop-owner", daemon=False).start()
    with contextlib.redirect_stdout(sys.stderr):
        serve(store, {**DEFAULTS,"dashboard_port":0,"enable_api_gateway":False,
              "desktop_recorder":recorder}, on_listening=ready)


if __name__ == "__main__":
    main()
