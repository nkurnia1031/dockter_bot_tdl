import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "utility" / "pindah" / "pindah.py"


def load_pindah_module():
    spec = importlib.util.spec_from_file_location("pindah_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PindahSettingsTests(unittest.TestCase):
    def test_group_limit_uses_utility_move_size_environment(self):
        pindah = load_pindah_module()
        with patch.dict(os.environ, {"UTILITY_MOVE_SIZE": "750m"}, clear=False):
            self.assertEqual(pindah.move_size_limit(), 750 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
