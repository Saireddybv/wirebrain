"""Build and install the wheel in isolation; verify its packaged capture policy."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    dest = Path(tmp)
    installed = dest / "installed"
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", tmp, str(root)], cwd=tmp, check=True)
    wheel, = dest.glob("wirebrain_local-*.whl")
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed), str(wheel)], cwd=tmp, check=True)
    subprocess.run([sys.executable, "-I", "-c", """
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from wirebrain import webcapture
assert Path(webcapture.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
assert webcapture.HOSTS["chatgpt.com"] == "chatgpt"
""", str(installed)], cwd=tmp, check=True)
