"""Disposable signed-ACP acceptance, not a native ASI browser interaction."""

import hashlib
import json
from uuid import uuid4

from tests.support import card_selection
from tool_offer_agent.export_delivery import reassemble


async def exercise(ask, stored_state, receipt):
    customer = 'Independent shipping-form developers'
    exports = []
    action_cases = []

    def payload(metadata):
        return json.loads(metadata[0]['card_payload'])

    async def complete(session, command):
        text, _ = await ask(session, command)
        manifest = json.loads(text) if text.startswith('{') else {}
        if manifest.get('schema') != 'TOOL_OFFER_EXPORT_MANIFEST_V1':
            return text, None
        parts = []
        for index in range(1, manifest['total_parts'] + 1):
            part, _ = await ask(session, f"export part {manifest['export_id']} {index}")
            parts.append(json.loads(part))
        text = reassemble(manifest, parts)
        exports.append({'command': command, 'revision': manifest['revision'], 'parts': len(parts),
                        'bytes': len(text.encode()), 'sha256': hashlib.sha256(text.encode()).hexdigest()})
        return text, manifest

    async def fresh(origin):
        session = uuid4()
        _, metadata = await ask(session, 'what do you do?', card_kind='custom')
        example = payload(metadata)['root']['children'][-1]['action']['selection']
        _, metadata = await ask(session, json.dumps(example), 'Fictional parcel draft ready', 'custom')
        if origin == 'typed_review':
            _, metadata = await ask(session, 'review offer', card_kind='custom')
        return session, metadata

    for origin in ('automatic', 'typed_review'):
        for action in ('approve_cta', 'reject_cta'):
            session, metadata = await fresh(origin)
            before = await stored_state(session)
            selection = {**card_selection(payload(metadata), action), 'approved': True}
            text, metadata = await ask(session, json.dumps(selection),
                'Review finished for saved draft revision 1' if action == 'approve_cta' else 'Correct one seller-stated value',
                None if action == 'approve_cta' else 'form')
            after = await stored_state(session)
            assert after['fields'] == before['fields'] and after['draft'] == before['draft']
            assert not after.get('approved_offer') and not after.get('commercial_transactions')
            if action == 'reject_cta':
                selection = {**payload(metadata)['submit_cta']['selection'], 'field': 'customer',
                             'value': before['fields']['customer'], 'approved': True}
                await ask(session, json.dumps(selection), 'customer unchanged')
                identical = await stored_state(session)
                assert identical['revision'] == before['revision'] and identical['draft'] == before['draft']
            action_cases.append({'origin': origin, 'action': action, 'approved': True, 'passed': True})

    session, metadata = await fresh('automatic')
    before = await stored_state(session)
    original_json, original_manifest = await complete(session, 'export json')
    assert original_manifest is not None
    edit = {**card_selection(payload(metadata), 'reject_cta'), 'approved': True}
    await ask(uuid4(), json.dumps(edit), 'stale')
    _, metadata = await ask(session, json.dumps(edit), 'Correct one seller-stated value', 'form')
    correction = {**payload(metadata)['submit_cta']['selection'], 'field': 'customer', 'value': customer, 'approved': True}
    await ask(session, json.dumps(correction), 'Saved your customer')
    await ask(session, json.dumps(correction), 'already handled')
    corrected = await stored_state(session)
    assert corrected['fields'] == {**before['fields'], 'customer': customer}
    assert corrected['draft'] == before['draft'] and corrected['documents'] == before['documents']
    assert corrected['restrictions'] == before['restrictions'] and corrected['revision'] == 2 and corrected['outdated']
    await ask(session, json.dumps(edit), 'stale')
    text, metadata = await ask(session, 'review offer', 'intake revision 2', 'custom')
    assert 'draft limited' in text and 'OUTDATED' in text
    finish = {**card_selection(payload(metadata), 'approve_cta'), 'approved': True}
    await ask(session, json.dumps(finish), 'pending intake revision 2')
    readiness, _ = await complete(session, 'readiness')
    assert 'needs revision' in readiness and customer in readiness
    detailed, _ = await complete(session, 'readiness text')
    report, _ = await complete(session, 'readiness json')
    assert json.loads(report)['basis']['snapshot_sha256'] in detailed
    assert 'Assessed intake revision: 2' in detailed and 'Saved draft revision: 1' in detailed
    assert '\n\nSnapshot:' in detailed and 'draft limited' in detailed
    old_buyer, _ = await complete(session, 'export buyer readable')
    assert old_buyer.startswith('## Detailed buyer-readable offer') and 'For: Shipping form developers' in old_buyer
    assert customer not in old_buyer and '\n\n### Inputs\n\n' in old_buyer and '\n\n### Outputs\n\n' in old_buyer
    pending, _ = await complete(session, 'export json')
    assert json.loads(pending)['draft'] == json.loads(original_json)['draft']
    assert json.loads(pending)['pending_intake']['customer'] == customer
    await ask(session, 'draft limited', 'Draft v2')
    rebuilt = await stored_state(session)
    assert rebuilt['draft']['revision'] == 3 and rebuilt['draft']['draft_version'] == 2
    assert rebuilt['draft']['seller']['intended_customer'] == customer
    assert rebuilt['restrictions']['demonstration_only'] and not rebuilt['outdated']
    for command in ('review offer', 'buyer explanation', 'readiness', 'readiness text', 'export buyer readable'):
        text, metadata = await ask(session, command)
        if command == 'review offer':
            assert customer in json.dumps(payload(metadata)) and 'OUTDATED' not in text
        else:
            manifest = json.loads(text) if text.startswith('{') else {}
            if manifest.get('schema') == 'TOOL_OFFER_EXPORT_MANIFEST_V1':
                parts = [json.loads((await ask(session, f"export part {manifest['export_id']} {index}"))[0])
                         for index in range(1, manifest['total_parts'] + 1)]
                text = reassemble(manifest, parts)
            assert customer in text and 'OUTDATED' not in text
    audit_text, manifest = await complete(session, 'export json')
    audit = json.loads(audit_text)
    assert manifest is not None and audit['draft']['seller']['intended_customer'] == customer
    assert audit['draft']['revision'] == 3 and audit['restrictions']['demonstration_only']
    assert audit['pending_intake'] is None and not audit['approved_offer'] and not audit['commercial_transaction_ids']
    await ask(session, 'what do you do?', 'Your saved draft is preserved.', 'custom')
    await ask(session, 'buyer explanation', customer)
    reopened = await stored_state(session)
    assert reopened['draft'] == rebuilt['draft'] and reopened['fields'] == rebuilt['fields']
    parts = [json.loads((await ask(session, f"export part {original_manifest['export_id']} {index}"))[0])
             for index in range(1, original_manifest['total_parts'] + 1)]
    assert reassemble(original_manifest, parts) == original_json
    typed_session, _ = await fresh('automatic')
    typed_before = await stored_state(typed_session)
    await ask(typed_session, 'revise customer: ' + customer, 'Saved your customer')
    typed_after = await stored_state(typed_session)
    assert typed_after['fields'] == {**typed_before['fields'], 'customer': customer}
    assert typed_after['draft'] == typed_before['draft']
    receipt['card_journey'] = {'action_cases': action_cases, 'exports': exports,
        'customer_only_correction': True, 'identical_value': True, 'typed_correction_separate': True,
        'explicit_limited_rebuild': True, 'historical_export_preserved': True,
        'same_session_reentry_and_storage_readback': True, 'browser_reload_observed': False,
        'action_transport': 'Retained browser action structure with fresh disposable bindings, submitted through signed ACP; not a browser click.'}
    receipt['passed'] = True
