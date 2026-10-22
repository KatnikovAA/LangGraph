"""Fail publication checks on sensitive tracked files; never print secret values.

This is a small repository policy check, not an exhaustive secret scanner.
"""

import re
import subprocess
from pathlib import PurePosixPath


TEMPLATES = {'.env.example', '.env.web.example'}
TOKEN = re.compile(
    r'(?<![\w-])(?:sk-[A-Za-z0-9_-]{32,}|tvly-[A-Za-z0-9_-]{24,}'
    r'|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'
)
PRIVATE_KEY = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')


def inspect_file(name: str, content: str) -> list[str]:
    path = PurePosixPath(name)
    findings = []
    if ((path.name == '.env' or path.name.startswith('.env.')) and name not in TEMPLATES
            or path.suffix.lower() in {'.key', '.pem', '.p12', '.pfx'}):
        findings.append('sensitive file must not be tracked')
    if TOKEN.search(content) or PRIVATE_KEY.search(content):
        findings.append('possible credential or private key')
    if name in TEMPLATES:
        for line in content.splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key in {'POLZA_API_KEY', 'TAVILY_API_KEY', 'OPENAI_API_KEY', 'LANGSMITH_API_KEY'}:
                if value.strip().strip('\"\''):
                    findings.append('API key in environment template must be empty')
    return findings


def main() -> int:
    # Read index blobs: untracked/ignored local .env files are never opened.
    git = ['git']
    names = subprocess.check_output(git + ['ls-files', '-z']).decode('utf-8').split('\0')
    failures = []
    for name in filter(None, names):
        raw = subprocess.check_output(git + ['show', ':' + name])
        for finding in inspect_file(name, raw.decode('utf-8', errors='replace')):
            failures.append(f'{name}: {finding}')
    if failures:
        print('\n'.join(failures))
        return 1
    print('Repository security policy: OK (tracked files only; no secret values printed).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
