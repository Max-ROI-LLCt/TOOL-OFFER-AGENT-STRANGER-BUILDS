"""Verify selected source integrity and retained release reconstruction offline."""

from hashlib import sha256
import gzip
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, 'machine/discovery.py', 'check'], cwd=ROOT, check=True)
manifest = json.loads((ROOT / 'evidence/package-manifest.json').read_text())
for record in manifest['files']:
    path = ROOT / record['path']
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
        raise SystemExit('Missing or unsafe selected path: ' + record['path'])
    data = path.read_bytes()
    if len(data) != record['bytes'] or sha256(data).hexdigest() != record['sha256']:
        raise SystemExit('Selected content changed: ' + record['path'])
baseline_path = ROOT / 'evidence/releases/revision-79'
baseline = json.loads((baseline_path / 'baseline.json').read_text())
archive = (baseline_path / 'hosted-source.json.gz').read_bytes()
assert sha256(archive).hexdigest() == baseline['archive_sha256'], 'Archive bytes changed'
decoded = gzip.decompress(archive)
assert sha256(decoded).hexdigest() == manifest['revision_79_uncompressed_sha256'], 'Reconstructed archive changed'
members = json.loads(decoded)['code']
assert len(members) == len(baseline['modules'])
assert {member['name'] for member in members} == set(baseline['modules'])
for member in members:
    body = member['value'].encode('utf-8')
    expected = baseline['modules'][member['name']]
    assert sha256(body).hexdigest() == expected['sha256'] and len(body) == expected['bytes'], member['name']
print('Verified', len(manifest['files']), 'selected files and all', len(members), 'retained revision-79 source members.')
print('Manifest is an unsigned integrity record, not a deployment or independent provenance attestation.')
