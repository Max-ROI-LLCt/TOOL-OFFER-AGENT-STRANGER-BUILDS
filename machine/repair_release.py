"""Targeted native repair through the existing flat-build and avctl push path.

Preserves the complete deployed machine contract, profile and website. No local
Markdown surface is accessed. Host revision and source hashes identify this repair;
the unchanged machine contract release continues to bind adapter clients.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time
import tomllib

import release
from build_hosted import build

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'data/acceptance-nov02'
MODULES = ('product_policy', 'conversation', 'workflow', 'chat')


def read(path):
    return json.loads(path.read_text())


def hashes(source):
    return {name: sha256(text.encode()).hexdigest() for name, text in sorted(source.items())}


def stage():
    baseline = release.sources(read(WORK / 'baseline/code.json'))
    candidate = WORK / 'candidate'
    candidate.mkdir(exist_ok=False)
    for name, text in baseline.items():
        (candidate / name).write_text(text)
    build(candidate, modules=MODULES)
    staged = {path.name: path.read_text() for path in candidate.glob('*.py')}
    for name, text in staged.items():
        compile(text, name, 'exec')
    changed = sorted(name for name in baseline if staged[name] != baseline[name])
    assert changed and set(changed).issubset({name + '.py' for name in MODULES})
    contract = read(ROOT / 'site/src/generated.json')
    manifest = {'baseline_revision': read(WORK / 'baseline/metadata.json')['revision'],
                'baseline_digest': read(WORK / 'baseline/code.json')['digest'],
                'machine_contract_release_id_preserved': contract['release_id'],
                'changed_modules': changed, 'source_hashes': hashes(staged),
                'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'profile_preserved': True, 'website_changed': False,
                'payment_calls': 0, 'external_publication_calls': 0}
    manifest['repair_id'] = sha256(json.dumps(manifest['source_hashes'], sort_keys=True).encode()).hexdigest()
    (WORK / 'repair-manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def verified_candidate():
    manifest = read(WORK / 'repair-manifest.json')
    source = {path.name: path.read_text() for path in (WORK / 'candidate').glob('*.py')}
    assert hashes(source) == manifest['source_hashes'], 'Candidate drift'
    assert manifest['source_commit'] == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'Commit drift'
    return manifest, source


def push_context(profile, address):
    """AVCTL implicitly uploads configured readme even with explicit -f.

    Isolate that behavior using the exact API-read profile in a text file; never
    let the CLI discover the working checkout's configured Markdown path.
    """
    context = WORK / 'push-context'
    (context / '.avctl').mkdir(parents=True, exist_ok=True)
    (context / 'profile.txt').write_text(profile['profile']['readme'])
    local = tomllib.loads((ROOT / '.avctl/config.toml').read_text())['agent']
    assert local['address'] == address
    local['readme_path'] = 'profile.txt'
    (context / '.avctl/config.toml').write_text(
        '[agent]\n' + ''.join(name + ' = ' + json.dumps(value) + '\n' for name, value in local.items()))
    (context / 'pyproject.toml').write_text((ROOT / 'pyproject.toml').read_text().replace('readme = "README.md"', 'readme = "profile.txt"'))
    (context / 'agent.py').write_text((WORK / 'candidate/agent.py').read_text())
    return context


def deploy():
    manifest, candidate = verified_candidate()
    baseline = read(WORK / 'baseline/code.json')
    current = release.live()
    assert current['metadata']['running'] and current['metadata']['compiled']
    assert current['metadata']['revision'] == manifest['baseline_revision'], 'Revision drift'
    assert current['code']['digest'] == manifest['baseline_digest'], 'Digest drift'
    assert release.sources(current['code']) == release.sources(baseline), 'Source drift'
    assert current['profile'] == read(WORK / 'baseline/profile.json'), 'Profile drift'
    address = read(ROOT / 'machine/contract.json')['agent_address']
    local = tomllib.loads((ROOT / '.avctl/config.toml').read_text())
    assert local['agent']['address'] == address
    context = push_context(current['profile'], address)
    result = read(WORK / 'staged-test-result.json')
    assert result['passed'] and result['repair_id'] == manifest['repair_id'], 'Tests not bound to candidate'
    subprocess.run([release.AVCTL, 'hosting', 'stop', '-a', address], check=True, timeout=90)
    try:
        subprocess.run([release.AVCTL, 'hosting', 'push', '-a', address, '-f', ','.join(str(WORK / 'candidate' / name) for name in candidate)], cwd=context, check=True, timeout=120)
    finally:
        subprocess.run([release.AVCTL, 'hosting', 'run', '-a', address], check=True, timeout=90)
    for _ in range(8):
        current = release.live()
        if current['metadata']['running'] and current['metadata']['compiled']:
            break
        time.sleep(3)
    assert current['metadata']['running'] and current['metadata']['compiled']
    assert hashes(release.sources(current['code'])) == manifest['source_hashes'], 'Live source mismatch'
    assert current['profile'] == read(WORK / 'baseline/profile.json'), 'Profile changed'
    (WORK / 'deployed-code.json').write_text(json.dumps(current['code']))
    receipt = {**manifest, 'deployed_revision': current['metadata']['revision'],
               'deployed_digest': current['code']['digest'], 'running': True, 'compiled': True,
               'verified_at': datetime.now(timezone.utc).isoformat(), 'agent_address': address}
    (WORK / 'repair-receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'deploy'])
    parser.add_argument('--work', type=Path, default=WORK)
    args = parser.parse_args()
    WORK = args.work.resolve()
    stage() if args.action == 'stage' else deploy()
