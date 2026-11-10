import json
import unittest
import httpx
import decision


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):decision._blocked_until=0
    async def test_obvious_routes_never_call_classifier(self):
        def forbidden(request):raise AssertionError('classifier should not run')
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as h:
            for q,route in [('tell me a joke about Trump','chat'),('latest Israel news','search'),('verify this quote is authentic','fact'),('research the competing primary sources','research'),('how many characters did user alice write?','chat')]:
                self.assertEqual(await decision.choose_route(q,h,True),route)
    async def test_ambiguous_hint_is_bounded_and_failures_open_circuit(self):
        calls=[]
        def malformed(request):calls.append(request);return httpx.Response(200,json={'response':'{"route":"admin"}'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(malformed)) as h:
            self.assertEqual(await decision.choose_route('Explain the competing accounts of this dispute.',h,True),'chat')
            self.assertEqual(await decision.choose_route('Compare these two ideas in a concise explanation.',h,True),'chat')
            self.assertEqual(len(calls),1)
            body=json.loads(calls[0].content)
            self.assertLessEqual(len(body['state']['question']),700)
            self.assertEqual(set(body['questions']['route']['criteria']),{'chat','search','fact','research'})
    async def test_valid_research_hint(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'answers':{'route':{'choice':'research','confidence':.9}}}))) as h:
            self.assertEqual(await decision.choose_route('Compare the provenance of these disputed quotations.',h,True),'research')
