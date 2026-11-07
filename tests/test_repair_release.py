"""Offline guard for the CLI's implicit hosted profile upload."""
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tomllib
from unittest import TestCase
from unittest.mock import patch


class RepairReleaseTests(TestCase):
    def test_push_context_preserves_api_profile_without_markdown_files(self):
        machine = Path(__file__).resolve().parents[1] / 'machine'
        sys.path.insert(0, str(machine))
        try:
            spec = importlib.util.spec_from_file_location('repair_release_guard', machine / 'repair_release.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        with TemporaryDirectory() as directory, patch.object(module, 'WORK', Path(directory)):
            (Path(directory) / 'candidate').mkdir()
            (Path(directory) / 'candidate/agent.py').write_text('original_agent = True\n')
            profile = {'profile': {'readme': 'Original hosted profile\nExact public contract.'}}
            address = tomllib.loads((module.ROOT / '.avctl/config.toml').read_text())['agent']['address']
            context = module.push_context(profile, address)
            config = tomllib.loads((context / '.avctl/config.toml').read_text())
            self.assertEqual(config['agent']['address'], address)
            self.assertEqual(config['agent']['readme_path'], 'profile.txt')
            self.assertEqual((context / 'profile.txt').read_text(), profile['profile']['readme'])
            self.assertEqual({p.name for p in context.rglob('*') if p.is_file()}, {'config.toml', 'profile.txt', 'agent.py', 'pyproject.toml'})
            self.assertEqual((context / 'agent.py').read_text(), 'original_agent = True\n')
