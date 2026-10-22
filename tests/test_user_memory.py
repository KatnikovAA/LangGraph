import tempfile
import unittest
from pathlib import Path
from research_assistant.user_memory import (open_memory_store, update_profile, get_profile,
    save_note, list_notes, update_note, delete_note, retrieve_memory, MemoryError)


class UserMemoryTests(unittest.TestCase):
    def test_profile_collection_retrieval_and_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'memory.sqlite')
            with open_memory_store(db) as store:
                update_profile(store, 'alice', {'language': 'English', 'code_language': 'Python'})
                update_profile(store, 'alice', {'style': 'detailed'})
                self.assertEqual(get_profile(store, 'alice'), {'language': 'English', 'style': 'detailed', 'code_language': 'Python'})
                self.assertEqual(len(store.search(('alice', 'profile'))), 1)
                self.assertEqual(get_profile(store, 'bob')['language'], 'русский')
                a = save_note(store, 'alice', {'text': 'StateGraph сохраняет state', 'tags': ['LangGraph']})
                b = save_note(store, 'alice', {'text': 'Другой факт', 'topic': 'Python'})
                self.assertEqual(len(list_notes(store, 'alice')), 2)
                update_note(store, 'alice', a, {'text': 'Обновлённая заметка', 'tags': ['LangGraph']})
                selected = retrieve_memory(store, 'alice', 'LangGraph')
                self.assertEqual([item['id'] for item in selected['notes']], [a])
                self.assertEqual(retrieve_memory(store, 'alice', 'unmatched')['notes'], [])
                self.assertEqual(retrieve_memory(store, 'bob', 'LangGraph')['notes'], [])
                delete_note(store, 'alice', a)
                self.assertEqual(len(list_notes(store, 'alice')), 1)
                self.assertEqual(retrieve_memory(store, 'alice', 'LangGraph')['notes'], [])
                with self.assertRaises(MemoryError):
                    update_profile(store, 'alice', {'unknown': 'x'})
            with open_memory_store(db, existing=True) as store:
                self.assertEqual(get_profile(store, 'alice')['style'], 'detailed')
                self.assertEqual(list_notes(store, 'alice')[0]['id'], b)

    def test_real_store_contract_async_prefix_filters_pagination_and_rollback(self):
        import asyncio
        from langgraph.store.base import BaseStore, PutOp
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            self.assertIsInstance(store, BaseStore)
            store.put(('a', 'notes'), 'b', {'kind': 'note', 'nested': {'value': 1}})
            store.put(('a', 'notes'), 'a', {'kind': 'note'})
            store.put(('ab', 'notes'), 'x', {'kind': 'note'})
            items = store.search(('a',), filter={'kind': 'note'}, limit=1)
            self.assertEqual([i.key for i in items], ['a'])
            self.assertEqual(store.search(('a',), limit=1, offset=1)[0].key, 'b')
            self.assertEqual(store.list_namespaces(prefix=('a',)), [('a', 'notes')])
            original = store.get(('a', 'notes'), 'a')
            store.put(('a', 'notes'), 'a', {'kind': 'new'})
            self.assertEqual(store.get(('a', 'notes'), 'a').created_at, original.created_at)
            async def check():
                await store.aput(('async', 'notes'), 'x', {'text': 'JSON'})
                self.assertEqual((await store.aget(('async', 'notes'), 'x')).value, {'text': 'JSON'})
                await store.adelete(('async', 'notes'), 'x')
                self.assertIsNone(await store.aget(('async', 'notes'), 'x'))
            asyncio.run(check())
            for action in [lambda: store.search(('a',), query='semantic'),
                           lambda: store.put(('a',), 'x', {}, ttl=1),
                           lambda: store.search(('a',), filter={'kind': {'$eq': 'note'}})]:
                with self.assertRaises(NotImplementedError):
                    action()
            store.conn.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON store WHEN NEW.key = 'reject' "
                               "BEGIN SELECT RAISE(ABORT, 'offline rejected'); END")
            with self.assertRaises(MemoryError):
                store.batch([PutOp(('a',), 'rollback', {'x': 1}), PutOp(('a',), 'reject', {'x': 2})])
            self.assertIsNone(store.get(('a',), 'rollback'))

    def test_receipt_replay_size_limits_and_deterministic_selection(self):
        from research_assistant.user_memory import apply_tool_operation, MAX_MEMORY_CHARS
        import json
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            origin = {'chat_thread_id': 'a', 'turn_id': 'turn', 'tool_call_id': 'call'}
            first = apply_tool_operation(store, 'alice', 'save_note', {'text': 'LangGraph note'}, origin)
            second = apply_tool_operation(store, 'alice', 'save_note', {'text': 'LangGraph note'}, origin)
            self.assertEqual(first['id'], second['id'])
            self.assertEqual(second['status'], 'already_applied')
            self.assertEqual(len(list_notes(store, 'alice')), 1)
            delete_note(store, 'alice', first['id'])
            replay = apply_tool_operation(store, 'alice', 'save_note', {'text': 'LangGraph note'}, origin)
            self.assertFalse(replay['present'])
            self.assertEqual(list_notes(store, 'alice'), [])
            for i in range(6):
                save_note(store, 'alice', {'text': 'LangGraph ' + 'X' * 550}, note_id=f'n{i}')
            selection = retrieve_memory(store, 'alice', 'LangGraph')
            self.assertEqual([n['id'] for n in selection['notes']], ['n0', 'n1', 'n2'])
            self.assertLessEqual(len(json.dumps(selection, ensure_ascii=False)), MAX_MEMORY_CHARS)
            self.assertEqual(selection, retrieve_memory(store, 'alice', 'LangGraph'))
