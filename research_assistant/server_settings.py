"""Explicit local web environment; never reuse CLI databases implicitly."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerSettings:
    mode: str
    data_root: Path
    agent_url: str

    @property
    def reports(self):
        return self.data_root / 'reports'

    @property
    def memory_db(self):
        return self.data_root / 'memory.sqlite'


def load_server_settings() -> ServerSettings:
    mode = os.getenv('RA_WEB_MODE', 'demo')
    if mode not in ('demo', 'live'):
        raise ValueError('RA_WEB_MODE: допустимы demo или live.')
    root = Path(os.getenv('RA_WEB_DATA', f'.research_assistant/web/{mode}')).resolve()
    url = os.getenv('RA_AGENT_URL', 'http://127.0.0.1:2025')
    from urllib.parse import urlparse
    if urlparse(url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Agent Server должен быть доступен по loopback.')
    return ServerSettings(mode, root, url)
