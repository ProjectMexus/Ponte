import tempfile
import unittest
from pathlib import Path

from mock_backends.core.ids import TextFileIdGenerator
from mock_backends.core.persistence import JsonLinesTextRepository


class TextFileIdGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_text_file_generator_continues_after_reopen(self):
        path = Path(self.temp_dir.name) / "sequences.txt"
        first = TextFileIdGenerator(JsonLinesTextRepository(path))

        self.assertEqual(first.next("APT"), "APT-0001")
        self.assertEqual(first.next("APT"), "APT-0002")

        reopened = TextFileIdGenerator(JsonLinesTextRepository(path))
        self.assertEqual(reopened.next("APT"), "APT-0003")
        self.assertEqual(reopened.next("TASK"), "TASK-0001")

        records = JsonLinesTextRepository(path).list()
        self.assertEqual({record["prefix"] for record in records}, {"APT", "TASK"})
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
