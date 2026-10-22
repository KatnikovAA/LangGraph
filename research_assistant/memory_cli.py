"""Explicit memory CRUD and retrieval diagnostics without invoking any model."""

import json
from pathlib import Path
from research_assistant.user_memory import (DEFAULT_MEMORY_DB, MemoryError, open_memory_store, validate_user_id,
    get_profile, update_profile, reset_profile, save_note, get_note, list_notes, update_note, delete_note,
    retrieve_memory)

COMMANDS = ('profile-show', 'profile-update', 'profile-reset', 'note-add', 'note-list', 'note-show',
            'note-update', 'note-delete', 'retrieve')


def run_memory(args) -> dict:
    user = validate_user_id(args.user_id)
    command = args.memory_command
    needs_data = command in ('profile-update', 'note-add', 'note-update')
    needs_id = command in ('note-show', 'note-update', 'note-delete')
    supplied_data = args.memory_json is not None or args.memory_file is not None
    if (needs_data != supplied_data or (args.memory_json is not None and args.memory_file is not None)
            or needs_id != (args.note_id is not None) or (args.note_id is not None and not args.note_id.strip())
            or ((command == 'retrieve') != (args.memory_query is not None))):
        raise MemoryError('Проверьте аргументы: update/add требуют memory-json/file; note show/update/delete — note-id; retrieve — memory-query.')
    data = None
    if needs_data:
        try:
            data = json.loads(Path(args.memory_file).read_text(encoding='utf-8-sig') if args.memory_file
                              else args.memory_json)
        except (OSError, ValueError) as error:
            raise MemoryError('Нужен корректный JSON-объект памяти в UTF-8.') from error
        if not isinstance(data, dict):
            raise MemoryError('Память принимает JSON-объект.')
    path = str(Path(args.memory_db or DEFAULT_MEMORY_DB).resolve())
    with open_memory_store(path) as store:
        if command == 'profile-show':
            result = get_profile(store, user)
        elif command == 'profile-update':
            result = update_profile(store, user, data)
        elif command == 'profile-reset':
            reset_profile(store, user)
            result = {'status': 'reset', 'profile': get_profile(store, user)}
        elif command == 'note-add':
            identifier = save_note(store, user, data)
            result = get_note(store, user, identifier)
        elif command == 'note-list':
            result = list_notes(store, user)
        elif command == 'note-show':
            result = get_note(store, user, args.note_id)
        elif command == 'note-update':
            result = update_note(store, user, args.note_id, data)
        elif command == 'note-delete':
            delete_note(store, user, args.note_id)
            result = {'status': 'deleted', 'id': args.note_id}
        else:
            result = retrieve_memory(store, user, args.memory_query)
    return {'user_id': user, 'memory_db': path, 'operation': command, 'result': result}
