import tempfile
import unittest
from pathlib import Path

from mock_backends.core.errors import DomainError
from mock_backends.core.idempotency import (
    RepositoryIdempotencyStore,
    canonical_json_hash,
)
from mock_backends.core.persistence import JsonLinesTextRepository


class IdempotencyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        repo = JsonLinesTextRepository(Path(self.temp_dir.name) / "idempotency.txt", id_field="id")
        self.store = RepositoryIdempotencyStore(repo)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_miss_and_same_scope_hit(self):
        self.assertIsNone(self.store.lookup("USR-1:/submit", "KEY-1"))
        response = {"status": 201, "body": {"id": "A-1"}}
        request_hash = canonical_json_hash({"name": "陳"})
        self.store.remember("USR-1:/submit", "KEY-1", request_hash, response)
        self.assertEqual(
            self.store.lookup("USR-1:/submit", "KEY-1"),
            {"request_hash": request_hash, "response": response},
        )

    def test_scope_isolation(self):
        self.store.remember("USR-1:/submit", "KEY-1", "hash", {"status": 201})
        self.assertIsNone(self.store.lookup("USR-2:/submit", "KEY-1"))
        self.assertIsNone(self.store.lookup("USR-1:/other", "KEY-1"))

    def test_conflicting_hash_raises_domain_error(self):
        self.store.remember("USR-1:/submit", "KEY-1", "hash-a", {"status": 201})
        with self.assertRaises(DomainError) as raised:
            self.store.remember("USR-1:/submit", "KEY-1", "hash-b", {"status": 201})
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")

    def test_reopen_replays_response(self):
        temp_path = Path(self.temp_dir.name) / "reopen.txt"
        first = RepositoryIdempotencyStore(JsonLinesTextRepository(temp_path, id_field="id"))
        first.remember("USR-1:/submit", "KEY-1", "hash", {"status": 201, "body": {"ok": True}})
        second = RepositoryIdempotencyStore(JsonLinesTextRepository(temp_path, id_field="id"))
        self.assertEqual(second.lookup("USR-1:/submit", "KEY-1")["response"]["status"], 201)
