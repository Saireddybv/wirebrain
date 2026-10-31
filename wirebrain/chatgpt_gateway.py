"""Testing adapter for Codex's supported ChatGPT sign-in, without copying tokens."""
from .prompting import render_prompt
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

LOCK = threading.Lock()
DISABLED = ('shell_tool', 'unified_exec', 'apps', 'plugins', 'remote_plugin',
            'hooks', 'multi_agent', 'browser_use', 'computer_use', 'code_mode_host', 'code_mode', 'code_mode_only',
            'view_image', 'skill_search')


def environment():
    env = dict(os.environ)
    # A separately configured API key must not turn this into API-key billing.
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL'):
        env.pop(name, None)
    return env


def executable():
    return shutil.which('codex.exe') or shutil.which('codex')


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def status():
    binary = executable()
    if not binary:
        return {'available':False,'connected':False,'message':'Install Codex CLI and run codex login with ChatGPT.'}
    try:
        result = subprocess.run([binary,'login','status'], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=10, env=environment(), **process_options())
        description = (result.stdout + result.stderr).lower()
        connected = result.returncode == 0 and 'chatgpt' in description and 'logged in' in description
        return {'available':True,'connected':connected,
                'message':'Connected with ChatGPT sign-in. Requests use your Codex allowance.' if connected else 'Run codex login and choose ChatGPT sign-in.'}
    except (OSError, subprocess.TimeoutExpired):
        return {'available':True,'connected':False,'message':'Could not check Codex sign-in. Run codex login status.'}


def chat(messages, schema=None):
    if not isinstance(messages,list) or not messages or len(json.dumps(messages))>80000:
        raise ValueError('Choose a bounded message list for the ChatGPT testing gateway')
    binary = executable()
    if not binary:
        raise ValueError('Codex CLI is missing. Install it and sign in with ChatGPT first.')
    if not status()['connected']:
        raise ValueError('Sign in to Codex with ChatGPT first. API-key logins are not used by this testing gateway.')
    if not LOCK.acquire(blocking=False):
        raise ValueError('The ChatGPT testing gateway is busy. Try again shortly.')
    try:
        # A fresh empty directory avoids loading repository context. No prompt or reply
        # is saved here. Codex owns sign-in/token renewal in its existing credential store.
        with tempfile.TemporaryDirectory(prefix='wirebrain-chatgpt-') as directory:
            args = [binary,'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check',
                    '--sandbox','read-only','--json','--color','never',
                    '-c','project_doc_max_bytes=0','-c','web_search="disabled"']
            for feature in DISABLED:
                args.extend(['--disable',feature])
            if schema is not None:
                path = Path(directory)/'output-schema.json'
                path.write_text(json.dumps(schema),encoding='utf-8')
                args.extend(['--output-schema',str(path)])
            args.append('-')
            request_prompt = render_prompt('gateway.text_only',messages=json.dumps(messages,ensure_ascii=False))
            try:
                result = subprocess.run(args, input=request_prompt, text=True, encoding='utf-8', errors='replace',
                    capture_output=True,cwd=directory,env=environment(),timeout=150,**process_options())
            except subprocess.TimeoutExpired:
                raise ValueError('The ChatGPT testing gateway timed out; no memory was saved for this request.') from None
            except OSError:
                raise ValueError('Could not start the Codex ChatGPT gateway.') from None
            if result.returncode:
                raise ValueError('ChatGPT gateway failed. Check codex login status, your Codex allowance, and connectivity. No API-key fallback was used.')
            answer = ''
            completed = False
            for line in result.stdout.splitlines():
                try: event = json.loads(line)
                except ValueError: continue
                if event.get('type') in ('turn.failed','error'):
                    raise ValueError('ChatGPT did not complete the request. Check your subscription allowance and sign-in.')
                if event.get('type') == 'item.completed':
                    item = event.get('item',{})
                    if item.get('type') == 'agent_message': answer = item.get('text','')
                    elif item.get('type') == 'error' and str(item.get('message','')).startswith('Code Mode is unavailable because code-mode host is disabled.'):
                        pass  # Expected fail-closed tool-host notice in a text-only runner.
                    elif item.get('type') not in ('reasoning',):
                        raise ValueError('The text gateway rejected an unexpected item type: '+str(item.get('type')))
                if event.get('type') == 'turn.completed': completed = True
            if not completed or not isinstance(answer,str) or not answer.strip():
                raise ValueError('ChatGPT returned no completed text answer.')
            if schema is not None:
                try: json.loads(answer)
                except ValueError: raise ValueError('ChatGPT returned invalid structured JSON.') from None
            return {'message':{'content':answer},'provider':'chatgpt-sign-in'}
    finally:
        LOCK.release()
