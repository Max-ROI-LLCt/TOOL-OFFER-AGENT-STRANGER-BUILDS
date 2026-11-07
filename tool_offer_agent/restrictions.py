"""Typed seller declarations with literal provenance; URLs never establish rights."""
import copy
import re


def empty():
    return {"schema": "TOOL_OFFER_RESTRICTIONS_V1", "demonstration_only": False,
            "third_party_non_ownership": False, "not_representing_maintainers": False,
            "commercial_authorization": "not_established", "lifecycle": "current_product",
            "sources": []}


def capture(record, text, *, message_id=None, timestamp=None, origin="current_message"):
    result = copy.deepcopy(record or empty())
    # A question or hypothetical is not a declaration. Restrictions are monotonic;
    # a later assertion of ownership cannot silently erase earlier restrictions.
    if re.search(r"\b(?:what if|suppose|hypothetical|if i |if we )", text, re.I):
        return result
    rules = {
        "demonstration_only": r"\b(?:demonstration only|demo only|non[- ]commercial(?: demonstration)?(?: only)?)\b",
        "third_party_non_ownership": r"\b(?:i (?:do not|don't|don’t) own|i(?: am|'m|’m) not (?:the |an? )?(?:api |tool )?owner|not claiming ownership)\b",
        "not_representing_maintainers": r"\b(?:not (?:selling it or )?representing (?:its |the )?maintainers|do not represent|don't represent)\b",
        "commercial_prohibition": r"\b(?:not selling|not for sale|no resale|no commercial use|no commercial authorization|not authorized to sell)\b",
    }
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if sentence.strip().endswith('?'):
            continue
        found = [field for field, pattern in rules.items() if re.search(pattern, sentence, re.I)]
        if not found:
            continue
        source = {"quote": sentence, "message_id": message_id, "timestamp": timestamp,
                  "origin": origin, "evidence_status": "seller_declaration_not_authenticated",
                  "applies_to": "current_product", "restrictions": found}
        if not any(s["quote"] == sentence and s["origin"] == origin for s in result["sources"]):
            result["sources"].append(source)
        for field in found:
            if field != "commercial_prohibition":
                result[field] = True
        result["commercial_authorization"] = "explicitly_restricted"
    return result


def blocked(record):
    return bool(record and (record.get("demonstration_only") or record.get("third_party_non_ownership")
                           or record.get("commercial_authorization") == "explicitly_restricted"))


def describe(record):
    record = record or empty()
    labels = []
    if record["demonstration_only"]:
        labels.append("Demonstration only")
    if record["third_party_non_ownership"]:
        labels.append("Seller discloses third-party ownership")
    if record["not_representing_maintainers"]:
        labels.append("Seller does not represent the maintainers")
    labels.append("Commercial authorization: " + record["commercial_authorization"].replace('_', ' '))
    return "; ".join(labels) + "."
