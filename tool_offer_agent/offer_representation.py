"""Lossless, inspectable offer mapping. Engine interpretation is a separate gate."""

import json
import re
from .drafting import human_fact, verified_derivation
from .restrictions import empty as empty_restrictions, describe as describe_restrictions
from .fahce import canonical_json, fingerprint, machine_request, utf16_length


def leaf_values(value, path=""):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from leaf_values(child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from leaf_values(child, path + "/" + str(index))
    else:
        yield path, value


def representation(draft, documents, *, restrictions=None, outdated=False):
    """Map every source leaf once, with unchanged text and no synthetic evidence."""
    claims = []
    sources = {doc["source_url"]: (f"doc_{i + 1}", doc["text"]) for i, doc in enumerate(documents)}
    for path, value in leaf_values(draft):
        documented = any(path.startswith("/offer/" + category + "/") for category in
                         ("capabilities", "inputs", "outputs", "limitations", "documented_commercial_terms"))
        item = {"id": "field_" + fingerprint(path)[:20], "draft_pointer": path,
                "value": value, "role": "documentation_claim" if documented else
                "limitation_or_provenance" if path.startswith(("/boundaries", "/model_extraction", "/deterministic_extraction")) else "seller_or_record_declaration",
                "evidence_refs": [], "external_execution_verified": False}
        if documented and path.endswith("/text") and isinstance(value, str):
            parent_path = path.rsplit("/", 1)[0]
            parts = parent_path.strip("/").split("/")
            parent = draft
            for part in parts:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            source = sources.get(parent.get("source_url"))
            if source:
                item["evidence_refs"] = [source[0]]
                item["quote_alignment"] = ("source_backed_derived" if verified_derivation(parent, source[1]) else
                                           "verbatim" if value in source[1] else "derived_schema_or_unaligned")
                if item["quote_alignment"] == "source_backed_derived":
                    item["source_pointers"] = parent.get("derivation", {}).get("source_pointers", [parent["source_pointer"]])
        claims.append(item)
    result = {"schema": "TOOL_OFFER_REPRESENTATION_V1", "draft_sha256": fingerprint(draft),
              "original_draft": draft, "claims": claims,
              "current_restrictions": restrictions or draft.get("restrictions", empty_restrictions()), "draft_outdated": outdated,
              "evidence_sha256": [fingerprint(doc) for doc in documents],
              "interpretation_scope": "NOT_ESTABLISHED",
              "payment_ready": False,
              "scope_note": "Complete local field mapping, not proof that FAHCE interprets nested JSON as these propositions. Free preflight cannot establish that scope."}
    validate_representation(result, draft, documents)
    return result


def validate_representation(value, draft, documents):
    if (value.get("draft_sha256") != fingerprint(draft)
            or value.get("original_draft") != draft
            or value.get("evidence_sha256") != [fingerprint(doc) for doc in documents]):
        raise ValueError("Representation changed the original draft or evidence.")
    expected = dict(leaf_values(draft))
    actual = value.get("claims", [])
    if (len(actual) != len(expected) or len({item["draft_pointer"] for item in actual}) != len(expected)
            or {item["draft_pointer"]: item["value"] for item in actual} != expected):
        raise ValueError("Representation omitted, duplicated or altered source fields.")
    if any(item.get("external_execution_verified") is not False for item in actual):
        raise ValueError("Representation invented execution evidence.")
    for item in actual:
        path = item["draft_pointer"]
        refs = []
        if path.endswith("/text") and any(path.startswith("/offer/" + category + "/") for category in
                ("capabilities", "inputs", "outputs", "limitations", "documented_commercial_terms")):
            parent = draft
            for part in path.strip("/").split("/")[:-1]:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            matches = [(i, doc) for i, doc in enumerate(documents) if doc["source_url"] == parent.get("source_url")]
            if matches:
                i, doc = matches[-1]
                refs = [f"doc_{i + 1}"]
                aligned = ("source_backed_derived" if verified_derivation(parent, doc["text"]) else
                           "verbatim" if item["value"] in doc["text"] else "derived_schema_or_unaligned")
                if item.get("quote_alignment") != aligned:
                    raise ValueError("Representation altered quote alignment.")
                if aligned == "source_backed_derived" and item.get("source_pointers") != parent.get("derivation", {}).get("source_pointers", [parent["source_pointer"]]):
                    raise ValueError("Representation altered derivation pointers.")
        if item.get("evidence_refs") != refs:
            raise ValueError("Representation misaligned claim evidence.")


def structured_preview_request(draft, documents):
    # Intentionally separate from checkout preparation until semantic coverage is established.
    request = machine_request(draft, documents)
    request["candidate_output"] = canonical_json(representation(draft, documents))
    if len(canonical_json(request).encode()) > 524288 or utf16_length(request["candidate_output"]) > 200000:
        raise ValueError("Lossless representation exceeds the aggregate request limit.")
    return request


def buyer_offer(draft, *, outdated=False, restrictions=None, documents=None):
    from .drafting import human_fact, presentation_fact
    offer, seller = draft["offer"], draft["seller"]
    def buyer_facts(name):
        result = []
        seen = set()
        for entry in offer.get(name, []):
            item = presentation_fact(entry, documents)
            if isinstance(item.get("schema_value"), dict):
                item["text"] = human_fact(item)
                item["derivation"] = {**item.get("derivation", {}), "kind": "schema_summary"}
                item["text_scope"] = "Readable schema summary; schema_value retains the complete exact schema."
            identity = (item.get("source_url"), item["text"])
            if identity not in seen:
                result.append(item)
                seen.add(identity)
        return result
    return {"schema": "TOOL_OFFER_BUYER_V1", "offer_sha256": fingerprint(draft),
            "revision": draft["revision"], "outdated": outdated,
            "draft_version": draft.get("draft_version"), "draft_version_scope": draft.get("draft_version_scope", "legacy_unknown"),
            "documentation_evidence": draft.get("documentation_evidence", {"status": "legacy_not_assessed"}),
            "restrictions": restrictions or draft.get("restrictions", empty_restrictions()),
            "description": {"job": offer["job"], "customer": seller["intended_customer"],
                            "outcome_status": "proposed_not_executed"},
            "provider": seller,
            "interface": {name: buyer_facts(name) for name in ("capabilities", "inputs", "outputs", "limitations")},
            "seller_terms": {name: offer.get(name) for name in ("pricing", "payment_instructions", "access_instructions", "invocation_instructions")},
            "documented_terms": buyer_facts("documented_commercial_terms"),
            "commercial_terms_provenance": draft.get("commercial_terms_provenance", {"authorization_status": "not_established"}),
            "coverage": {"missing_categories": offer.get("unknown_or_unextracted", []),
                         "meaning": "Unknown or not extracted from bounded sources; not proof of absence or lack of support.",
                         "extraction_mode": draft.get("extraction_mode")},
            "evidence_availability": {name: "documented_unverified" if offer.get(name) else "not_extracted" for name in
                                      ("capabilities", "inputs", "outputs", "limitations", "documented_commercial_terms")},
            "semantic_support": "not_established_by_this_export",
            "use_restrictions": [{"field": name, "seller_wording": value} for name, value in offer.items()
                                 if isinstance(value, str) and any(term in value.casefold() for term in
                                      ("demonstration", "demo only", "non-commercial", "not the owner", "not the api owner"))],
            "boundaries": draft.get("boundaries", []),
            "evaluation_status": "not_established_by_this_export"}


def buyer_readable(draft, restrictions=None, *, outdated=False, documents=None):
    from .drafting import presentation_fact
    if not draft:
        return "No draft yet. " + describe_restrictions(restrictions)
    offer, seller = draft["offer"], draft["seller"]
    from .customer_recovery import evidence_text
    label = f"Draft v{draft['draft_version']}" if draft.get("draft_version") else "Draft (legacy version count unknown)"
    lines = ["## Detailed buyer-readable offer — " + label + f"; saved draft revision {draft['revision']}" + (" (previous version; revisions pending)" if outdated else ""),
             evidence_text(draft.get("documentation_evidence", {})),
             "Job: " + offer['job'], "For: " + seller['intended_customer'],
             "Customer outcome: the proposed job above; no tool execution is verified.",
             "Access: " + offer['access_instructions'], "Invoke: " + offer['invocation_instructions'],
             "Seller-stated pricing: " + offer['pricing'],
             "Payment instructions (seller supplied): " + offer['payment_instructions'],
             describe_restrictions(restrictions or draft.get('restrictions')),
             "Seller identity and commercial rights are not independently authenticated."]
    if draft.get("draft_version_scope") == "generated_since_version_tracking_began_after_legacy_draft":
        lines.insert(1, "Version count covers drafts generated since tracking began; earlier legacy drafts were not counted.")
    if outdated:
        command = 'draft limited' if (restrictions or draft.get('restrictions') or {}).get('demonstration_only') else 'draft'
        lines.insert(1, 'This is the previous saved draft; corrections are pending. Use ' + command + ' to explicitly rebuild. Historical export snapshots stay unchanged.')
    if offer.get("payment_status") == "tentative_seller_statement":
        lines.append("Payment is tentative seller information; operational acceptance is not verified.")
    for category in ("capabilities", "inputs", "outputs"):
        lines.append("### " + category.title())
        for item in offer.get(category, []):
            item = presentation_fact(item, documents)
            source = item.get("source_url", "not supplied") + ("#" + item["source_pointer"] if item.get("source_pointer") else "")
            lines.append("- " + human_fact(item) + " [source: " + source + "]")
        if not offer.get(category):
            lines.append("- Not extracted; no absence or support is inferred.")
    limits = offer.get('limitations', [])
    lines.append("Documented limitations: " + ("; ".join(item['text'] + " [source: " + item.get('source_url', 'not supplied') + "]" for item in limits) if limits else "not extracted; absence is not established."))
    terms = offer.get('documented_commercial_terms', [])
    lines.append("Third-party documented terms: " + ("; ".join(item['text'] + " [source: " + item.get('source_url', 'not supplied') + "]" for item in terms) if terms else "not extracted.") + " These do not grant seller authorization.")
    lines.append("Sources (claims, not verified behavior): " + ", ".join(seller['source_urls']))
    return "\n\n".join(lines)


def fact_operation(item):
    match = re.match(r'^/paths/([^/]+)/(get|post|put|patch|delete|head|options)(?:/|$)', item.get('source_pointer') or '')
    if match:
        return match[2], match[1].replace('~1', '/').replace('~0', '~')
    match = re.match(r'^paths\[(.+)\]\.(get|post|put|patch|delete|head|options)(?:\.|$)', item.get('location') or '')
    if match:
        return match[2], match[1]
    match = re.match(r'^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[^\s:]+)', item['text'])
    return (match[1].lower(), match[2]) if match else item.get('operation_binding')


def selected_operations(offer):
    selected = {(match[1].lower(), match[2].rstrip('.')) for match in re.finditer(
        r'\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?:https?://[^/\s]+)?(/[^\s,;]*)', offer['invocation_instructions'], re.I)}
    documented = {fact_operation(item) for category in ('capabilities', 'inputs', 'outputs') for item in offer.get(category, [])}
    return selected & documented


def display_facts(offer, documents=None):
    from .drafting import json_spans, presentation_fact
    categories = ('capabilities', 'inputs', 'outputs', 'limitations', 'documented_commercial_terms')
    result = {category: [] for category in categories}
    fragments, recovered, references = {}, {}, set()
    selected = selected_operations(offer)
    for category in categories:
        for original in offer.get(category, []):
            item = presentation_fact(original, documents)
            span = re.fullmatch(r'text\[(\d+):(\d+)\]', original.get('location') or '')
            if item.get('evidence_status') == 'legacy_fragment_requires_review':
                identity = (original['source_url'], original['location'], original['text'])
                fragments[identity] = fragments.get(identity, 0) + 1
                start, end = map(int, span.groups())
                for document in documents or []:
                    content = document['text']
                    if document.get('source_url') != original['source_url'] or content[start:end] != original['text']:
                        continue
                    parsed = json.loads(content)
                    for pointer, value, beginning, ending in json_spans(content):
                        if not isinstance(value, str) or not value.strip() or beginning >= end or ending <= start:
                            continue
                        record = {**original, 'text': value, 'source_pointer': pointer, 'location': pointer,
                                  'original_excerpt_location': original['location'],
                                  'derivation': {'kind': 'json_value_text'}, 'presentation_scope': 'Complete retained JSON value, not a verbatim fragment.'}
                        recovered[(original['source_url'], pointer)] = record
                        if re.fullmatch(r'https?://\S+', value):
                            references.add(value)
                            continue
                        service = re.match(r'^/services/(\d+)/', pointer)
                        if service:
                            definition = parsed['services'][int(service[1])]
                            path = re.sub(r'^https?://[^/]+', '', definition.get('endpoint', ''))
                            record['operation_binding'] = (definition.get('method', '').lower(), path)
                        applies = fact_operation(record)
                        if selected and applies and applies not in selected:
                            continue
                        if pointer.endswith('/description') and (service or re.fullmatch(r'/paths/[^/]+/[^/]+/description', pointer)):
                            result['capabilities'].append(record)
                        elif re.search(r'/responses/[^/]+/description$', pointer):
                            result['limitations'].append(record)
                        elif re.search(r'/(?:price_display|settlement_display|consumption_scope)$|/price/description$', pointer):
                            result['documented_commercial_terms'].append(record)
                continue
            if span and item == original:
                start, end = map(int, span.groups())
                for document in documents or []:
                    content = document['text']
                    if document.get('source_url') != original.get('source_url') or content[start:end] != original['text']:
                        continue
                    try:
                        json.loads(content)
                    except ValueError:
                        boundary = content.find('\n', end)
                        item = {**item, 'text': content[start:boundary if boundary >= 0 else len(content)]}
            if re.fullmatch(r'https?://\S+', item['text']):
                references.add(item['text'])
                continue
            if re.search(r'\b(?:the|this) example\b', item['text'], re.I) or item.get('example_value'):
                item = {**item, 'presentation_example': True}
            applies = fact_operation(item)
            if selected and applies and applies not in selected and category in {'capabilities', 'inputs', 'outputs'}:
                continue
            if selected and applies and applies not in selected:
                item = {**item, 'scope': applies[0].upper() + ' ' + applies[1] + ' (other operation)'}
            result[category].append(item)
    for category, entries in result.items():
        result[category] = list({(item['text'], item.get('source_url'), item.get('source_pointer')): item for item in entries}.values())
    result['inputs'].sort(key=lambda item: (0 if (item.get('schema_value') or {}).get('content') else
                                           1 if (item.get('schema_value') or {}).get('required') else 2))
    result['capabilities'].sort(key=lambda item: (fact_operation(item) not in selected, not (item.get('source_pointer') or '').endswith('/description')))
    return result, {'appearances': sum(fragments.values()), 'unique_fragments': len(fragments),
                    'recovered_values': list(recovered.values()), 'references': sorted(references)}


def operation_job(offer, documents):
    selected = selected_operations(offer)
    descriptions = []
    for document in documents or []:
        try:
            spec = json.loads(document['text'])
        except ValueError:
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get('paths'), dict):
            continue
        for method, path in sorted(selected):
            path_item = spec['paths'].get(path, {})
            operation = path_item.get(method, {}) if isinstance(path_item, dict) else {}
            description = operation.get('description') if isinstance(operation, dict) else None
            if isinstance(description, str) and description not in descriptions:
                descriptions.append(description)
    if not descriptions:
        descriptions = [item['text'] for item in offer.get('capabilities', []) if fact_operation(item) in selected]
    return ' '.join(descriptions) if descriptions else offer['job']


