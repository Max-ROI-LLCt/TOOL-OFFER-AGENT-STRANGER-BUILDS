"""Run offline regressions against an explicit flat hosted source directory."""

import argparse
import importlib
from pathlib import Path
import socket
import sys
import unittest

import tool_offer_agent


def deny_network(*args, **kwargs):
    raise AssertionError("Offline hosted regression attempted a network connection")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--focused", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--tests", nargs="+", help="Run only these explicitly named offline test modules.")
    arguments = parser.parse_args()
    source = Path(arguments.source).resolve(strict=True)
    sys.path.insert(0, str(source))
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    for name in ("parcel_fixture", "customer_recovery", "restrictions", "export_delivery", "model_runtime", "documents", "commerce", "drafting", "fahce", "fahce_checkout", "storage",
                 "buyer_guidance", "listing_guidance", "offer_representation", "owner_export", "protocol_payment",
                 "cloudflare_custody", "product_policy", "conversation", "readiness_cards", "readiness", "guided_cards", "workflow", "machine_contract", "machine", "chat"):
        if name in {"product_policy", "machine_contract", "machine", "readiness", "readiness_cards"} and not (source / (name + ".py")).exists():
            continue
        module = importlib.import_module(name)
        if Path(module.__file__).parent != source:
            raise RuntimeError("Wrong hosted module loaded: " + name)
        sys.modules["tool_offer_agent." + name] = module
        setattr(tool_offer_agent, name, module)
    modules = ["tests.test_wallet_information"]
    if not arguments.focused:
        modules += ["tests.test_buyer_guidance", "tests.test_fahce_checkout", "tests.test_conversation", "tests.test_workflow", "tests.test_product_reliability", "tests.test_customer_repair", "tests.test_listing_guidance", "tests.test_listing_intent_regression"]
    if arguments.tests:
        modules = arguments.tests
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    result = unittest.TextTestRunner(verbosity=2 if arguments.verbose else 1).run(suite)
    raise SystemExit(not result.wasSuccessful())
