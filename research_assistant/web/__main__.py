"""Run the local BFF; use Ctrl+C or the orderly bff.stop file to stop."""
import threading
import os
import time
import uvicorn
from research_assistant.server_settings import load_server_settings
from research_assistant.web.app import create_app


def main():
    settings = load_server_settings()
    settings.data_root.mkdir(parents=True, exist_ok=True)
    stop = settings.data_root / 'bff.stop'
    stop.unlink(missing_ok=True)
    port = int(os.getenv('RA_WEB_PORT', '8080'))
    if not 1 <= port <= 65535:
        raise ValueError('RA_WEB_PORT должен быть в диапазоне 1–65535.')
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host='127.0.0.1', port=port,
                                          log_level='warning', access_log=False))
    from research_assistant.server_logging import install_safe_logs
    install_safe_logs()
    def watch():
        while not server.should_exit:
            if stop.exists():
                server.should_exit = True
                return
            time.sleep(.2)
    threading.Thread(target=watch, daemon=True).start()
    server.run()


if __name__ == '__main__':
    main()
