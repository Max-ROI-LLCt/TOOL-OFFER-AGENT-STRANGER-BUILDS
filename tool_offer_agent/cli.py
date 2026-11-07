"""Local interactive workflow; no agent service or model requests by default."""

import argparse
import os

from .storage import DEFAULT_STATE_PATH, StateStore
from .workflow import Workflow


def main():
    parser = argparse.ArgumentParser(description="Local Tool Offer Agent; type help or quit.")
    parser.add_argument("--sender", default="local-owner")
    parser.add_argument("--session", default="local-chat")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--message", help="Process one message and print only its reply, then exit.")
    args = parser.parse_args()
    workflow = Workflow(store=StateStore(args.state), name=os.getenv("TOOL_OFFER_AGENT_NAME", "Tool Offer Agent"))
    if args.message is not None:
        print(workflow.handle(args.sender, args.session, args.message))
        return
    print(workflow.handle(args.sender, args.session, "start"))
    while True:
        try:
            text = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() in ("quit", "exit"):
            break
        print(workflow.handle(args.sender, args.session, text))


if __name__ == "__main__":
    main()
