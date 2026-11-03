"""Record exactly which CA and files desktop enrollment introduced."""
import hashlib
import json
from pathlib import Path


NAMES = {"mitmproxy-ca.pem","mitmproxy-ca.p12","mitmproxy-ca-cert.pem",
         "mitmproxy-ca-cert.cer","mitmproxy-ca-cert.p12","mitmproxy-dhparam.pem"}


def remember(home, der, existed):
    target = home/"desktop-enrollment.json"
    fingerprint = hashlib.sha256(der).hexdigest()
    if target.exists():
        if json.loads(target.read_text())["root"] != fingerprint:
            raise ValueError("Desktop enrollment fingerprint changed; refusing to replace the record.")
        return
    files = {}
    for name in NAMES - existed:
        path = home/"certificates"/name
        if path.is_file():
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"root":fingerprint,"files":files}))
    tmp.replace(target)


def forget(home, roots, untrust):
    target = home/"desktop-enrollment.json"
    if not target.exists():
        return
    entry = json.loads(target.read_text())
    cert = next((der for der in roots() if hashlib.sha256(der).hexdigest() == entry["root"]), None)
    if cert:
        untrust(cert)
        if cert in roots():
            raise RuntimeError("Desktop root is still trusted")
    for name,digest in entry["files"].items():
        if name not in NAMES:
            raise ValueError("Unknown enrollment file; refusing cleanup")
        path = home/"certificates"/name
        if path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Enrollment file changed; refusing cleanup")
            path.unlink()
    (home/"local-capture-authorized").unlink(missing_ok=True)
    target.unlink()
