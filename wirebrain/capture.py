"""Optional HTTPS capture lifecycle with explicit Windows trust/proxy opt-ins."""
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import ssl
import uuid
from pathlib import Path

from .webcapture import ALLOW_HOSTS
from .store import Store
from .windows_proxy import connection_options


def executable():
    if Path(sys.executable).with_name("wirebrain-runtime").is_file():
        return sys.executable
    candidate = Path(sys.executable).with_name("mitmdump.exe" if os.name == "nt" else "mitmdump")
    found = str(candidate) if candidate.exists() else shutil.which("mitmdump")
    if not found:
        raise ValueError('Web capture needs the optional dependency: python -m pip install -e ".[capture]"')
    return found


LOCAL_MODE = "local:chrome.exe,ChatGPT.exe,claude.exe"


def command(home, port, local_capture=False):
    routing = ["--mode", LOCAL_MODE] if local_capture else ["--listen-host", "127.0.0.1", "--listen-port", str(port)]
    program = executable()
    launch = ([program, "-I", "-c", "from mitmproxy.tools.main import mitmdump; mitmdump()"]
              if program == sys.executable else [program])
    return [*launch, *routing,
            "--set", f"confdir={Path(home).resolve() / 'certificates'}",
            "--set", "flow_detail=0", "--set", "termlog_verbosity=error",
            "--set", "connection_strategy=lazy", "--allow-hosts", ALLOW_HOSTS,
            "-s", str(Path(__file__).with_name("mitm_addon.py"))]


