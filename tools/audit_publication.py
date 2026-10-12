"""Read-only publication guard: report filenames, never print secret values."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', 'runtime', '__pycache__', '.pytest_cache', 'node_modules', '_scratch', 'tmp', 'backups', 'output', 'dist'}
TEXT = {'.py', '.js', '.cjs', '.mjs', '.html', '.css', '.json', '.md', '.txt', '.ps1', '.bat', '.yml', '.yaml'}
TOKEN = re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
PAYLOAD = re.compile(r'<script id="sync-payload" type="application/json">(.*?)</script>', re.S)


def selected_files():
    result = subprocess.run(['git','ls-files','-z'], cwd=ROOT, capture_output=True)
    names = result.stdout.decode('utf-8').split('\0') if result.returncode == 0 else []
    if any(names):
        return [ROOT/name for name in names if name]
    return [p for p in ROOT.rglob('*') if p.is_file() and not any(part in SKIP for part in p.relative_to(ROOT).parts)]


def is_clean_payload(block):
    if block.strip() in ('', '{}', 'null'):
        return True
    try:
        value = json.loads(block)
    except ValueError:
        return False
    return isinstance(value, dict) and set(value) <= {'syncedAt','note','courses','messages','todos'} and not any(value.values())


def audit():
    problems = []
    checked = 0
    for path in selected_files():
        rel = path.relative_to(ROOT)
        name = rel.as_posix()
        checked += 1
        if any(p in SKIP for p in rel.parts):
            problems.append((name, 'private/generated directory')); continue
        if rel.parts[0] == 'data' and path.name != '.gitkeep':
            problems.append((name, 'local application data')); continue
        if name.startswith(('sync/state/', 'sync/debug/', 'sync/logs/')) or name in ('sync/push_config.json', 'sync/sync-data.json', 'weapp/project.private.config.json'):
            problems.append((name, 'credentials, logs or private configuration')); continue
        if path.suffix.lower() in {'.sqlite3','.db','.log','.pem','.key','.p12','.lnk'} or path.name == '.env':
            problems.append((name, 'sensitive or local-only file')); continue
        if path.stat().st_size > 50*1024*1024:
            problems.append((name, 'large binary; review before Git upload')); continue
        if path.suffix.lower() not in TEXT:
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if TOKEN.search(text):
            problems.append((name, 'possible access token or private key'))
        if path.suffix.lower() == '.html':
            for block in PAYLOAD.findall(text):
                if not is_clean_payload(block):
                    problems.append((name, 'nonempty personal sync snapshot'))
        if name == 'weapp/miniprogram/config.js' and re.search(r"ENV_ID:\s*['\"][^'\"]+['\"]", text):
            problems.append((name, 'cloud environment is not an empty template'))
    print(f'Publication audit: {checked} files; {len(problems)} issues')
    for name, reason in problems:
        print(name+': '+reason)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(audit())
