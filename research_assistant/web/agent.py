"""Isolated dev Agent Server runner with an orderly local stop-file lifecycle."""
import importlib
import json
import os
from pathlib import Path
import socket
import threading
import time


def main():
    from research_assistant.server_settings import load_server_settings
    settings = load_server_settings()
    root = Path(__file__).resolve().parents[2]
    settings.data_root.mkdir(parents=True, exist_ok=True)
    runtime = settings.data_root / 'runtime'
    runtime.mkdir(exist_ok=True)
    os.environ.update(LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false', LOG_COLOR='false')
    os.environ['RA_WEB_DATA'] = str(settings.data_root)
    os.environ['PYTHONPATH'] = str(root)
    if settings.mode == 'live':
        from dotenv import load_dotenv
        load_dotenv(root / '.env', override=False, encoding='utf-8-sig')
        if any(not os.environ.get(k, '').strip() for k in ('POLZA_API_KEY', 'POLZA_MODEL', 'TAVILY_API_KEY')):
            raise ValueError('Live требует POLZA_API_KEY, POLZA_MODEL и TAVILY_API_KEY на сервере.')
    from urllib.parse import urlparse
    port = urlparse(settings.agent_url).port or 2025
    # The CLI otherwise silently chooses another port, breaking the BFF connection.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    config = json.loads((root / 'langgraph.web.json').read_text(encoding='utf-8'))
    config['dependencies'] = [str(root)]
    config['graphs'] = {k: (root / v.split(':')[0]).as_posix() + ':' + v.split(':')[1] for k, v in config['graphs'].items()}
    config['store']['path'] = (root / 'research_assistant/server_store.py').as_posix() + ':create_store'
    file = runtime / 'langgraph.json'
    file.write_text(json.dumps(config), encoding='utf-8')
    stop = settings.data_root / 'agent.stop'
    stop.unlink(missing_ok=True)
    # Uvicorn still owns startup/shutdown; the watcher requests its normal shutdown.
    uvmain = importlib.import_module('uvicorn.main')
    original = uvmain.Server
    class LocalServer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # CLI environment is now configured, but native lifespan has not run.
            # Pickle imports may need native config; checking earlier would cache
            # an unconfigured server module. Fail before start_pool can delete data.
            from research_assistant.web.runtime_guard import guard_runtime
            guard_runtime(runtime)
            from research_assistant.server_logging import install_safe_logs
            install_safe_logs()
            def watch():
                while not self.should_exit:
                    if stop.exists():
                        self.should_exit = True
                        break
                    time.sleep(.2)
            threading.Thread(target=watch, daemon=True).start()
    uvmain.Server = LocalServer
    os.chdir(runtime)
    from langgraph_cli.cli import cli
    cli.main(args=['dev', '--config', str(file), '--host', '127.0.0.1', '--port', str(port),
                   '--no-browser', '--no-reload', '--allow-blocking', '--server-log-level', 'WARNING'], standalone_mode=False)


if __name__ == '__main__':
    main()
