"""Source-checkout launcher: python start_wirebrain.py. No elevated silent setup."""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser


def main():
    if sys.version_info < (3,11): raise SystemExit('Install Python 3.11 or newer first: https://python.org/downloads/')
    root = Path(__file__).resolve().parent
    environment = root/'.venv-wirebrain'
    python = environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists(): subprocess.run([sys.executable,'-m','venv',str(environment)],check=True)
    print('Preparing Wirebrain. First launch downloads its capture dependencies; later launches reuse them.')
    marker = environment/'wirebrain-ready'
    if not marker.exists():
        subprocess.run([str(python),'-m','pip','install','-e',str(root)+'[capture,memory]'],check=True)
        marker.touch()
    home = Path(os.environ.get('WIREBRAIN_HOME',str(Path.home()/'.wirebrain'))).resolve()
    base = [str(python),'-m','wirebrain','--home',str(home)]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:3333/health',timeout=1):
            webbrowser.open('http://127.0.0.1:3333/')
            print('A diary is already open on port 3333. Use its Local setup screen.'); return
    except OSError: pass
    dashboard = subprocess.Popen(base+['up'])
    try:
        for _ in range(50):
            if dashboard.poll() is not None: raise SystemExit('The diary could not start. Check the message above.')
            try:
                with opener.open('http://127.0.0.1:3333/health',timeout=.3): break
            except OSError: time.sleep(.1)
        else: raise SystemExit('The diary did not become ready.')
        webbrowser.open('http://127.0.0.1:3333/')
        print('\nCapture can read supported ChatGPT and Claude conversation traffic on this device.\n'
              'Enabling it trusts a local certificate and changes your proxy settings until capture stops.\n'
              'Windows and macOS are supported by setup code; macOS still needs real-device verification.\n'
              'Your OS may ask you to approve certificate or network changes.')
        enable = input('Enable capture on this computer? Type yes, or press Enter for diary only: ').strip().lower()
        if enable == 'yes':
            result = subprocess.run(base+['capture','--install-ca','--system-proxy'])
            if result.returncode:
                print('Capture setup did not finish. The diary remains open; check Local setup and the message above.')
        print('Diary open. Optional local AI and history import are in Local setup. Ctrl+C exits.')
        dashboard.wait()
    except KeyboardInterrupt: pass
    finally:
        if dashboard.poll() is None:
            dashboard.terminate()
            dashboard.wait()


if __name__ == '__main__': main()
