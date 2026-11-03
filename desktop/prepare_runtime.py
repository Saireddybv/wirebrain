"""Stage the private Windows runtime on the build machine, not on the user's PC."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/"desktop/src-tauri/runtime"
URL = "https://api.nuget.org/v3-flatcontainer/python/3.11.9/python.3.11.9.nupkg"
SHA256 = "9283876d58c017e0e846f95b490da3bca0fc0a6ee1134b2870677cfb7eec3c67"

if __name__ == "__main__":
    if os.name != "nt" or sys.version_info[:2] != (3,11) or sys.maxsize <= 2**32:
        sys.exit("Build with Windows x64 Python 3.11.")
    RUNTIME.mkdir(exist_ok=False)
    data = urllib.request.urlopen(URL, timeout=90).read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        sys.exit("Unexpected CPython package digest")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if name.startswith("tools/") and not name.endswith("/"):
                target = (RUNTIME / name[6:]).resolve()
                target.relative_to(RUNTIME)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    pip = [sys.executable,"-m","pip","install","--disable-pip-version-check","--no-compile",
           "--target",str(RUNTIME/"Lib/site-packages")]
    subprocess.run(pip + ["--require-hashes","-r",str(ROOT/"desktop/capture-win64.lock")],check=True)
    subprocess.run(pip + ["--no-deps",str(ROOT)],check=True)
    (RUNTIME/"wirebrain-runtime").touch()
    subprocess.run([str(RUNTIME/"python.exe"),"-I","-c",
                    "import sqlite3, mitmproxy_windows, wirebrain.desktop; from mitmproxy.tools.main import mitmdump"],check=True)
