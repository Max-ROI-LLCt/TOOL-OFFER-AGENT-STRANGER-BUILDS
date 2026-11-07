import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from build_hosted import build
from tool_offer_agent.storage import AgentStateStore
from tool_offer_agent.workflow import Workflow


class HostingTests(TestCase):
    def test_flat_build_has_no_relative_or_package_imports(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            build(folder)
            for file in Path(folder).glob('*.py'):
                tree = ast.parse(file.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        self.assertEqual(node.level, 0, str(file))
                        self.assertFalse((node.module or '').startswith('tool_offer_agent'))
            self.assertIn('hosted=True', (Path(folder) / 'agent.py').read_text())
            self.assertNotIn('import', (Path(folder) / 'cli.py').read_text())

    def test_targeted_build_preserves_other_modules_and_entrypoint(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            untouched = {"fahce.py": "# preserved checker\n", "agent.py": "# preserved entrypoint\n"}
            for name, content in untouched.items():
                (Path(folder) / name).write_text(content, encoding="utf-8")
            build(folder, modules=("drafting", "workflow"))
            for name, content in untouched.items():
                self.assertEqual((Path(folder) / name).read_text(encoding="utf-8"), content)
            self.assertEqual({file.name for file in Path(folder).glob("*.py")},
                             {"drafting.py", "workflow.py", "fahce.py", "agent.py"})
            for name in ("drafting.py", "workflow.py"):
                tree = ast.parse((Path(folder) / name).read_text(encoding="utf-8"))
                self.assertTrue(all(node.level == 0 for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)))

    def test_platform_storage_preserves_and_isolates_intake(self):
        values = {}
        storage = Mock()
        storage.get.side_effect = values.get
        storage.set.side_effect = values.__setitem__
        storage.remove.side_effect = values.pop
        workflow = Workflow(store=AgentStateStore(storage))
        workflow.handle('seller', 'session', 'customer: API developers')
        restarted = Workflow(store=AgentStateStore(storage))
        self.assertIn('Intake 1/7', restarted.handle('seller', 'session', 'status'))
        self.assertIn('Intake 0/7', restarted.handle('other', 'session', 'status'))
        self.assertIn('Intake 0/7', restarted.handle('seller', 'other', 'status'))
