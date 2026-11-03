"""Exercise the installed WebView2 controls on a disposable GitHub Windows runner."""
import os
from pathlib import Path
import subprocess
import sys
import time

import json
import urllib.request

from pywinauto import Desktop
import win32con
import win32gui
import win32process


def answer_dialog(pid, button):
    for _ in range(100):
        matches = []
        def visit(window, unused):
            if (win32process.GetWindowThreadProcessId(window)[1] == pid
                    and win32gui.GetWindowText(window) == "Start recording?"):
                matches.append(window)
        win32gui.EnumWindows(visit, None)
        if matches:
            win32gui.PostMessage(matches[0], win32con.WM_COMMAND, button, 0)
            return
        time.sleep(.1)
    raise RuntimeError("The installed diary did not open the native recording prompt")


def run(pid, diary_port, installed_python):
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("Installed capture checks require a disposable hosted runner")
    repo = Path(__file__).resolve().parents[1]
    # Use the bundled capture dependency and the existing runner-only fixture recipe.
    setup = """
from pathlib import Path
import sys
sys.path.insert(0,sys.argv[1])
from run_windows_teardown_trial import hosted_fixture_trust
der=hosted_fixture_trust(Path.home()/'.wirebrain')
if not der: raise RuntimeError('Missing fixture trust')
Path(sys.argv[2]).write_bytes(der)
"""
    der_path = Path(os.environ["RUNNER_TEMP"])/"desktop-fixture.der"
    window = Desktop(backend="uia").window(process=pid,title="Wirebrain")
    def button(name):
        control = window.child_window(title=name,control_type="Button",found_index=0)
        control.wait("exists enabled visible",timeout=90)
        return control.wrapper_object()
    api = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{diary_port}"
    def running():
        with api.open(base+"/api/stats",timeout=5) as response:
            return json.load(response)["capture"]["running"]
    button("Start recording").invoke()
    answer_dialog(pid, win32con.IDCANCEL)
    if running():
        raise RuntimeError("Cancelling started recording")
    try:
        subprocess.run([installed_python,"-I","-c",setup,str(repo/"scripts"),str(der_path)],check=True)
        button("Start recording").invoke()
        answer_dialog(pid, win32con.IDOK)
        stop = button("Stop recording")
        if not running():
            raise RuntimeError("Recorder is not running")
        stop.invoke()
        button("Start recording")
        if running():
            raise RuntimeError("Recorder did not stop")
    finally:
        req=urllib.request.Request(base+"/api/capture/stop",data=b"{}",headers={"Content-Type":"application/json"})
        with api.open(req,timeout=5): pass
        if der_path.exists():
            cleanup = "from wirebrain.windows_certificates import remove_root; from pathlib import Path; import sys; remove_root(Path(sys.argv[1]).read_bytes(),'LocalMachine')"
            subprocess.run([installed_python,"-I","-c",cleanup,str(der_path)],check=True)
            der_path.unlink()


if __name__ == "__main__":
    run(int(sys.argv[1]),int(sys.argv[2]),sys.argv[3])
