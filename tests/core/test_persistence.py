import json
import tempfile
import unittest
from pathlib import Path

from mock_backends.core.persistence import JsonLinesTextRepository, MemoryRepository


class JsonLinesTextRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "records.txt"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_repository_and_reopen(self):
        repo = JsonLinesTextRepository(self.path, id_field="id")
        self.assertEqual(repo.list(), [])

        repo.insert({"id": "REC-1", "status": "new"})
        reopened = JsonLinesTextRepository(self.path, id_field="id")
        self.assertEqual(reopened.get("REC-1")["status"], "new")
        self.assertEqual(len(self.path.read_text(encoding="utf-8").splitlines()), 1)

    def test_replace_does_not_duplicate_record(self):
        repo = JsonLinesTextRepository(self.path, id_field="id")
        repo.insert({"id": "REC-1", "status": "new"})
        repo.replace("REC-1", {"id": "REC-1", "status": "updated"})

        self.assertEqual(repo.list(), [{"id": "REC-1", "status": "updated"}])

    def test_find_and_copy_semantics(self):
        repo = MemoryRepository(id_field="id")
        repo.insert({"id": "REC-1", "kind": "a"})
        records = repo.find(lambda item: item["kind"] == "a")
        records[0]["kind"] = "changed"
        self.assertEqual(repo.get("REC-1")["kind"], "a")

    def test_malformed_line_is_rejected(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("not-json\n", encoding="utf-8")
        repo = JsonLinesTextRepository(self.path, id_field="id")
        with self.assertRaisesRegex(ValueError, "line 1"):
            repo.list()

    def test_blank_line_is_rejected(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n", encoding="utf-8")
        repo = JsonLinesTextRepository(self.path, id_field="id")
        with self.assertRaisesRegex(ValueError, "line 1"):
            repo.list()


if __name__ == "__main__":
    unittest.main()
