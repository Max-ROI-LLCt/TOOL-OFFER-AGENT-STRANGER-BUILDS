"""Synthetic legacy-behavior regressions; no customer transcript is distributed."""
import asyncio
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import Mock, AsyncMock, patch
from uuid import uuid4

from tool_offer_agent.chat import respond, create_text_chat, bounded_send
from tool_offer_agent.drafting import CATEGORIES, OpenAIQuoteExtractor, ExtractionError
from tool_offer_agent.export_delivery import snapshot, part, reassemble, REPLY_BYTES
from tool_offer_agent.model_runtime import completion, traced
from tool_offer_agent.offer_representation import buyer_offer, representation
from tool_offer_agent.restrictions import capture, empty
from tool_offer_agent.workflow import Workflow
from tests.support import StoreTestMixin, FakeFetcher, INTAKE, DOC_URL
from tool_offer_agent.documents import Document

FIXTURE = json.loads((Path(__file__).parent/'fixtures/customer-revision41.json').read_text())


def model_response(value):
    return SimpleNamespace(model='asi1', usage=None, choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps(value)))])


class CustomerSequenceTests(StoreTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Mock()
        self.client.chat.completions.create.return_value = model_response({name: [] for name in CATEGORIES})
        self.model = Mock()
        self.model.interpret.return_value = {'action':'update','reply':'Understood.', 'updates': {
            'tool_url':'https://jsonplaceholder.typicode.com/', 'docs':'https://jsonplaceholder.typicode.com/',
            'customer':'developers learning HTTP integrations', 'pricing':'USD 0 for this demonstration only',
            'payment':'No payment is collected', 'access':'public without an API key',
            'invocation':'GET https://jsonplaceholder.typicode.com/posts/1', 'job':'demonstrate reading a fake post'}}
        self.fetcher = Mock()
        self.fetcher.fetch.return_value = Document(**FIXTURE['document'])
        self.checkout = Mock()
        self.w = Workflow(store=self.store, fetcher=self.fetcher, conversation=self.model,
                          extractor=OpenAIQuoteExtractor(self.client), checkout=self.checkout)

    def chat(self, text, **kwargs):
        return self.w.handle('seller','session',text, **kwargs)

    def state(self):
        return self.store.load(self.store.key('seller','session'))

    def test_complete_customer_sequence_preserves_typed_restrictions_everywhere(self):
        declaration = FIXTURE['restriction_message']
        self.assertIn('Saved your restrictions', self.chat(declaration, message_id='restriction-1'))
        self.model.interpret.assert_not_called()
        self.chat(FIXTURE['natural_intake'], message_id='intake-1')
        self.fetcher.fetch.assert_called_once()
        self.assertEqual(self.state()['fields']['invocation'], 'GET https://jsonplaceholder.typicode.com/posts/1')
        self.assertIn('Draft v', self.chat('draft'))
        state=self.state(); restrictions=state['restrictions']
        self.assertTrue(restrictions['demonstration_only'])
        self.assertTrue(restrictions['third_party_non_ownership'])
        self.assertTrue(restrictions['not_representing_maintainers'])
        self.assertEqual(restrictions['commercial_authorization'], 'explicitly_restricted')
        self.assertTrue(any(x['message_id']=='restriction-1' for x in restrictions['sources']))
        for command, path in [('export json',('draft','restrictions')), ('export buyer',('restrictions',)), ('export representation',('original_draft','restrictions'))]:
            value=json.loads(self.chat(command))
            for key in path:value=value[key]
            self.assertEqual(value,restrictions)
        self.assertIn('Demonstration only', self.chat('export readable'))
        self.assertIn('Seller discloses third-party ownership',self.chat('buyer explanation'))
        for command in ('offer approve','check','transaction open buyer=ignored','publish'):
            self.assertIn('blocked',self.chat(command).lower())
        self.checkout.prepare.assert_not_called()
        self.chat('pricing: USD 0 for this demonstration only')
        self.chat('draft')
        recovered=Workflow(store=self.store, fetcher=self.fetcher)
        self.assertEqual(json.loads(recovered.handle('seller','session','export json'))['draft']['restrictions'],self.state()['restrictions'])
        self.assertTrue(all(source in self.state()['restrictions']['sources'] for source in restrictions['sources']))
        self.assertEqual(self.client.chat.completions.create.call_count,1)  # successful extraction cached

    def test_restriction_after_existing_draft_invalidates_without_rewriting_history(self):
        self.chat(FIXTURE['natural_intake']); self.chat('draft limited')
        prior=copy.deepcopy(self.state()['draft'])
        self.chat(FIXTURE['restriction_message'])
        self.assertEqual(self.state()['draft'],prior)
        exported=json.loads(self.chat('export representation'))
        self.assertTrue(exported['draft_outdated'])
        self.assertTrue(exported['current_restrictions']['third_party_non_ownership'])
        self.assertIn('blocked',self.chat('offer approve'))

    def test_recover_only_retained_literal_user_history(self):
        state=self.state(); state['conversation']=[{'role':'assistant','content':FIXTURE['restriction_message']}]
        self.store.save(self.store.key('seller','session'),state)
        self.assertIn('not established',self.chat('status'))
        state['conversation'].append({'role':'user','content':FIXTURE['restriction_message']})
        self.store.save(self.store.key('seller','session'),state)
        self.chat('status')
        self.assertEqual(self.state()['restrictions']['sources'][0]['origin'],'retained_history')
        self.assertIsNone(self.state()['restrictions']['sources'][0]['message_id'])

    def test_duplicate_envelope_and_restart_do_not_repeat_inference(self):
        self.chat(FIXTURE['natural_intake'],message_id='same')
        saved=self.state()
        self.chat(FIXTURE['natural_intake'],message_id='same')
        self.assertEqual(self.state(),saved)
        self.model.interpret.assert_called_once()
        Workflow(store=self.store,conversation=self.model).handle('seller','session',FIXTURE['natural_intake'],message_id='same')
        self.model.interpret.assert_called_once()

    def test_status_is_deterministic_while_other_operation_is_pending(self):
        entered=threading.Event(); release=threading.Event()
        def waiting(*args):
            entered.set(); release.wait(3)
            return {'action':'reply','reply':'Ready.','updates':{}}
        self.model.interpret.side_effect=waiting
        with ThreadPoolExecutor(max_workers=1) as pool:
            task=pool.submit(self.chat,'Tell me about APIs',message_id='pending')
            self.assertTrue(entered.wait(1))
            self.assertIn('processing',self.chat('status'))
            self.assertIn('No instruction or model request was repeated',self.chat('Tell me about APIs',message_id='pending'))
            self.assertIn('Intake 0/7',self.w.handle('other','other-session','status'))
            release.set(); task.result(2)
        self.model.interpret.assert_called_once()

    def test_model_url_value_is_grounded_without_turning_its_sentence_into_a_url(self):
        from tool_offer_agent.conversation import ConversationInterpreter
        client=Mock()
        text='The API is https://jsonplaceholder.typicode.com/ and the docs are https://jsonplaceholder.typicode.com/.'
        client.chat.completions.create.return_value=model_response({'action':'update','reply':'Understood.', 'updates':[
            {'field':'tool_url','value':'https://jsonplaceholder.typicode.com/','source_quote':'The API is https://jsonplaceholder.typicode.com/'},
            {'field':'docs','value':'https://jsonplaceholder.typicode.com/','source_quote':'the docs are https://jsonplaceholder.typicode.com/'}]})
        w=Workflow(store=self.store,conversation=ConversationInterpreter(client),fetcher=self.fetcher)
        reply=w.handle('url-test','url-session',text)
        state=self.store.load(self.store.key('url-test','url-session'))
        self.assertEqual(state['fields']['tool_url'],'https://jsonplaceholder.typicode.com/')
        self.assertEqual(state['fields']['docs'],['https://jsonplaceholder.typicode.com/'])
        self.assertNotIn('CHAT_',reply)

    def test_hypothetical_and_public_url_do_not_create_authorization(self):
        self.assertFalse(capture(empty(), 'What if I do not own this API?')['third_party_non_ownership'])
        self.assertEqual(capture(empty(),'https://public.example/')['commercial_authorization'],'not_established')


class ExportIntegrityTests(StoreTestMixin, TestCase):
    def test_utf8_exact_reconstruction_and_corruption_cases(self):
        raw=json.dumps({'value':'😀é漢字' * 4000},ensure_ascii=False)
        value=snapshot(raw,4,'export representation'); m=value['manifest']
        parts=[part(value,i) for i in range(1,m['total_parts']+1)]
        self.assertEqual(reassemble(m,list(reversed(parts))),raw)
        json.loads(reassemble(m,parts))
        self.assertTrue(all(len(json.dumps(p).encode())<=REPLY_BYTES for p in parts))
        bad_cases=[parts[1:],parts[:1],parts[:-1]+[parts[0]]]
        for attribute,replacement in [('export_id','different'),('revision',9),('data_base64','YQ=='),('sha256','bad')]:
            changed=copy.deepcopy(parts);changed[0][attribute]=replacement;bad_cases.append(changed)
        for bad in bad_cases:
            with self.assertRaises(ValueError):reassemble(m,bad)
        # Exact observed loss patterns: Part 2/2 only and Part 1/5 only.
        for total,received in [(2,2),(5,1)]:
            value=snapshot('x'*(3000*total-1),4,'export json')
            self.assertEqual(value['manifest']['total_parts'],total)
            with self.assertRaisesRegex(ValueError,'Missing'):
                reassemble(value['manifest'],[part(value,received)])

    def test_snapshot_is_immutable_resumable_idempotent_and_session_bound(self):
        fetcher=FakeFetcher();fetcher.text += ' ' * 6000
        w=Workflow(store=self.store,fetcher=fetcher);w.handle('s','c',INTAKE)
        raw=w.handle('s','c','export json')
        m=json.loads(w.render_response('s','c',raw,'export json'))
        self.assertFalse(m['complete_payload'])
        command=f"export part {m['export_id']} 1"
        first=w.handle('s','c',command)
        self.assertEqual(w.handle('s','c',command),first)
        w.handle('s','c','pricing: USD 9')
        restarted=Workflow(store=self.store)
        self.assertEqual(restarted.handle('s','c',command),first)
        self.assertIn('unavailable',restarted.handle('other','c',command))
        parts=[json.loads(restarted.handle('s','c',f"export part {m['export_id']} {i}")) for i in range(1,m['total_parts']+1)]
        self.assertEqual(reassemble(m,parts),raw)


class ExtractionClassificationTests(TestCase):
    def test_success_offsets_and_light_reasoning_request(self):
        client=Mock();doc=FIXTURE['document'];quote='JSONPlaceholder'
        client.chat.completions.create.return_value=model_response({**{n:[] for n in CATEGORIES},'capabilities':[{'text':quote,'source_url':doc['source_url']}]})
        result=OpenAIQuoteExtractor(client).extract([doc])
        item=result['capabilities'][0]
        start,end=map(int,item['location'][5:-1].split(':'))
        self.assertEqual(doc['text'][start:end],quote)
        self.assertEqual(client.chat.completions.create.call_args.kwargs['reasoning_effort'],'low')
        client.chat.completions.create.assert_called_once()

    def test_timeout_connection_parsing_and_quote_failures_are_distinct(self):
        for error,code in [(TimeoutError('private'),'MODEL_TIMEOUT'),(ConnectionError('private'),'MODEL_CONNECTION'),(ValueError('private'),'MODEL_INVALID_SHAPE')]:
            client=Mock();client.chat.completions.create.side_effect=error
            with self.assertRaises(ExtractionError) as caught:OpenAIQuoteExtractor(client).extract([FIXTURE['document']])
            self.assertEqual(caught.exception.code,code);client.chat.completions.create.assert_called_once()
        for value,code in [('not JSON','MODEL_INVALID_JSON'),(json.dumps({**{n:[] for n in CATEGORIES},'outputs':[{'text':'INVENTED CLAIM','source_url':FIXTURE['document']['source_url']}]}),'MODEL_UNGROUNDED_QUOTE')]:
            client=Mock();client.chat.completions.create.return_value=model_response({})
            client.chat.completions.create.return_value.choices[0].message.content=value
            with self.assertRaises(ExtractionError) as caught:OpenAIQuoteExtractor(client).extract([FIXTURE['document']])
            self.assertEqual(caught.exception.code,code)

    def test_indexed_quotes_use_exact_source_ranges_and_reject_invalid_ids(self):
        client=Mock();doc={'source_url':'https://docs.example.com/','text':'Feature heading\nInputs: CSV\nOutputs: JSON'}
        client.chat.completions.create.return_value=model_response({**{n:[] for n in CATEGORIES},'inputs':[{'quote_id':1,'scope_id':0}]})
        extracted=OpenAIQuoteExtractor(client).extract([doc])
        self.assertEqual(extracted['inputs'][0]['text'],'Inputs: CSV')
        self.assertEqual(extracted['inputs'][0]['scope'],'Feature heading')
        self.assertEqual(extracted['inputs'][0]['location'],'text[16:27]')
        for entry,code in [({'quote_id':999},'MODEL_UNGROUNDED_QUOTE'),({'quote_id':1,'scope_id':2},'MODEL_UNGROUNDED_SCOPE'),({'quote_id':True},'MODEL_UNGROUNDED_QUOTE')]:
            client.chat.completions.create.return_value=model_response({**{n:[] for n in CATEGORIES},'inputs':[entry]})
            with self.assertRaises(ExtractionError) as caught:OpenAIQuoteExtractor(client).extract([doc])
            self.assertEqual(caught.exception.code,code)

    def test_real_sdk_read_timeout_is_classified_without_replay(self):
        import httpx
        from openai import OpenAI
        def timeout(request):
            raise httpx.ReadTimeout("private upstream timeout", request=request)
        transport=httpx.MockTransport(timeout)
        with httpx.Client(transport=transport) as http:
            client=OpenAI(api_key='synthetic-test-only',base_url='https://api.asi1.ai/v1',http_client=http,max_retries=0)
            # Financial admission is tested separately; this fully mocked HTTP
            # transport exercises SDK timeout classification without paid work.
            client._tool_offer_spending_guard = Mock()
            client._tool_offer_spending_guard.reserve.return_value = 0
            with self.assertRaises(ExtractionError) as caught:
                OpenAIQuoteExtractor(client).extract([FIXTURE['document']])
            self.assertEqual(caught.exception.code,'MODEL_TIMEOUT')

    def test_total_inference_attempt_budget_and_usage_metadata(self):
        client=Mock();client.chat.completions.create.return_value=model_response({})
        def operation():
            completion(client,model='asi1');completion(client,model='asi1')
            with self.assertRaisesRegex(RuntimeError,'budget'):completion(client,model='asi1')
        _,events=traced(operation)
        self.assertEqual(len(events),2);self.assertEqual(client.chat.completions.create.call_count,2)
        self.assertTrue(all(e['request_id'] for e in events))


class ActualChatDeliveryTests(StoreTestMixin, IsolatedAsyncioTestCase):
    async def test_one_manifest_then_one_part_per_request_and_exact_reassembly(self):
        fetcher=FakeFetcher();fetcher.text += ' ' * 6000
        w=Workflow(store=self.store,fetcher=fetcher);w.handle('s','c',INTAKE)
        ctx=SimpleNamespace(session='c',send=AsyncMock(),logger=Mock())
        await respond(ctx,'s',create_text_chat('export json'),w)
        self.assertEqual(ctx.send.call_count,2)
        m=json.loads(ctx.send.call_args_list[-1].args[1].text())
        parts=[]
        for i in range(1,m['total_parts']+1):
            ctx.send.reset_mock()
            await respond(ctx,'s',create_text_chat(f"export part {m['export_id']} {i}"),w)
            self.assertEqual(ctx.send.call_count,2)
            body=ctx.send.call_args_list[-1].args[1].text()
            self.assertLessEqual(len(body.encode()),REPLY_BYTES);parts.append(json.loads(body))
        rebuilt=reassemble(m,parts)
        self.assertEqual(json.loads(rebuilt)['draft'],self.store.load(self.store.key('s','c'))['draft'])

    async def test_delivery_failure_and_timeout_do_not_retry(self):
        for error,outcome in [(TimeoutError(),'delivery_timeout'),(RuntimeError('private'),'delivery_exception')]:
            ctx=SimpleNamespace(send=AsyncMock(side_effect=error),logger=Mock())
            self.assertEqual(await bounded_send(ctx,'s',create_text_chat('status'),'id','reply'),outcome)
            ctx.send.assert_called_once()
            self.assertNotIn('private',str(ctx.logger.mock_calls))
