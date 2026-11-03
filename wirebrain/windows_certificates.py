"""Remove only an exact certificate from a named Windows root store."""
import base64
import os
from pathlib import Path
import subprocess


def remove_root(der, scope="CurrentUser"):
    if scope not in ("CurrentUser", "LocalMachine"):
        raise ValueError("Invalid root store")
    shell = Path(os.environ["SystemRoot"])/"System32/WindowsPowerShell/v1.0/powershell.exe"
    script = """
$ErrorActionPreference='Stop'
$store = [System.Security.Cryptography.X509Certificates.X509Store]::new('Root',$env:WB_CERT_SCOPE)
try {
    $store.Open('ReadWrite')
    foreach ($cert in $store.Certificates) {
        if ([Convert]::ToBase64String($cert.RawData) -ceq $env:WB_CERT_DER) { $store.Remove($cert) }
    }
} finally { $store.Close() }
"""
    subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                   env={**os.environ, "WB_CERT_SCOPE":scope, "WB_CERT_DER":base64.b64encode(der).decode("ascii")},
                   capture_output=True, timeout=60)
