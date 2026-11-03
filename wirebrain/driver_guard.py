"""One per-user guardian for Wirebrain's Windows process-capture driver."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager


def service_image():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\WinDivert") as key:
            path = winreg.QueryValueEx(key, "ImagePath")[0]
    except FileNotFoundError:
        return None
    return Path(path.removeprefix("\\??\\").strip('"')).resolve()


def expected_image():
    import mitmproxy_windows
    return Path(mitmproxy_windows.__file__).resolve().with_name("WinDivert64.sys")


def helper_active():
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq windows-redirector.exe",
                             "/FO", "CSV", "/NH"], capture_output=True, text=True, check=True)
    return any(row and row[0].lower() == "windows-redirector.exe"
               for row in csv.reader(result.stdout.splitlines()))


def cleanup(marker):
    if not marker.exists():
        return
    expected = expected_image()
    if json.loads(marker.read_text()) != {"image": str(expected)}:
        raise ValueError("Driver ownership record changed; manual review required.")
    for _ in range(30):
        if not helper_active():
            break
        time.sleep(.5)
    else:
        raise ValueError("Redirector still active; retained ownership record for retry.")
    image = service_image()
    if image is not None:
        if image != expected:
            raise ValueError("Another WinDivert installation is active; refusing to stop it.")
        # Only the fixed OS command receives elevation, never code from the diary.
        sc = str(Path(os.environ["SystemRoot"])/"System32"/"sc.exe")
        result = subprocess.run([sc, "stop", "WinDivert"], capture_output=True)
        if result.returncode == 5:
            shell = Path(os.environ["SystemRoot"])/"System32/WindowsPowerShell/v1.0/powershell.exe"
            subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command",
                            "$ErrorActionPreference='Stop'; $p=Start-Process -FilePath "
                            "(Join-Path $env:SystemRoot 'System32/sc.exe') -ArgumentList 'stop','WinDivert' "
                            "-WindowStyle Hidden -Verb RunAs -Wait -PassThru; exit $p.ExitCode"], check=True)
        elif result.returncode not in (0, 1060, 1062):
            raise ValueError(f"Driver stop failed ({result.returncode})")
        for _ in range(30):
            if service_image() is None:
                break
            time.sleep(.25)
        else:
            raise ValueError("Driver service is still present; cleanup requires review.")
    marker.unlink()


@contextmanager
def ownership():
    import msvcrt
    directory = Path(os.environ["LOCALAPPDATA"])/"Wirebrain"/"capture-lifecycle"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/"lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        yield directory/"driver.json"


def recover_orphan():
    """Uninstall can reclaim an owned driver even if all workers were killed."""
    marker = Path(os.environ["LOCALAPPDATA"])/"Wirebrain"/"capture-lifecycle"/"driver.json"
    if not marker.exists():
        return
    deadline = time.monotonic()+120
    while marker.exists():
        try:
            with ownership() as owned:
                cleanup(owned)
            return
        except OSError as exc:
            if time.monotonic() >= deadline or exc.errno not in (13, 36):
                raise
            time.sleep(.5)


def watch(ready):
    with ownership() as marker:
        cleanup(marker)
        if service_image() is not None or helper_active():
            raise ValueError("Another WinDivert session exists. Process capture will not take ownership.")
        tmp = marker.with_suffix(".tmp")
        tmp.write_text(json.dumps({"image":str(expected_image())}))
        tmp.replace(marker)
        try:
            ready.touch()
            sys.stdin.buffer.read(1)
        finally:
            cleanup(marker)


@contextmanager
def guard(home):
    ready = Path(home).resolve()/("driver-ready-"+uuid.uuid4().hex)
    with (ready.parent/"driver-lifecycle.log").open("ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "wirebrain.driver_guard", str(ready)],
                                stdin=subprocess.PIPE, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        deadline = time.monotonic()+90
        while not ready.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise ValueError("Driver guardian could not start. See driver-lifecycle.log.")
            time.sleep(.1)
        yield proc
    finally:
        proc.stdin.close()
        ready.unlink(missing_ok=True)
        if proc.wait(timeout=120):
            raise ValueError("Driver cleanup requires attention. See driver-lifecycle.log.")


if __name__ == "__main__":
    watch(Path(sys.argv[1]))
