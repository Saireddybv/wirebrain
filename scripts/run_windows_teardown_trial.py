"""Windows release gate. Run explicitly from an installed capture environment.

Uses a fresh trial directory per run. Stream trials target Chrome on a disposable runner.
Windows prompts for redirector/driver permissions. Logs and snapshots stay local.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

from wirebrain import capture
from wirebrain.store import Store


def until(predicate, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.25)
    raise TimeoutError("Release gate timed out")


def snapshot(path, baseline=None):
    script = Path(__file__).with_name("check_windows_trial.ps1")
    args = [os.environ.get("WIREBRAIN_TRIAL_PWSH") or shutil.which("pwsh") or "powershell", "-NoProfile", "-File", str(script), "-OutputFile", str(path)]
    if baseline:
        args.extend(["-Baseline", str(baseline)])
    subprocess.run(args, check=True)


def cycle(root, scenario):
    from wirebrain.driver_guard import service_image, helper_active
    if helper_active() or service_image() is not None:
        raise RuntimeError("Run on a test PC with no existing redirector or WinDivert driver.")
    root.mkdir(parents=True)
    base = root/"before.json"
    snapshot(base)
    if json.loads(base.read_text(encoding="utf-8-sig")).get("ProxyEnable") not in (0, None):
        raise RuntimeError("Release gate requires a clean runner with manual proxy off")
    stream = scenario.startswith("chrome-stream-")
    if stream and os.environ.get("WIREBRAIN_DISPOSABLE_RUNNER") != "1":
        raise RuntimeError("Chrome stream trials require a dedicated disposable Windows runner")
    probe = root/("wbtrial-"+uuid.uuid4().hex[:10]+".exe")
    shutil.copy2(Path(os.environ["SystemRoot"])/"System32"/"curl.exe", probe)
    home = root/"diary"
    store = Store(home)
    with (root/"capture.log").open("wb") as log:
        controller = subprocess.Popen([sys.executable, __file__, "--worker", str(root), "chrome.exe" if stream else probe.name],
                                      stdout=log, stderr=log)
        try:
            def ready():
                if controller.poll() is not None:
                    raise RuntimeError("Capture startup failed. Inspect capture.log")
                return store.capture_state().get("running")
            until(ready)
            snapshot(root/"during.json")
            during = json.loads((root/"during.json").read_text(encoding="utf-8-sig"))
            before = json.loads(base.read_text(encoding="utf-8-sig"))
            for key in ("ProxyEnable","ProxyServer","ProxyOverride","AutoConfigURL","DefaultConnectionSettings","SavedLegacySettings"):
                if before[key] != during[key]:
                    raise RuntimeError(f"Proxy setting changed during recording: {key}")
            if scenario == "pause":
                store.capture_stop(True)
            elif scenario == "controller-kill":
                os.kill(int((root/"controller.pid").read_text()), signal.SIGTERM)
            elif stream:
                from chrome_stream_trial import run
                run(root, int(next(home.glob("local-ready-*")).read_text()), store, int(scenario.rsplit("-",1)[1]))
            else:
                worker = int(next(home.glob("local-ready-*")).read_text())
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1",0))
                    sock.listen()
                    sock.settimeout(15)
                    probe_proc = subprocess.Popen([str(probe), "--no-buffer", "--noproxy", "*", "--max-time", "10",
                                                   f"https://127.0.0.1:{sock.getsockname()[1]}"],
                                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    try:
                        with sock.accept()[0] as conn:
                            conn.settimeout(10)
                            if conn.recv(1) != b"\x16":
                                raise ValueError("Expected a TLS ClientHello")
                            (root/"kill-time.txt").write_text(str(time.time()))
                            os.kill(worker, signal.SIGTERM)
                    finally:
                        probe_proc.wait(timeout=12)
            controller.wait(timeout=140)
            until(lambda: not helper_active() and service_image() is None)
            subprocess.run([str(probe),"--fail","--noproxy","*","--max-time","20","https://example.com/"],
                           stdout=subprocess.DEVNULL, check=True)
        finally:
            store.capture_stop(True)
            controller.wait(timeout=140)
            subprocess.run([sys.executable, "-m", "wirebrain", "--home", str(home),
                            "capture-reset", "--remove-ca"], check=True)
            snapshot(root/"removed.json", base)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        root = Path(sys.argv[2])
        (root/"controller.pid").write_text(str(os.getpid()))
        capture.LOCAL_MODE = "local:"+sys.argv[3]
        if sys.argv[3] == "chrome.exe":
            # Trust only the fixture CA for the recorder's upstream connection.
            cmd = capture.command
            capture.command = lambda *a, **kw: cmd(*a, **kw) + ["--set",
                "ssl_verify_upstream_trusted_ca=" + str(root/"diary"/"certificates"/"mitmproxy-ca-cert.pem")]
        capture.run(root/"diary", install_ca=True, local_capture=True)
    else:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument("directory",type=Path)
        cases = ("pause","recorder-kill","controller-kill","recorder-kill-repeat",
                 "chrome-stream-1","chrome-stream-5","chrome-stream-9")
        parser.add_argument("--scenario",choices=cases)
        args=parser.parse_args()
        root=args.directory.resolve()
        root.mkdir(exist_ok=False)
        for scenario in ([args.scenario] if args.scenario else cases):
            cycle(root/scenario, scenario)
            print(scenario, "passed", flush=True)
