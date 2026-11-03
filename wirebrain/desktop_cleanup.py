"""NSIS pre-uninstall: stop capture, remove our user root, retain the diary."""
import os
from pathlib import Path
import ssl
import sys
import time
import winreg

from .capture import remove_ca
from .driver_guard import recover_orphan
from .store import Store


def main():
    home = Path.home()/".wirebrain"
    if (home/"memory.sqlite3").exists():
        store = Store(home)
        store.capture_stop(True)
        deadline = time.monotonic()+120
        while store.capture_state().get("running"):
            if time.monotonic() > deadline:
                raise RuntimeError("Recorder did not pause")
            time.sleep(.25)
    recover_orphan()
    pem = home/"certificates/mitmproxy-ca-cert.pem"
    if pem.is_file():
        der = ssl.PEM_cert_to_DER_cert(pem.read_text(encoding="ascii"))
        def trusted():
            return any(entry[0] == der for entry in ssl.enum_certificates("ROOT"))
        if trusted():
            remove_ca(home)
        if trusted():
            raise RuntimeError("Capture root remains trusted")
    (home/"local-capture-authorized").unlink(missing_ok=True)
    # Remove only a startup entry pointing at this installation.
    exe = Path(sys.executable).resolve().parents[1]/"wirebrain-desktop.exe"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0,winreg.KEY_READ|winreg.KEY_SET_VALUE) as key:
            for name in ("Wirebrain","wirebrain-desktop"):
                try: value,_ = winreg.QueryValueEx(key,name)
                except FileNotFoundError: continue
                if os.path.normcase(value.strip('"')) == os.path.normcase(str(exe)):
                    winreg.DeleteValue(key,name)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
