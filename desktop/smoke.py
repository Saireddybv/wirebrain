"""Verify the staged interpreter serves the real diary and stops on shell EOF, without capture."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request

runtime = Path(__file__).resolve().parent/"src-tauri/runtime/python.exe"
with tempfile.TemporaryDirectory() as home:
    proc = subprocess.Popen([str(runtime),"-I","-u","-m","wirebrain.desktop"],
                            stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                            env={**os.environ,"WIREBRAIN_HOME":home})
    try:
        port = int(proc.stdout.readline())
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with client.open(f"http://127.0.0.1:{port}/",timeout=5) as page:
            if b"Wirebrain" not in page.read():
                raise RuntimeError("Wrong diary")
        with client.open(f"http://127.0.0.1:{port}/api/stats",timeout=5) as result:
            if json.load(result)["capture"]["running"]:
                raise RuntimeError("Capture unexpectedly active on first launch")
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/capture/start",data=b"{}",
                                         headers={"Content-Type":"application/json"})
        try:
            client.open(request,timeout=5)
        except urllib.error.HTTPError as exc:
            if exc.code != 400 or "tray" not in json.load(exc)["error"]:
                raise
        else:
            raise RuntimeError("The web page cannot enroll the user root")
        proc.stdin.close()
        if proc.wait(timeout=15) or (Path(home)/"certificates").exists():
            raise RuntimeError("Launching the diary must not enable capture")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
