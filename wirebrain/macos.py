"""macOS capture adapter. OS permissions remain explicit and user-controlled."""
import json
import subprocess
from pathlib import Path

NETWORKSETUP = '/usr/sbin/networksetup'


def network(*args):
    try:
        result = subprocess.run([NETWORKSETUP,*args],capture_output=True,text=True,check=True)
        if 'Error:' in result.stdout or 'You need' in result.stdout: raise ValueError(result.stdout.strip())
        return result.stdout
    except subprocess.CalledProcessError as exc:
        raise ValueError('macOS could not change network settings. An administrator may need to authorize networksetup. Your recovery file is kept until restoration succeeds.') from exc


def details(output):
    return dict(line.split(': ',1) for line in output.splitlines() if ': ' in line)


def set_proxy(home, port):
    backup = Path(home)/'proxy-backup.json'
    if backup.exists(): raise ValueError('Run wirebrain capture-reset before starting another recorder')
    services = [s for s in network('-listallnetworkservices').splitlines()[1:] if s and not s.startswith('*')]
    if not services: raise ValueError('No enabled macOS network services were found')
    old = []
    for service in services:
        web = details(network('-getwebproxy',service))
        secure = details(network('-getsecurewebproxy',service))
        pac = details(network('-getautoproxyurl',service))
        discovery = details(network('-getproxyautodiscovery',service))
        if any(p.get('Authenticated Proxy Enabled') in ('1','Yes','On') for p in (web,secure)) or pac.get('Enabled') == 'Yes' or discovery.get('Auto Proxy Discovery') == 'On':
            raise ValueError('This network uses an authenticated proxy or automatic proxy script. Automatic capture setup cannot safely replace it.')
        old.append({'service':service,'web':web,'secure':secure})
    backup.write_text(json.dumps({'platform':'Darwin','services':old}),encoding='utf-8')
    try:
        for item in old:
            for kind in ('web','secureweb'):
                network('-set'+kind+'proxy',item['service'],'127.0.0.1',str(port))
                network('-set'+kind+'proxystate',item['service'],'on')
    except (OSError,ValueError):
        reset_proxy(home)
        raise


def reset_proxy(home):
    backup = Path(home)/'proxy-backup.json'
    if not backup.exists(): return
    state = json.loads(backup.read_text(encoding='utf-8'))
    if state.get('platform') != 'Darwin': raise ValueError('This proxy backup belongs to another operating system')
    errors = []
    for item in state['services']:
        for kind,key in (('web','web'),('secureweb','secure')):
            old = item[key]
            try:
                if old.get('Server') and old.get('Port','0') != '0':
                    network('-set'+kind+'proxy',item['service'],old['Server'],old['Port'])
                elif old.get('Enabled') == 'Yes':
                    raise ValueError('The saved enabled proxy has no valid server/port; check Network settings')
                network('-set'+kind+'proxystate',item['service'],'on' if old.get('Enabled')=='Yes' else 'off')
            except (OSError,ValueError) as exc: errors.append(str(exc))
    if errors: raise ValueError('Proxy restoration needs attention. Run wirebrain capture-reset again. '+errors[0])
    backup.unlink()


def install_ca(cert):
    subprocess.run(['/usr/bin/security','add-trusted-cert','-r','trustRoot','-k',str(Path.home()/'Library/Keychains/login.keychain-db'),str(cert)],check=True)


def remove_ca(cert):
    import hashlib
    import ssl
    if not cert.exists(): return
    fingerprint = hashlib.sha1(ssl.PEM_cert_to_DER_cert(cert.read_text(encoding='ascii'))).hexdigest()
    subprocess.run(['/usr/bin/security','remove-trusted-cert',str(cert)],check=True)
    subprocess.run(['/usr/bin/security','delete-certificate','-Z',fingerprint,str(Path.home()/'Library/Keychains/login.keychain-db')],check=True)
    (cert.parent.parent/'mac-capture-authorized').unlink(missing_ok=True)