def human_highlight(item, documents=None, *, concise=False):
    value = item.get('schema_value', {})
    content = value.get('content', {}) if isinstance(value, dict) else {}
    schema = content.get('application/json', {}).get('schema', {})
    pointer = schema.get('$ref', '')
    if pointer.startswith('#/'):
        for document in documents or []:
            if document.get('source_url') != item.get('source_url'):
                continue
            try:
                resolved = json.loads(document['text'])
                for name in pointer[2:].split('/'):
                    resolved = resolved[name.replace('~1', '/').replace('~0', '~')]
                properties = resolved.get('properties', {})
                required = resolved.get('required', [])
                if properties and required:
                    fields = [name + ' (' + ('exactly ' + json.dumps(properties[name]['const'], ensure_ascii=False) if 'const' in properties[name]
                              else str(properties[name].get('type', 'see schema'))) + ')' for name in required if name in properties]
                    optional = [name for name in properties if name not in required]
                    return 'JSON request outline: required ' + '; '.join(fields) + ('. Optional: ' + ', '.join(optional) if optional else '') + '. Complete nested schemas and constraints: export buyer readable.'
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    text = human_fact(item, concise=concise)
    text = human_fact(item, concise=True) if len(text.encode()) > 600 and value else text
    return re.sub(r'(?<=[.!?])\.(?=\s|$)', '', text) if value else text


