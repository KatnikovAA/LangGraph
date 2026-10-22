import unittest
try:
    from research_assistant.web.app import projection
    from research_assistant.web.client import EventProjection
except ImportError:
    projection = EventProjection = None


@unittest.skipIf(projection is None, 'Requires web extra')
class WebInterviewTests(unittest.TestCase):
    def test_initial_checkpoint_none(self):
        result=projection({'checkpoint':None,'values':{},'next':[]})
        self.assertIsNone(result['checkpoint_id'])
        self.assertEqual(result['status'],'new')

    def test_custom_event_whitelist(self):
        from uuid import uuid4
        projector=EventProjection('real-run')
        data=dict(node='ask_question',round=1,execution_id=str(uuid4()),status='running',
                  timestamp='2026-10-22T12:00:00+00:00',secret='PRIVATE',run_id='fake')
        kind,event=projector.accept('custom',data)
        self.assertEqual(kind,'interview-progress')
        self.assertEqual(event['run_id'],'real-run')
        self.assertNotIn('PRIVATE',str(event))

    def test_missing_pinned_checkpoint_is_404(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from uuid import uuid4
        from starlette.exceptions import HTTPException
        from research_assistant.web.service import WebService
        service=object.__new__(WebService)
        service.owned=AsyncMock(return_value={})
        service.client=SimpleNamespace(threads=SimpleNamespace(get_state=AsyncMock(return_value={'checkpoint':None})))
        with self.assertRaises(HTTPException) as result:
            asyncio.run(service.state('alice',str(uuid4()),str(uuid4())))
        self.assertEqual(result.exception.status_code,404)
