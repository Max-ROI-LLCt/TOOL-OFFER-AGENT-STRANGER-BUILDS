"""Immutable, resumable UTF-8 exports with byte-exact client verification."""
import base64
import hashlib
import json
import math
import re

# Application budget, not a claimed ASI:One platform limit. One reply per request.
REPLY_BYTES = 6000
PART_BYTES = 3000
MAX_EXPORT_BYTES = 8 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot(payload, revision, kind):
    raw = payload.encode('utf-8')
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError('Export exceeds the bounded snapshot capacity; no partial export claimed.')
    total = math.ceil(len(raw) / PART_BYTES)
    identity = sha(json.dumps([kind, revision, sha(raw)], separators=(',', ':')).encode())
    manifest = {"schema": "TOOL_OFFER_EXPORT_MANIFEST_V1", "export_id": identity,
                "kind": kind, "revision": revision, "encoding": "utf-8", "part_encoding": "base64",
                "total_parts": total, "total_bytes": len(raw), "sha256": sha(raw),
                "part_bytes": PART_BYTES, "complete_payload": False,
                "retrieve": f"export part {identity} <index 1..{total}>",
                "verification": "Decode base64, verify each part, join in index order, then verify total_bytes and sha256. A manifest or single part is not a complete export."}
    return {"manifest": manifest, "payload": payload}


def part(value, index):
    manifest = value['manifest']
    if not 1 <= index <= manifest['total_parts']:
        raise ValueError('Part index outside the manifest range.')
    raw = value['payload'].encode('utf-8')[(index - 1) * PART_BYTES:index * PART_BYTES]
    return {"schema": "TOOL_OFFER_EXPORT_PART_V1", "export_id": manifest['export_id'],
            "revision": manifest['revision'], "index": index, "total_parts": manifest['total_parts'],
            "offset_bytes": (index - 1) * PART_BYTES, "bytes": len(raw), "sha256": sha(raw),
            "data_base64": base64.b64encode(raw).decode('ascii'), "complete_payload": False}


def reassemble(manifest, parts):
    if len(parts) != manifest['total_parts']:
        raise ValueError('Missing or extra parts.')
    chunks = {}
    for item in parts:
        index = item.get('index')
        if type(index) is not int or not 1 <= index <= manifest['total_parts'] or index in chunks:
            raise ValueError('Invalid or duplicate part index.')
        if (item.get('export_id') != manifest['export_id'] or item.get('revision') != manifest['revision']
                or item.get('total_parts') != manifest['total_parts']
                or item.get('offset_bytes') != (index - 1) * manifest['part_bytes']):
            raise ValueError('Mismatched part.')
        try:
            raw = base64.b64decode(item['data_base64'], validate=True)
        except Exception:
            raise ValueError('Invalid part encoding.') from None
        expected = min(manifest['part_bytes'], manifest['total_bytes'] - (index - 1) * manifest['part_bytes'])
        if len(raw) != expected or item.get('bytes') != len(raw) or sha(raw) != item.get('sha256'):
            raise ValueError('Truncated or corrupt part.')
        chunks[index] = raw
    raw = b''.join(chunks[i] for i in range(1, manifest['total_parts'] + 1))
    if len(raw) != manifest['total_bytes'] or sha(raw) != manifest['sha256']:
        raise ValueError('Export integrity mismatch.')
    if sha(json.dumps([manifest['kind'], manifest['revision'], sha(raw)], separators=(',', ':')).encode()) != manifest['export_id']:
        raise ValueError('Export identity mismatch.')
    return raw.decode('utf-8')


def deliver(store, key, payload, revision, kind):
    if len(payload.encode('utf-8')) <= REPLY_BYTES:
        return payload
    value = snapshot(payload, revision, kind)
    # Separate durable custody prevents export retrieval from changing offer state.
    storage_key = 'export_' + key + '_' + value['manifest']['export_id']
    index_key = 'export_index_' + key
    index = store.load(index_key).get('exports', [])
    if storage_key not in index:
        index.append(storage_key)
        while len(index) > 8:
            store.delete(index.pop(0))
        store.save(index_key, {'exports': index})
    store.save(storage_key, value)
    return json.dumps(value['manifest'], ensure_ascii=False, separators=(',', ':'))


def retrieve(store, key, command):
    match = re.fullmatch(r'export part ([a-f0-9]{64}) ([1-9][0-9]{0,5})', command)
    if not match:
        return 'Use export part <export_id> <index>; retrieve exactly one indexed part per request.'
    value = store.load('export_' + key + '_' + match[1])
    if not value.get('manifest'):
        return 'Export snapshot unavailable in this sender/session. Request the export again for a new manifest.'
    try:
        return json.dumps(part(value, int(match[2])), separators=(',', ':'))
    except ValueError as error:
        return str(error)