def terminate_process(proc):
    """Windows executable/venv launchers can own child interpreters; stop the tree."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        proc.terminate()
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def notify_windows():
    wininet = ctypes.windll.Wininet
    wininet.InternetSetOptionW(0, 39, 0, 0)
    wininet.InternetSetOptionW(0, 37, 0, 0)


def set_proxy(home, port, session=None):
    if sys.platform == 'darwin':
        from .macos import set_proxy as mac_set
        return mac_set(home, port, session=session)
    import winreg
    backup = Path(home) / "proxy-backup.json"
    if backup.exists():
        raise ValueError("A previous proxy backup exists. Run wirebrain capture-reset before restarting.")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        old = {}
        for name in ("ProxyEnable", "ProxyServer", "ProxyOverride"):
            try:
                value, kind = winreg.QueryValueEx(key, name)
                old[name] = [value, kind]
            except FileNotFoundError:
                old[name] = None
        old['_connection_flags'] = connection_options()
        if session:
            old['_session'] = session
            old['_capture_server'] = f'127.0.0.1:{port}'
        backup.write_text(json.dumps(old), encoding="utf-8")
        try:
            connection_options(3, f"127.0.0.1:{port}", "localhost;127.*;<local>")
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{port}")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "localhost;127.*;<local>")
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        except OSError:
            reset_proxy(home)
            raise
    notify_windows()


def reset_proxy(home, expected_session=None):
    if sys.platform == 'darwin':
        from .macos import reset_proxy as mac_reset
        return mac_reset(home, expected_session=expected_session)
    backup = Path(home) / "proxy-backup.json"
    if not backup.exists():
        return
    if os.name != "nt":
        raise ValueError("Automatic proxy restoration supports Windows and macOS")
    import winreg
    old = json.loads(backup.read_text(encoding="utf-8"))
    session = old.pop('_session', None)
    capture_server = old.pop('_capture_server', None)
    if expected_session is not None:
        if session != expected_session:
            return  # An old guard must never restore a newer capture session.
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_READ) as key:
            try:
                enabled = winreg.QueryValueEx(key, 'ProxyEnable')[0]
                server = winreg.QueryValueEx(key, 'ProxyServer')[0]
            except FileNotFoundError:
                enabled, server = 0, ''
        if not enabled or server != capture_server:
            # Respect a proxy disabled or replaced manually after startup.
            backup.unlink()
            return
    flags = old.pop('_connection_flags', None)
    if flags is not None:
        connection_options(flags, (old.get('ProxyServer') or [''])[0], (old.get('ProxyOverride') or [''])[0])
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_WRITE) as key:
        for name, entry in old.items():
            if entry is None:
                try: winreg.DeleteValue(key, name)
                except FileNotFoundError: pass
            else:
                winreg.SetValueEx(key, name, 0, entry[1], entry[0])
    backup.unlink()
    notify_windows()


def remove_ca(home):
    if sys.platform == 'darwin':
        from .macos import remove_ca as mac_remove
        return mac_remove(Path(home)/'certificates'/'mitmproxy-ca-cert.pem')
    if os.name != "nt":
        raise ValueError("Automatic certificate removal is currently Windows-only")
    cert = Path(home) / "certificates" / "mitmproxy-ca-cert.pem"
    if cert.exists():
        der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="ascii"))
        from .windows_certificates import remove_root
        remove_root(der)
    (Path(home)/"local-capture-authorized").unlink(missing_ok=True)


def recover_proxy(home):
    """Restore an interrupted session only when its proxy is no longer listening."""
    if not (Path(home)/'proxy-backup.json').exists(): return
    state = Store(home).capture_state()
    if state.get('running'):
        raise ValueError('The recorder is still running. Pause it before restarting.')
    try:
        connection = socket.create_connection(('127.0.0.1', state.get('port', 8082)), timeout=3)
    except ConnectionRefusedError:
        reset_proxy(home)
    except OSError as exc:
        raise ValueError('Could not verify the previous recorder stopped. Try again before recovery.') from exc
    else:
        connection.close()
        raise ValueError('The previous recorder is still listening. Close it before restarting.')


def setup_needed(home):
    """Why the dashboard cannot resume recording yet, or None when it can."""
    if os.name != 'nt' and sys.platform != 'darwin': return 'Automatic recording setup supports Windows and macOS'
    cert = Path(home) / 'certificates' / 'mitmproxy-ca-cert.pem'
    if not cert.exists(): return 'Recording needs its one-time device setup first'
    der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding='ascii'))
    if os.name == 'nt' and not any(c[0] == der for c in ssl.enum_certificates('ROOT')):
        return 'Recording needs its local certificate setup first'
    if os.name == 'nt' and not (Path(home)/'local-capture-authorized').exists():
        return 'Complete process capture setup in Local setup first.'
    if sys.platform == 'darwin' and not (Path(home)/'mac-capture-authorized').exists():
        return 'Complete the one-time macOS capture setup first'
    return None


def start_background(home):
    """Resume the already-authorized recorder, without changing certificate trust."""
    store = Store(home)
    if store.capture_state().get('running'):
        if not store.capture_stop(): return {'ok':True}
        # A pause is still in flight: let that recorder exit, then start a fresh one.
        deadline = time.monotonic() + 15
        while store.capture_state().get('running') and time.monotonic() < deadline: time.sleep(.25)
        if store.capture_state().get('running'): raise ValueError('The recorder is still pausing. Try resuming again in a moment.')
    reason = setup_needed(home)
    if reason: raise ValueError(reason)
    executable()  # Check the optional runtime before accepting the request.
    if os.name != "nt":
        recover_proxy(home)
    Store(home).capture_state({'running':False, 'starting':True, 'heartbeat':time.time()})
    with (Path(home)/'capture-runtime.log').open('ab') as log:
        proc = subprocess.Popen([sys.executable,'-m','wirebrain','--home',str(Path(home).resolve()),'capture','--local-capture' if os.name == 'nt' else '--system-proxy'],
                                stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    # Reap the launcher when the recorder exits, including after dashboard pause.
    import threading
    def reap():
        code = proc.wait()
        state = Store(home).capture_state()
        if code:
            Store(home).capture_state({**state,'running':False,'starting':False,
                'error':'The recorder could not stay running. Open Local setup to check capture dependencies, or inspect capture-runtime.log.',
                'heartbeat':time.time()})
    threading.Thread(target=reap,daemon=True).start()
    return {'ok':True,'starting':True}


def prepare_process_trust(home, install_ca):
    from mitmproxy.certs import CertStore
    directory = Path(home) / "certificates"
    desktop = os.environ.get("WIREBRAIN_DESKTOP_ENROLL") == "1" and install_ca
    existed = {p.name for p in directory.glob("mitmproxy-*")} if desktop else set()
    if install_ca:
        CertStore.from_store(directory, "mitmproxy", 2048)
    cert = directory / "mitmproxy-ca-cert.pem"
    if not cert.exists():
        raise ValueError("Complete local capture certificate setup first.")
    der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="ascii"))
    if any(entry[0] == der for entry in ssl.enum_certificates("ROOT")):
        return False
    if not install_ca:
        raise ValueError("This recorder's CA is not trusted. Complete Local setup first.")
    if desktop:
        from .desktop_trust import remember
        remember(Path(home), der, existed)
    subprocess.run(["certutil", "-user", "-addstore", "Root", str(cert.resolve())],
                   check=True, capture_output=True)
    return True


def run(home, port=8082, install_ca=False, system_proxy=False, local_capture=False):
    from contextlib import nullcontext
    from .driver_guard import guard
    added_ca = False
    if local_capture:
        if os.name != "nt" or system_proxy:
            raise ValueError("Process capture requires Windows and cannot change system proxy settings.")
        if (Path(home) / "proxy-backup.json").exists():
            raise ValueError("Pause legacy capture and restore its proxy before using process capture.")
        executable()
    try:
        with guard(home) if local_capture else nullcontext() as guardian:
            if local_capture:
                added_ca = prepare_process_trust(home, install_ca)
            _run(home, port, install_ca, system_proxy, local_capture, guardian)
    except BaseException:
        if added_ca:
            remove_ca(home)
        raise


def _run(home, port, install_ca, system_proxy, local_capture, guardian=None):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if (install_ca or system_proxy) and os.name != "nt" and sys.platform != "darwin":
        raise ValueError("Automatic certificate/proxy setup supports Windows and macOS")
    if system_proxy and (Path(home) / "proxy-backup.json").exists():
        raise ValueError("Run wirebrain capture-reset to restore the previous proxy first")
    # Refuse to hijack an existing listener.
    if not local_capture:
        with socket.socket() as sock:
            if os.name != "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
    env = {**os.environ, "WIREBRAIN_HOME": str(Path(home).resolve())}
    ready = Path(home).resolve() / ("local-ready-" + uuid.uuid4().hex)
    if local_capture:
        env["WIREBRAIN_LOCAL_READY"] = str(ready)
    else:
        env.pop("WIREBRAIN_LOCAL_READY", None)
    store = Store(home)
    store.capture_stop(False)
    proc = subprocess.Popen(command(home, port, local_capture), env=env,
                            stdin=subprocess.PIPE if local_capture else None)
    changed_proxy = False
    guard = None
    session = uuid.uuid4().hex
    try:
        deadline = time.monotonic() + 30
        cert = Path(home) / "certificates" / "mitmproxy-ca-cert.cer"
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ValueError("Capture proxy exited during startup")
            if local_capture:
                if ready.exists() and cert.exists(): break
                time.sleep(.1)
                continue
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.2):
                    if cert.exists(): break
            except OSError: pass
            time.sleep(.1)
        else:
            raise ValueError("Capture proxy did not become ready")
        if install_ca and not local_capture:
            try:
                if sys.platform == 'darwin':
                    from .macos import install_ca as mac_install
                    mac_install(Path(home)/'certificates'/'mitmproxy-ca-cert.pem')
                    (Path(home)/'mac-capture-authorized').touch()
                else:
                    subprocess.run(["certutil", "-user", "-addstore", "Root", str(cert.resolve())], check=True, capture_output=True)
            except subprocess.CalledProcessError as exc:
                raise ValueError("The operating system did not install the local capture certificate; system proxy was not changed") from exc
            print("Local capture CA installed in your user trust store.", flush=True)
        if system_proxy:
            from .proxy_guard import start as start_guard
            guard = start_guard(home, session)
            set_proxy(home, port, session=session)
            changed_proxy = True
        if local_capture:
            (Path(home)/"local-capture-authorized").touch()
            print("Process capture ready for Chrome, ChatGPT and Claude. Windows proxy settings are unchanged.", flush=True)
        else:
            print(f"HTTPS capture listening at 127.0.0.1:{port}\nTargets: ChatGPT, Claude, Gemini, Grok, and Meta AI allowlisted traffic.\nDashboard: run wirebrain up in another terminal.\nCtrl+C stops capture and restores proxy settings.", flush=True)
        if not system_proxy and not local_capture:
            print("System proxy is unchanged. No apps are routed here automatically yet.", flush=True)
        if not install_ca:
            print(f"No certificate trust changes made this run. CA certificate: {cert.resolve()}", flush=True)
        while proc.poll() is None and not store.capture_stop():
            if guardian is not None and guardian.poll() is not None:
                raise ValueError("Driver guardian exited; stopping capture.")
            store.capture_state({"running": True, "port": port, "system_proxy": changed_proxy, "local_capture": local_capture,
                                 "ca_installed_this_run": install_ca, "heartbeat": time.time()})
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if changed_proxy: reset_proxy(home, expected_session=session)
        finally:
            try:
                if guard is not None:
                    from .proxy_guard import finish as finish_guard
                    finish_guard(guard)
            finally:
                if local_capture:
                    proc.stdin.close()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: pass
                    ready.unlink(missing_ok=True)
                if proc.poll() is None:
                    terminate_process(proc)
                store.capture_state({"running": False, "heartbeat": time.time()})
