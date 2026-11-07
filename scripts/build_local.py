"""Build an inspectable Agentverse artifact locally. Never uploads or deploys."""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_hosted import build, validate_import_graph

destination = build(ROOT / 'build' / 'hosted')
(destination / '__init__.py').write_text((ROOT / 'tool_offer_agent' / '__init__.py').read_text())
sources = {path.name: path.read_text() for path in destination.glob('*.py')}
validate_import_graph(sources)
manifest = {'scope': 'LOCAL REPRODUCIBLE HOSTED BUILD; THIS COMMAND DOES NOT DEPLOY', 'files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sorted(sources.items())}}
(destination.parent / 'local-source.json').write_text(json.dumps(manifest, indent=2)+'\n')
print('Built local hosted modules; no network or deployment performed.')
