"""Private stdin control channel from the Windows tray; stdout contains only the port."""
import contextlib
import os
from pathlib import Path
import subprocess
import sys
import threading

from .gateway import serve
from .store import Store


def main():
    store = Store(os.environ.get("WIREBRAIN_HOME") or Path.home()/".wirebrain")
    output = sys.stdout
    def ready(server):
        print(server.server_port, file=output, flush=True)
        def control():
            worker = None
            try:
                for line in sys.stdin:
                    action = line.strip()
                    if action == "pause":
                        store.capture_stop(True)
                    elif action == "record" and not store.capture_state().get("running") and (
                            worker is None or worker.poll() is not None):
                        args = [sys.executable, "-m", "wirebrain", "--home", str(store.home),
                                "capture", "--local-capture"]
                        if not (store.home/"local-capture-authorized").exists():
                            args.append("--install-ca")
                        with (store.home/"capture-runtime.log").open("ab") as log:
                            worker = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                store.capture_stop(True)
                server.shutdown()
                if worker is not None:
                    worker.wait()
        threading.Thread(target=control, name="desktop-owner", daemon=False).start()
    with contextlib.redirect_stdout(sys.stderr):
        serve(store, {"dashboard_port":0,"enable_api_gateway":False}, on_listening=ready)


if __name__ == "__main__":
    main()