def buyer_explanation(draft, restrictions=None, *, outdated=False, documents=None, pending_fields=None, intake_revision=None):
    from .customer_recovery import evidence_text
    if not draft:
        return "No draft yet. " + describe_restrictions(restrictions)
    offer, seller = draft['offer'], draft['seller']
    sources = list(dict.fromkeys(seller.get('source_urls', [])))
    selected = selected_operations(offer)

    def reference(item):
        source = item.get('source_url')
        if not source:
            return '[source unspecified]'
        if source not in sources:
            sources.append(source)
        return '[' + str(sources.index(source) + 1) + ']'

    label = 'Draft v' + str(draft['draft_version']) if draft.get('draft_version') else 'Saved draft (legacy numbering)'
    lines = ['## Buyer explanation — ' + label + '; revision ' + str(draft['revision']) + ('; OUTDATED: corrections pending' if outdated else ''),
             'Concise derived overview, not a quotation or full specification.',
             evidence_text(draft.get('documentation_evidence', {})),
             'Offered operation (documented, not independently verified): ' + operation_job(offer, documents), 'For: ' + seller['intended_customer'],
             'Seller-stated pricing: ' + offer['pricing'], 'Payment (seller supplied): ' + offer['payment_instructions'],
             'Access (seller supplied): ' + offer['access_instructions'], 'Invoke (seller supplied): ' + offer['invocation_instructions'],
             describe_restrictions(restrictions or draft.get('restrictions'))]
    if (offer['job'] != operation_job(offer, documents)
            and not re.match(r'^(?:Prepare a source-attributed (?:commercial )?offer\b|Use the documented operation:)', offer['job'], re.I)):
        lines.insert(5, 'Seller-scoped proposed job: ' + offer['job'])
    if outdated and pending_fields:
        saved = {'customer': seller['intended_customer'], 'tool_url': seller.get('tool_url'), 'seller_name': seller.get('name'), 'docs': seller.get('source_urls'),
                 **{field: offer.get(field if field in {'job', 'pricing'} else field + '_instructions') for field in ('job', 'pricing', 'payment', 'access', 'invocation')}}
        pending = [field + ': ' + str(value) for field, value in pending_fields.items() if field in saved and value != saved[field]]
        command = 'draft limited' if (restrictions or draft.get('restrictions') or {}).get('demonstration_only') else 'draft'
        lines[2:2] = ['Pending seller corrections — intake revision ' + str(intake_revision) + '; not incorporated into the saved draft:',
                      *pending, 'The saved-draft details below are historical until you request ' + command + '. No new evidence or authorization is inferred.']
    if offer.get('payment_status') == 'tentative_seller_statement':
        lines.append('Payment is tentative; operational acceptance is not verified.')
    projected, recovery = display_facts(offer, documents)
    other_operations = {fact_operation(item) for category in ('capabilities', 'inputs', 'outputs') for item in offer.get(category, [])
                        if selected and fact_operation(item) and fact_operation(item) not in selected}
    examples = set()
    for categories, heading in [(('inputs',), 'Input highlights'), (('outputs',), 'Output highlights'),
                                (('capabilities', 'limitations'), 'Documented capabilities and limitations'),
                                (('documented_commercial_terms',), 'Third-party documented terms (not seller authority)')]:
        entries = {}
        for category, item in ((category, entry) for category in categories for entry in projected[category]):
            source = reference(item)
            if item.get('presentation_example'):
                examples.add((item['text'], source))
                continue
            text = human_highlight(item, documents) if category in {'inputs', 'outputs'} else human_fact(item)
            if category == 'capabilities' and text == operation_job(offer, documents):
                continue
            if category == 'capabilities' and selected and not fact_operation(item) and text not in {entry['text'] for entry in projected['limitations']}:
                text = 'Platform context, not added operations: ' + text
            if item.get('scope'):
                text = 'Applies to ' + item['scope'] + ': ' + text
            entries.setdefault(text, set()).add(source)
        lines.append('### ' + heading)
        lines.extend('- ' + text + ' ' + ' '.join(sorted(refs)) for text, refs in entries.items())
        if not entries:
            lines.append('- No complete applicable fact extracted; absence is not established.')
    if selected:
        lines.append('Interface highlights follow the explicitly seller-stated invocation: ' + '; '.join(method.upper() + ' ' + path for method, path in sorted(selected)) + '.')
    if other_operations:
        lines.append(str(len(other_operations)) + ' other documented operations are not automatically included in this seller offer. Their capabilities, conditions and schemas remain in export buyer readable / export json.')
    if recovery['appearances']:
        lines.append(str(recovery['appearances']) + ' incomplete legacy JSON excerpt appearances represent ' + str(recovery['unique_fragments']) + ' unique source fragments. Complete JSON values are recovered for display; originals and unresolved context remain in export json. Incomplete extraction is not proof of absence.')
    if examples:
        lines.append('Documentation includes ' + str(len(examples)) + ' illustrative examples, not general operation guarantees. Full examples and their source context: export buyer readable / export json.')
    additional = [url for url in recovery['references'] if url.split('#')[0] not in sources and url != seller.get('tool_url')
                  and url not in offer['invocation_instructions']]
    if additional:
        lines.append('Additional documentation references (not verified terms): ' + '; '.join(additional))
    if draft.get('model_extraction', {}).get('partial') or draft.get('extraction_mode') == 'deterministic_limited':
        lines.append('Extraction coverage is partial/limited, not proof of absence. Full recorded coverage is in export json.')
    lines.extend(['### Sources (documentation claims, not verified behavior)'] + ['- [' + str(index) + '] ' + url for index, url in enumerate(sources, 1)])
    lines.append('Full schemas, statuses and provenance: export buyer readable. Audit: export json. No seller authority, approval, publication, payment or execution is established.')
    return ''.join(('\n' if line.startswith('- ') and index and lines[index - 1].startswith('- ') else '\n\n' if index else '') + line for index, line in enumerate(lines))
