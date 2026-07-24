import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "tme3bot"


class ArchitectureBoundaryTests(unittest.TestCase):
    def imported_modules(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_domain_application_and_worker_do_not_import_telegram_or_fastapi(self):
        for folder in ("domain", "application", "worker"):
            for path in (ROOT / folder).glob("*.py"):
                imports = self.imported_modules(path)
                forbidden = {
                    item
                    for item in imports
                    if item == "telegram"
                    or item.startswith("telegram.")
                    or item == "fastapi"
                    or item.startswith("fastapi.")
                }
                self.assertEqual(forbidden, set(), f"{path}: {forbidden}")

    def test_telegram_frontend_has_no_direct_domain_runtime_dependencies(self):
        imports = self.imported_modules(
            ROOT / "frontend" / "telegram" / "app.py"
        )
        forbidden = {
            "tme3bot.profiles",
            "tme3bot.storage_catalog",
            "tme3bot.worker_registry",
            "tme3bot.tdl",
            "tme3bot.service",
        }
        self.assertFalse(imports & forbidden)

    def test_worker_job_schema_has_no_panel_metadata(self):
        tree = ast.parse(
            (ROOT / "api" / "schemas.py").read_text(encoding="utf-8")
        )
        worker_job = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "WorkerJobRequest"
        )
        fields = {
            node.target.id
            for node in worker_job.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
        }
        for field in (
            "chat_id",
            "message_id",
            "reply_to_message_id",
            "panel_view_token",
        ):
            self.assertNotIn(field, fields)


if __name__ == "__main__":
    unittest.main()
