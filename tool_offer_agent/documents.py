"""Bounded public-document GETs with DNS pinning and redirect revalidation."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from html.parser import HTMLParser
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class Document:
    requested_url: str
    source_url: str
    text: str
    media_type: str


def validate_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise DocumentError("Use a public HTTP(S) URL of at most 2048 characters.")
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise DocumentError("URL contains unsafe characters.")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
        if parts.scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None:
            raise ValueError()
        if port not in (None, 443 if parts.scheme == "https" else 80):
            raise ValueError()
        if any(key.lower() in {"api_key", "apikey", "key", "token", "access_token", "secret", "signature", "x-amz-signature", "x-goog-signature"} for key, _ in parse_qsl(parts.query)):
            raise ValueError()
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
        if "%" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-." for c in host):
                raise ValueError()
        else:
            if not public_address(address):
                raise ValueError()
        authority = f"[{host}]" if ":" in host else host
        return urlunsplit((parts.scheme, authority, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError):
        raise DocumentError("Only public HTTP(S) URLs on standard ports, without credentials, are allowed.") from None


def public_address(address):
    # is_global alone includes multicast on some Python versions.
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return public_address(address.ipv4_mapped)
        if address.sixtofour is not None or address.teredo is not None or address not in ipaddress.ip_network("2000::/3"):
            return False
    return address.is_global and not (address.is_multicast or address.is_reserved or address.is_unspecified)


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []
        self.row_cells = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden += 1
        elif tag == "tr":
            self.row_cells = 0
            self.parts.append("\n")
        elif tag in ("th", "td"):
            if self.row_cells:
                self.parts.append(" | ")
            self.row_cells += 1
        elif tag in ("p", "div", "br", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class PublicDocumentFetcher:
    def __init__(self, *, timeout=12.0, max_bytes=2097152, max_text_bytes=131072, max_redirects=3, resolver=None, connection_factory=None):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_text_bytes = max_text_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver or socket.getaddrinfo
        self.connection_factory = connection_factory or self._connection

    @staticmethod
    def _connection(scheme, host, port, address, timeout):
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        # Connect to the validated numeric address, never resolve the host a second time.
        deadline = time.monotonic() + timeout
        sock = socket.create_connection((address, port), timeout=timeout)
        try:
            if scheme == "https":
                sock.settimeout(max(0.001, deadline - time.monotonic()))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            connection.sock = sock
            return connection
        except Exception:
            sock.close()
            raise

    def fetch(self, url: str) -> Document:
        requested = validate_url(url)
        current = requested
        deadline = time.monotonic() + self.timeout

        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise DocumentError("Documentation request timed out.")
            return value

        try:
            for hop in range(self.max_redirects + 1):
                current = validate_url(current)
                parts = urlsplit(current)
                port = 443 if parts.scheme == "https" else 80
                pool = ThreadPoolExecutor(max_workers=1)
                try:
                    future = pool.submit(self.resolver, parts.hostname, port, 0, socket.SOCK_STREAM)
                    records = future.result(timeout=remaining())
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
                addresses = [record[4][0] for record in records]
                if not addresses or any(not public_address(ipaddress.ip_address(a)) for a in addresses):
                    raise DocumentError("Documentation host resolves to a non-public address.")
                conn = self.connection_factory(parts.scheme, parts.hostname, port, addresses[0], remaining())
                sock = conn.sock

                def expire(sock=sock):
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

                watchdog = threading.Timer(remaining(), expire)
                watchdog.daemon = True
                watchdog.start()
                response = None
                try:
                    target = parts.path or "/"
                    if parts.query:
                        target += "?" + parts.query
                    conn.request("GET", target, headers={"Host": parts.netloc, "User-Agent": "ToolOfferAgent/0.2", "Accept": "text/plain,text/html,application/json", "Accept-Encoding": "identity"})
                    sock.settimeout(remaining())
                    response = conn.getresponse()
                    if response.status in (301, 302, 303, 307, 308):
                        if hop == self.max_redirects or not response.getheader("Location"):
                            raise DocumentError("Too many or invalid documentation redirects.")
                        next_url = validate_url(urljoin(current, response.getheader("Location")))
                        if parts.scheme == "https" and urlsplit(next_url).scheme != "https":
                            raise DocumentError("HTTPS downgrade redirects are not allowed.")
                        current = next_url
                        continue
                    if response.status != 200:
                        raise DocumentError(f"Documentation server did not return HTTP 200 (received HTTP {response.status}).")
                    media = response.getheader("Content-Type", "").split(";")[0].lower().strip()
                    if media not in ("text/plain", "text/html", "application/json", "application/openapi+json", "text/markdown"):
                        raise DocumentError("Documentation must be text, HTML, or JSON.")
                    if response.getheader("Content-Encoding", "identity").lower() != "identity":
                        raise DocumentError("Compressed documentation is not accepted.")
                    length = response.getheader("Content-Length")
                    if length is not None and (int(length) < 0 or int(length) > self.max_bytes):
                        raise DocumentError("Documentation exceeds the size limit.")
                    body = bytearray()
                    while True:
                        sock.settimeout(remaining())
                        chunk = response.read1(min(8192, self.max_bytes + 1 - len(body)))
                        if not chunk:
                            break
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise DocumentError("Documentation exceeds the size limit.")
                    remaining()
                    text = body.decode("utf-8", errors="replace")
                    if media == "text/html":
                        parser = _TextParser()
                        parser.feed(text)
                        text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
                    if len(text.encode("utf-8")) > self.max_text_bytes:
                        raise DocumentError("Readable documentation exceeds the text size limit; supply a smaller documentation page.")
                    if not text.strip():
                        raise DocumentError("Documentation contains no readable text.")
                    return Document(requested, current, text, media)
                finally:
                    watchdog.cancel()
                    if response is not None:
                        response.close()
                    conn.close()
        except DocumentError:
            raise
        except (OSError, ValueError, http.client.HTTPException, FutureTimeout):
            raise DocumentError("Documentation could not be fetched safely; retry or supply another public docs URL.") from None
        raise DocumentError("Documentation could not be fetched.")
