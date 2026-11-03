"""Exercise the installed WebView2 controls on a disposable GitHub Windows runner."""
import os
from pathlib import Path
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright
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


def run(pid, debug_port, diary_port, installed_python):
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
    with sync_playwright() as driver:
        browser = driver.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
        page = next(page for context in browser.contexts for page in context.pages
                    if page.url == f"http://127.0.0.1:{diary_port}/")
        start = page.locator("#welcome-record")
        start.wait_for()
        if start.inner_text() != "Start recording":
            raise RuntimeError("Unexpected first-run state")
        start.click()
        answer_dialog(pid, win32con.IDCANCEL)
        if page.evaluate("fetch('/api/stats').then(r=>r.json()).then(s=>s.capture.running)"):
            raise RuntimeError("Cancelling started recording")
        try:
            subprocess.run([installed_python,"-I","-c",setup,str(repo/"scripts"),str(der_path)],check=True)
            start.click()
            answer_dialog(pid, win32con.IDOK)
            page.wait_for_function("document.querySelector('#welcome-record').textContent === 'Stop recording'",timeout=90000)
            start.click()
            page.wait_for_function("document.querySelector('#welcome-record').textContent === 'Start recording'",timeout=90000)
        finally:
            page.evaluate("fetch('/api/capture/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})")
            if der_path.exists():
                cleanup = "from wirebrain.windows_certificates import remove_root; from pathlib import Path; import sys; remove_root(Path(sys.argv[1]).read_bytes(),'LocalMachine')"
                subprocess.run([installed_python,"-I","-c",cleanup,str(der_path)],check=True)
                der_path.unlink()


if __name__ == "__main__":
    run(int(sys.argv[1]),int(sys.argv[2]),int(sys.argv[3]),sys.argv[4])
