"""Bundled fictional parcel example; never a fetched or invoked public service."""

URL = "https://parcel-example.invalid/openapi.json"
TOOL = "https://parcel-example.invalid/"
RESTRICTION = "Demonstration only. No commercial use."
SPEC = {
    "openapi": "3.1.0", "info": {"title": "Fictional Parcel Format API", "version": "1.0"},
    "paths": {"/normalize": {"post": {
        "summary": "Normalize seller-supplied parcel dimensions into centimetres",
        "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object", "required": ["length", "width", "height", "unit"],
            "properties": {"length": {"type": "number"}, "width": {"type": "number"}, "height": {"type": "number"}, "unit": {"enum": ["cm", "in"]}}},
            "example": {"length": 10, "width": 4, "height": 2, "unit": "in"}}}},
        "responses": {"200": {"description": "Normalized dimensions; no carrier quote or shipment booking",
            "content": {"application/json": {"schema": {"type": "object", "properties": {
                "length_cm": {"type": "number"}, "width_cm": {"type": "number"}, "height_cm": {"type": "number"}}},
                "example": {"length_cm": 25.4, "width_cm": 10.16, "height_cm": 5.08}}}}}}}},
    "x-limitations": "Dimensions only. No carrier prices, shipment booking, insurance or delivery guarantees. Positive finite numbers required.",
    "x-commercial-terms": "Documentation describes the interface; it grants no resale rights or seller authority.",
}
FIELDS = {"tool_url": TOOL, "docs": URL, "seller_name": "Fictional Parcel Workshop",
    "job": "Normalize parcel dimensions for a packing form", "customer": "Shipping form developers",
    "pricing": "Fictional seller proposes USD 9 per month for 1000 calls; overage disabled",
    "payment": "Fictional invoice; no payment connection exists",
    "access": "Fictional seller-issued API key; do not send a real credential",
    "invocation": "POST /normalize with JSON length, width, height, unit; Authorization: Bearer <API_KEY>"}
