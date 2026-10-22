"""Agent Server owns this context manager; BFF accesses the same native Store."""
from research_assistant.server_settings import load_server_settings
from research_assistant.user_memory import open_memory_store


def create_store():
    target = load_server_settings().memory_db
    return open_memory_store(str(target), existing=target.exists())
