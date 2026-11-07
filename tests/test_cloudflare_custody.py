"""Cloudflare custody contract, with opt-in tests against local Wrangler only."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from tests.support import FakeFetcher, INTAKE
from tool_offer_agent.chat import create_agent
from tool_offer_agent.cloudflare_custody import CloudflareTransactionStore, CustodyUnavailable
from tool_offer_agent.storage import StateStore
from tool_offer_agent.workflow import Workflow


class Response(BytesIO):
    pass


class CustodyClientTests(TestCase):
    def test_hosted_factory_uses_optional_custody_without_enabling_spending(self):
        environment = {"TOOL_OFFER_USE_MODEL": "0", "TOOL_OFFER_CUSTODY_URL": "https://example.com/v1/state",
                       "TOOL_OFFER_CUSTODY_TOKEN": "local-test-token", "TOOL_OFFER_ENABLE_TEST_PAYMENTS": "1"}
        with patch.dict(os.environ, environment, clear=True), patch("tool_offer_agent.chat.Agent") as agent_type, patch("tool_offer_agent.chat.Workflow") as workflow:
            create_agent(hosted=True)
        self.assertIsInstance(workflow.call_args.kwargs["transaction_store"], CloudflareTransactionStore)
        self.assertFalse(workflow.call_args.kwargs["local_test"])
        protocols = [call.args[0] for call in agent_type.return_value.include.call_args_list]
        self.assertEqual(len(protocols), 2)
        self.assertEqual({protocol.name for protocol in protocols}, {"AgentChatProtocol", "ToolOfferMachine"})
        self.assertTrue(all(call.kwargs.get("publish_manifest") for call in agent_type.return_value.include.call_args_list))

    def test_rejects_unsecured_remote_endpoints_and_missing_token(self):
        for endpoint in ("http://example.com/v1/state", "https://example.com/other", "https://example.com/v1/state?redirect=x"):
            with self.assertRaises(ValueError):
                CloudflareTransactionStore(endpoint, "test-token")
        with self.assertRaises(ValueError):
            CloudflareTransactionStore("https://example.com/v1/state", "")

    def test_unknown_outcome_does_not_retry_or_expose_transport_error(self):
        requests = []

        def transport(request, timeout):
            requests.append(request)
            raise URLError("credential must not appear in the error")

        store = CloudflareTransactionStore("https://example.com/v1/state", "local-test-token", transport=transport)
        with self.assertRaises(CustodyUnavailable) as error:
            store.compare_and_swap("a" * 64, None, {"commercial_transaction": {"stage": "BUYER_APPROVED"}})
        self.assertNotIn("credential", str(error.exception))
        self.assertEqual(len(requests), 1)

    def test_invalid_acknowledgement_fails_closed(self):
        store = CloudflareTransactionStore("https://example.com/v1/state", "local-test-token", transport=lambda request, timeout: Response(b"{}"))
        with self.assertRaises(CustodyUnavailable):
            store.compare_and_swap("a" * 64, None, {"commercial_transaction": {"stage": "PAYMENT_REQUESTED"}})


@skipUnless(os.getenv("TOOL_OFFER_CUSTODY_TEST_URL") and os.getenv("TOOL_OFFER_CUSTODY_TEST_TOKEN"), "Explicit local Wrangler endpoint and test token required")
class LocalWranglerTests(TestCase):
    def setUp(self):
        self.endpoint = os.environ["TOOL_OFFER_CUSTODY_TEST_URL"]
        self.token = os.environ["TOOL_OFFER_CUSTODY_TEST_TOKEN"]
        self.store = CloudflareTransactionStore(self.endpoint, self.token, allow_local_http=True)

    def test_worker_auth_atomic_cas_and_no_duplicate_authorization(self):
        unauthorized = Request(self.endpoint, data=b'{}', method="POST")
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as error:
            urlopen(unauthorized, timeout=10)
        self.assertEqual(error.exception.code, 401)

        key = self.store.key("tool-offer-commercial-v1", str(uuid4()))
        before = {"commercial_transaction": {"stage": "BUYER_APPROVED", "seller": "agent1seller"}}
        requested = {"commercial_transaction": {"stage": "PAYMENT_REQUESTED", "seller": "agent1seller"}}
        self.assertEqual(self.store.load(key), {})
        self.assertTrue(self.store.compare_and_swap(key, None, before))
        other = CloudflareTransactionStore(self.endpoint, self.token, allow_local_http=True)
        self.assertFalse(other.compare_and_swap(key, None, before))
        self.assertTrue(other.compare_and_swap(key, before, requested))
        self.assertFalse(self.store.compare_and_swap(key, before, requested))
        self.assertEqual(self.store.load(key), requested)

    def test_concurrent_custody_attempts_allow_only_one(self):
        key = self.store.key("tool-offer-commercial-v1", str(uuid4()))
        before = {"commercial_transaction": {"stage": "BUYER_APPROVED"}}
        self.assertTrue(self.store.compare_and_swap(key, None, before))

        def attempt(worker):
            store = CloudflareTransactionStore(self.endpoint, self.token, allow_local_http=True)
            return store.compare_and_swap(key, before, {"commercial_transaction": {"stage": "PAYMENT_REQUESTED", "worker": worker}})

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ("first", "second")))
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(self.store.load(key)["commercial_transaction"]["stage"], "PAYMENT_REQUESTED")

    def test_existing_chat_storage_stays_local_and_transaction_recovers_remotely(self):
        with TemporaryDirectory() as directory:
            session_store = StateStore(directory + "/sessions.sqlite3")
            workflow = Workflow(store=session_store, transaction_store=self.store, fetcher=FakeFetcher(), local_test=True)
            seller = "agent1seller" + uuid4().hex
            buyer = "agent1buyer" + uuid4().hex
            self.assertIn("Draft v", workflow.handle(seller, "session", INTAKE))
            self.assertIn("Seller offer approved", workflow.handle(seller, "session", "offer approve"))
            from datetime import datetime, timedelta, timezone
            deadline = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
            opened = json.loads(workflow.handle(seller, "session", (
                f"transaction open buyer={buyer} method=test_only currency=TEST amount=2.50 "
                f"network=local recipient={seller} deadline={deadline}"
            )))
            transaction_id = opened["transaction_id"]
            self.assertIn("approved", workflow.handle(buyer, "buyer-session", (
                f"transaction approve {transaction_id} test_only TEST 2.50 local {seller} {deadline}"
            )))
            self.assertIn("queued", workflow.handle(seller, "session", f"transaction send {transaction_id}"))
            restored = Workflow(store=session_store, transaction_store=self.store, fetcher=FakeFetcher(), local_test=True)
            self.assertIn("Buyer must approve", restored.handle(seller, "session", f"transaction send {transaction_id}"))
            self.assertEqual(restored.commerce.read(transaction_id)["stage"], "PAYMENT_REQUESTED")
            self.assertEqual(restored.commerce.read(transaction_id)["settlement"], "not_verified")
