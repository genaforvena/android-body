#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""A deliberately small, single-process, durable HTTP text rendezvous.

Python 3.10+ on Unix. No third-party packages. Run --help for configuration.
The Android phone does not need Python or any other companion runtime.
"""
from __future__ import annotations

import argparse
from array import array
import fcntl
import hmac
import ipaddress
import os
from pathlib import Path
import re
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_ID = 9_007_199_254_740_991
MAX_BODY_BYTES = 65_536
MAX_WIRE_LINE_BYTES = 1_024  # Not counting the final LF.
MAX_INPUT_LINE_BYTES = MAX_WIRE_LINE_BYTES - 17  # ID (16 digits) + one space.
MAX_BATCH_RECORDS = 128
DEFAULT_QUEUE_BYTES = 16 * 1024 * 1024
NODE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
TOKEN_RE = re.compile(r"[A-Za-z0-9._~-]+")
ROUTE_RE = re.compile(r"/node/([a-z0-9][a-z0-9_-]{0,63})/(actions|observations)(?:\?after=(0|[1-9][0-9]{0,15}))?")


class ProtocolError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def validate_line(line: bytes) -> str:
    if not line or len(line) > MAX_INPUT_LINE_BYTES:
        raise ProtocolError(400, "empty_or_oversized_line")
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(400, "invalid_utf8") from exc
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 or c in "\u2028\u2029\ufeff" for c in text):
        raise ProtocolError(400, "control_character")
    if not text.strip():
        raise ProtocolError(400, "blank_line")
    return text


def parse_body(body: bytes) -> list[bytes]:
    if not body or len(body) > MAX_BODY_BYTES:
        raise ProtocolError(400, "empty_or_oversized_body")
    lines = body.removesuffix(b"\n").split(b"\n")
    if len(lines) > MAX_BATCH_RECORDS:
        raise ProtocolError(400, "too_many_lines")
    for line in lines:
        validate_line(line)
    return lines


def valid_secret(value: str) -> bool:
    return 32 <= len(value) <= 256 and TOKEN_RE.fullmatch(value) is not None


class Queue:
    """One append-only text file. Only acknowledged appends are guaranteed durable.

    A torn/corrupt file fails closed on startup; there is no silent tail repair.
    This is not a transaction log: an interrupted POST can append some/all data.
    """

    def __init__(self, path: Path, max_bytes: int):
        self.lock = threading.Lock()
        self.max_bytes = max_bytes
        self.failed = False
        self.offsets = array("Q")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.file = os.fdopen(fd, "r+b", buffering=0)
        try:
            self.size = os.fstat(fd).st_size
            if self.size > max_bytes:
                raise ValueError(f"Queue exceeds configured size limit: {path.name}")
            offset = 0
            for expected in range(1, MAX_ID + 1):
                wire = self.file.readline(MAX_WIRE_LINE_BYTES + 2)
                if not wire:
                    break
                if len(wire) > MAX_WIRE_LINE_BYTES + 1 or not wire.endswith(b"\n"):
                    raise ValueError(f"Incomplete or oversized record in {path.name}")
                seq, sep, line = wire[:-1].partition(b" ")
                if not sep or seq != str(expected).encode("ascii"):
                    raise ValueError(f"Non-contiguous sequence in {path.name}")
                try:
                    validate_line(line)
                except ProtocolError as exc:
                    raise ValueError(f"Invalid record in {path.name}: {exc.message}") from exc
                self.offsets.append(offset)
                offset += len(wire)
            if offset != self.size:
                raise ValueError(f"Invalid queue length in {path.name}")
        except Exception:
            self.file.close()
            raise

    @property
    def head(self) -> int:
        return len(self.offsets)

    def append(self, lines: list[bytes]) -> list[int]:
        with self.lock:
            if self.failed:
                raise ProtocolError(503, "queue_requires_restart_and_inspection")
            if self.head + len(lines) > MAX_ID:
                raise ProtocolError(507, "sequence_limit_reached")
            ids = list(range(self.head + 1, self.head + len(lines) + 1))
            records = [str(seq).encode("ascii") + b" " + line + b"\n" for seq, line in zip(ids, lines)]
            payload = b"".join(records)
            if self.size + len(payload) > self.max_bytes:
                raise ProtocolError(507, "queue_full")
            # O_APPEND and the process lock prevent overwrite/concurrent writers.
            try:
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(self.file.fileno(), remaining)
                    if written == 0:
                        raise OSError("zero-byte append")
                    remaining = remaining[written:]
                os.fsync(self.file.fileno())
            except OSError as exc:
                # An ambiguous append must never be followed by reused IDs.
                self.failed = True
                raise ProtocolError(503, "append_uncertain_inspect_queue") from exc
            for record in records:
                self.offsets.append(self.size)
                self.size += len(record)
            return ids

    def read(self, after: int) -> tuple[bytes, int, bool]:
        with self.lock:
            if self.failed:
                raise ProtocolError(503, "queue_requires_restart_and_inspection")
            if after > self.head:
                raise ProtocolError(409, "cursor_ahead_of_queue")
            if after == self.head:
                return b"", after, False
            self.file.seek(self.offsets[after])
            chunks: list[bytes] = []
            total = 0
            last = after
            while last < self.head and len(chunks) < MAX_BATCH_RECORDS:
                wire = self.file.readline(MAX_WIRE_LINE_BYTES + 2)
                if total + len(wire) > MAX_BODY_BYTES:
                    break
                chunks.append(wire)
                total += len(wire)
                last += 1
            return b"".join(chunks), last, last < self.head

    def close(self) -> None:
        self.file.close()


class Store:
    def __init__(self, directory: Path, secrets: dict[str, str], max_queue_bytes: int = DEFAULT_QUEUE_BYTES):
        if not secrets or len(secrets) > 64:
            raise ValueError("Configure between 1 and 64 nodes")
        if max_queue_bytes < MAX_WIRE_LINE_BYTES + 1:
            raise ValueError("max_queue_bytes must be at least 1025")
        for node, secret in secrets.items():
            if not NODE_RE.fullmatch(node) or not valid_secret(secret):
                raise ValueError("Invalid node ID or secret")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secrets = {node: secret.encode("ascii") for node, secret in secrets.items()}
        self.queues: dict[tuple[str, str], Queue] = {}
        self.lockfile = None
        try:
            fd = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            self.lockfile = os.fdopen(fd, "r+b")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Another server already owns this data directory") from exc
            for node in secrets:
                for kind in ("actions", "observations"):
                    self.queues[(node, kind)] = Queue(directory / f"{node}.{kind}.log", max_queue_bytes)
            # Persist newly created directory entries before accepting appends.
            dirfd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except Exception:
            self.close()
            raise

    def authorized(self, node: str, authorization: str) -> bool:
        expected = self.secrets.get(node)
        # Also run the constant-time comparison for unknown nodes.
        token = authorization.removeprefix("Bearer ").encode("utf-8")
        matched = hmac.compare_digest(token, expected or b"0" * 64)
        return expected is not None and authorization.startswith("Bearer ") and matched

    def close(self) -> None:
        for queue in self.queues.values():
            queue.close()
        self.queues.clear()
        if self.lockfile is not None:
            self.lockfile.close()
            self.lockfile = None


class Server(ThreadingHTTPServer):
    daemon_threads = False  # Drain bounded in-flight requests before closing the store.
    request_queue_size = 32

    def __init__(self, address: tuple[str, int], store: Store):
        self.store = store
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        # Bound worker count even if clients hold connections open.
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.0"  # One bounded request per connection.
    server_version = "AndroidBodyRendezvous/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, _format, *_args):
        pass  # Avoid leaking request paths, tokens, or sensor contents.

    def send_text(self, status: int, body: bytes, headers: dict[str, str] | None = None):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        # BaseHTTPRequestHandler otherwise emits HTML for parser errors.
        self.send_text(code, f"error http_{code}\n".encode("ascii"))

    def route(self) -> tuple[str, str, int | None]:
        match = ROUTE_RE.fullmatch(self.path)
        if not match:
            raise ProtocolError(404, "unknown_route")
        node, kind, after_text = match.groups()
        authorizations = self.headers.get_all("Authorization", [])
        if len(authorizations) != 1 or not self.server.store.authorized(node, authorizations[0]):
            raise ProtocolError(401, "unauthorized")
        after = int(after_text) if after_text is not None else None
        if after is not None and after > MAX_ID:
            raise ProtocolError(400, "cursor_out_of_range")
        return node, kind, after

    def do_GET(self):
        self.handle_operation(False)

    def do_POST(self):
        self.handle_operation(True)

    def handle_operation(self, write: bool):
        try:
            node, kind, after = self.route()
            if self.headers.get_all("Transfer-Encoding"):
                raise ProtocolError(400, "transfer_encoding_unsupported")
            if self.headers.get_all("Content-Encoding"):
                raise ProtocolError(415, "content_encoding_unsupported")
            if len(self.headers.get_all("Content-Length", [])) > 1:
                raise ProtocolError(400, "duplicate_content_length")
            if self.headers.get_all("Expect"):
                raise ProtocolError(417, "expect_unsupported")
            if write:
                if after is not None:
                    raise ProtocolError(400, "post_does_not_take_cursor")
                types = self.headers.get_all("Content-Type", [])
                if len(types) != 1 or types[0].lower().replace(" ", "") not in ("text/plain", "text/plain;charset=utf-8"):
                    raise ProtocolError(415, "require_text_plain_utf8")
                lengths = self.headers.get_all("Content-Length", [])
                if not lengths:
                    raise ProtocolError(411, "content_length_required")
                if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,6}", lengths[0]):
                    raise ProtocolError(400, "invalid_content_length")
                size = int(lengths[0])
                if size > MAX_BODY_BYTES:
                    raise ProtocolError(413, "body_too_large")
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ProtocolError(400, "incomplete_body")
                ids = self.server.store.queues[(node, kind)].append(parse_body(body))
                self.send_text(201, b"".join(f"{seq}\n".encode("ascii") for seq in ids))
            else:
                if self.headers.get("Content-Length", "0") != "0":
                    raise ProtocolError(400, "get_body_unsupported")
                if after is None:
                    raise ProtocolError(400, "get_requires_after_cursor")
                body, last, more = self.server.store.queues[(node, kind)].read(after)
                self.send_text(200, body, {"X-Last-Sequence": str(last), "X-Has-More": str(int(more))})
        except ProtocolError as exc:
            headers = {"WWW-Authenticate": 'Bearer realm="android-body"'} if exc.status == 401 else None
            self.send_text(exc.status, f"error {exc.message}\n".encode("ascii"), headers)
        except (TimeoutError, socket.timeout):
            self.send_text(408, b"error request_timeout\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self.send_text(503, b"error storage_unavailable\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="IPv4 bind address (default: loopback)")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--node", action="append", required=True, metavar="ID:SECRET_ENV", help="repeat for each node; read its secret from this environment variable")
    parser.add_argument("--max-queue-bytes", type=int, default=DEFAULT_QUEUE_BYTES)
    parser.add_argument("--allow-insecure-http", action="store_true", help="explicitly allow an unencrypted non-loopback listener")
    args = parser.parse_args(argv)
    try:
        address = ipaddress.ip_address(args.host)
        if address.version != 4:
            raise ValueError("This minimal server accepts an IPv4 bind address")
        if not address.is_loopback and not args.allow_insecure_http:
            raise ValueError("Non-loopback HTTP exposes secrets and data; use --allow-insecure-http only on a trusted test LAN")
        if not 0 <= args.port <= 65535:
            raise ValueError("Port must be between 0 and 65535")
        secrets = {}
        for spec in args.node:
            node, separator, variable = spec.partition(":")
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
                raise ValueError("Use --node ID:SECRET_ENV")
            if node in secrets:
                raise ValueError("Node IDs must not be repeated")
            secret = os.environ.get(variable, "")
            if not valid_secret(secret):
                raise ValueError(f"{variable} must contain a 32–256 character URL-safe token; generate one with secrets.token_hex(32)")
            secrets[node] = secret
        store = Store(args.data_dir, secrets, args.max_queue_bytes)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    try:
        server = Server((args.host, args.port), store)
        print(f"Listening on http://{args.host}:{server.server_port}; {len(secrets)} configured node(s).", flush=True)
        if not address.is_loopback:
            print("WARNING: unencrypted HTTP; use only on a trusted test LAN. Prefer an HTTPS reverse proxy.", file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
