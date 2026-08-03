import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from middleware.config import load_dotenv


class ConfigTests(unittest.TestCase):
    def test_load_dotenv_reads_values_and_export_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "PONTE_BACKEND_URL=http://127.0.0.1:8080\n"
                "export PONTE_LLM_MODEL=\"test-model\"\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_dotenv(env_path)
                self.assertEqual(loaded["PONTE_LLM_MODEL"], "test-model")
                self.assertEqual(os.environ["PONTE_BACKEND_URL"], "http://127.0.0.1:8080")

    def test_shell_environment_takes_precedence_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("PONTE_LLM_MODEL=from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {"PONTE_LLM_MODEL": "from-shell"}, clear=True):
                load_dotenv(env_path)
                self.assertEqual(os.environ["PONTE_LLM_MODEL"], "from-shell")


if __name__ == "__main__":
    unittest.main()
