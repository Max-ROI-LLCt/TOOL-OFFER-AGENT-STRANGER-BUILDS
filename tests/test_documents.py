import io
import socket
import time
from unittest import TestCase
from unittest.mock import Mock, patch

from tool_offer_agent.documents import DocumentError, PublicDocumentFetcher, validate_url


def dns(addresses):
    return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]


class FakeResponse:
    def __init__(self, body=b"capabilities: Test fixture only", status=200, headers=None):
        self.body = io.BytesIO(body)
        self.status = status
        self.headers = {"content-type": "text/plain", **{k.lower(): v for k, v in (headers or {}).items()}}
        self.closed = False

    def getheader(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def read1(self, amount):
        return self.body.read(amount)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.sock = Mock()
        self.requests = []
        self.closed = False

    def request(self, method, target, headers):
        self.requests.append((method, target, headers))

    def getresponse(self):
        # HTTPConnection may detach its socket on Connection: close.
        self.sock = None
        return self.response

    def close(self):
        self.closed = True


class DocumentTests(TestCase):
    def test_blocks_nonpublic_literal_urls_and_credentials(self):
        urls = ["http://localhost", "http://box.local/a", "http://x.internal/", "http://127.0.0.1/", "http://10.0.0.1/", "http://169.254.169.254/", "http://100.64.0.1/", "http://224.0.0.1/", "http://[::1]/", "http://[fc00::1]/", "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::7f00:1]/", "ftp://docs.example.com/", "file:///C:/secret", "https://u:p@docs.example.com/", "http://docs.example.com:8080/", "https://docs.example.com/?access_token=private",  "https://docs.example.com\\@localhost/", "https://docs.example.com/\r\nX:yes"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(DocumentError):
                validate_url(url)

    def test_standard_public_url_and_idna(self):
        self.assertEqual(validate_url("https://docs.example.com:443/a#part"), "https://docs.example.com/a")
        self.assertIn("xn--", validate_url("https://bücher.example/a"))

    def test_all_dns_answers_must_be_public(self):
        for addresses in (["127.0.0.1"], ["93.184.216.34", "192.168.1.1"], ["::1"], ["169.254.169.254"], []):
            factory = Mock()
            fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(addresses)), connection_factory=factory)
            with self.subTest(addresses=addresses), self.assertRaises(DocumentError):
                fetcher.fetch("https://docs.example.com/")
            factory.assert_not_called()

    def test_ambiguous_numeric_hosts_resolved_then_blocked(self):
        for url in ("http://127.1/", "http://0177.0.0.1/"):
            factory = Mock()
            fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(["127.0.0.1"])), connection_factory=factory)
            with self.assertRaises(DocumentError):
                fetcher.fetch(url)
            factory.assert_not_called()

    def test_connects_only_pinned_address_and_preserves_host(self):
        resolver = Mock(return_value=dns(["93.184.216.34"]))
        connection = FakeConnection(FakeResponse())
        factory = Mock(return_value=connection)
        fetcher = PublicDocumentFetcher(resolver=resolver, connection_factory=factory)
        result = fetcher.fetch("https://docs.example.com/doc?q=1")
        self.assertEqual(result.source_url, "https://docs.example.com/doc?q=1")
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(factory.call_args.args[:4], ("https", "docs.example.com", 443, "93.184.216.34"))
        self.assertEqual(connection.requests[0][2]["Host"], "docs.example.com")
        self.assertTrue(connection.closed)
        self.assertTrue(connection.response.closed)

    def test_real_connection_uses_tls_original_hostname_and_numeric_socket(self):
        sock = Mock()
        context = Mock()
        with patch("socket.create_connection", return_value=sock) as connect, patch("ssl.create_default_context", return_value=context):
            connection = PublicDocumentFetcher._connection("https", "docs.example.com", 443, "93.184.216.34", 1)
        self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 443))
        context.wrap_socket.assert_called_once_with(sock, server_hostname="docs.example.com")
        self.assertIs(connection.sock, context.wrap_socket.return_value)

    def test_redirects_are_revalidated_and_dns_rebinding_is_blocked(self):
        for destination in ("http://127.0.0.1/", "https://private.example.com/", "https://docs.example.com/new"):
            first = FakeConnection(FakeResponse(status=302, headers={"Location": destination}))
            factory = Mock(return_value=first)
            resolver = Mock(side_effect=[dns(["93.184.216.34"]), dns(["127.0.0.1"])])
            fetcher = PublicDocumentFetcher(resolver=resolver, connection_factory=factory)
            with self.subTest(destination=destination), self.assertRaises(DocumentError):
                fetcher.fetch("https://docs.example.com/")
            self.assertEqual(factory.call_count, 1)
            self.assertTrue(first.closed)

    def test_relative_redirect_and_final_source(self):
        connections = [FakeConnection(FakeResponse(status=302, headers={"Location": "/final"})), FakeConnection(FakeResponse())]
        fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(["93.184.216.34"])), connection_factory=Mock(side_effect=connections))
        doc = fetcher.fetch("https://docs.example.com/start")
        self.assertEqual(doc.requested_url, "https://docs.example.com/start")
        self.assertEqual(doc.source_url, "https://docs.example.com/final")

    def test_redirect_loop_limited(self):
        factory = Mock(side_effect=lambda *args: FakeConnection(FakeResponse(status=302, headers={"Location": "/loop"})))
        fetcher = PublicDocumentFetcher(max_redirects=2, resolver=Mock(return_value=dns(["93.184.216.34"])), connection_factory=factory)
        with self.assertRaises(DocumentError):
            fetcher.fetch("https://docs.example.com/")
        self.assertEqual(factory.call_count, 3)

    def test_size_content_type_compression_and_http_errors(self):
        responses = [FakeResponse(b"x" * 65), FakeResponse(headers={"Content-Length": "65"}), FakeResponse(headers={"Content-Length": "invalid"}), FakeResponse(headers={"Content-Type": "application/octet-stream"}), FakeResponse(headers={"Content-Encoding": "gzip"}), FakeResponse(status=403), FakeResponse(b"")]
        for response in responses:
            fetcher = PublicDocumentFetcher(max_bytes=64, resolver=Mock(return_value=dns(["93.184.216.34"])), connection_factory=Mock(return_value=FakeConnection(response)))
            with self.subTest(response=response.headers), self.assertRaises(DocumentError):
                fetcher.fetch("https://docs.example.com/")

    def test_large_html_shell_with_small_documentation_is_accepted(self):
        body = b'<script>' + b'x' * 200000 + b'</script><p>Inputs: latitude and longitude</p>'
        response = FakeResponse(body, headers={'Content-Type': 'text/html', 'Content-Length': str(len(body))})
        fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(['93.184.216.34'])), connection_factory=Mock(return_value=FakeConnection(response)))
        doc = fetcher.fetch('https://docs.example.com/')
        self.assertEqual(doc.text, 'Inputs: latitude and longitude')

    def test_default_wire_limit_still_rejects_oversized_html(self):
        response = FakeResponse(headers={'Content-Type': 'text/html', 'Content-Length': str(2097153)})
        fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(['93.184.216.34'])), connection_factory=Mock(return_value=FakeConnection(response)))
        with self.assertRaisesRegex(DocumentError, 'size limit'):
            fetcher.fetch('https://docs.example.com/')

    def test_text_budget_is_independent_and_counts_utf8_bytes(self):
        for media, body in [('text/plain', 'é' * 9), ('text/html', '<p>' + 'é' * 9 + '</p>')]:
            response = FakeResponse(body.encode('utf-8'), headers={'Content-Type': media})
            fetcher = PublicDocumentFetcher(max_text_bytes=16, resolver=Mock(return_value=dns(['93.184.216.34'])), connection_factory=Mock(return_value=FakeConnection(response)))
            with self.subTest(media=media), self.assertRaisesRegex(DocumentError, 'text size limit'):
                fetcher.fetch('https://docs.example.com/')

    def test_html_scripts_not_in_evidence(self):
        response = FakeResponse(b"<h1>Capability: Convert rows</h1><script>SECRET_SCRIPT</script><p>Inputs: CSV</p>", headers={"Content-Type": "text/html; charset=utf-8"})
        fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(["93.184.216.34"])), connection_factory=Mock(return_value=FakeConnection(response)))
        doc = fetcher.fetch("https://docs.example.com/")
        self.assertNotIn("SECRET_SCRIPT", doc.text)
        self.assertIn("Inputs: CSV", doc.text)

    def test_html_table_preserves_cells_without_script_content(self):
        body = b"<table><tr><th>Parameter</th><th>Format</th><th>Required</th><th>Description</th></tr><tr><td>latitude</td><td>Float</td><td>Yes</td><td>Coordinate<script>not evidence</script></td></tr></table>"
        response = FakeResponse(body, headers={"Content-Type": "text/html"})
        fetcher = PublicDocumentFetcher(resolver=Mock(return_value=dns(["93.184.216.34"])), connection_factory=Mock(return_value=FakeConnection(response)))
        text = fetcher.fetch("https://docs.example.com/").text
        self.assertIn("latitude | Float | Yes | Coordinate", text)
        self.assertNotIn("not evidence", text)

    def test_dns_timeout_is_bounded_and_never_connects(self):
        def slow(*args):
            time.sleep(0.08)
            return dns(["93.184.216.34"])
        factory = Mock()
        fetcher = PublicDocumentFetcher(timeout=0.01, resolver=slow, connection_factory=factory)
        with self.assertRaises(DocumentError):
            fetcher.fetch("https://docs.example.com/")
        factory.assert_not_called()

    def test_wall_deadline_interrupts_slow_headers(self):
        connection = FakeConnection(FakeResponse())
        sock = connection.sock
        def slow_headers():
            time.sleep(0.04)
            return connection.response
        connection.getresponse = slow_headers
        fetcher = PublicDocumentFetcher(timeout=0.02, resolver=Mock(return_value=dns(["93.184.216.34"])), connection_factory=Mock(return_value=connection))
        with self.assertRaises(DocumentError):
            fetcher.fetch("https://docs.example.com/")
        sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        self.assertTrue(connection.closed)

    def test_service_errors_are_redacted(self):
        fetcher = PublicDocumentFetcher(resolver=Mock(side_effect=OSError("sensitive resolver details")))
        with self.assertRaises(DocumentError) as error:
            fetcher.fetch("https://docs.example.com/")
        self.assertNotIn("sensitive", str(error.exception))
