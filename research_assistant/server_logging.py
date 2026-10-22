"""Server logs contain operational IDs, never raw provider errors or payloads."""
import logging


class SafeServerLogs(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, dict):
            record.msg = {k: v for k, v in record.msg.items() if k not in (
                'error', 'exception', 'exc_info', 'traceback', 'input', 'output',
                'payload', 'response', 'content', 'kwargs', 'stack_info')}
        if record.levelno >= logging.ERROR or record.exc_info:
            if isinstance(record.msg, dict):
                record.msg = {k: record.msg[k] for k in ('run_id', 'thread_id', 'graph_id') if k in record.msg}
                record.msg['event'] = 'Server operation failed; inspect application state and configuration.'
            else:
                record.msg = 'Server operation failed; inspect application state and configuration.'
            record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


def install_safe_logs():
    handlers = set(logging.getLogger().handlers)
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            handlers.update(logger.handlers)
    for handler in handlers:
        handler.addFilter(SafeServerLogs())
