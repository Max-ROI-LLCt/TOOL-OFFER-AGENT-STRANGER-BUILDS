"""Nonspending buyer onboarding shared by deterministic and conversational intake."""

import re


def buyer_action_allowed(message, action):
    if buyer_command(message) == action:
        return True
    return action in {"wallet", "purchase guide"} and bool(re.fullmatch(
        r"\s*i (?:need|want)(?: some)? (?:help|guidance|instructions) (?:for|with) (?:a|my|the) (?:purchase|buyer wallet)[.!]?\s*", message, re.I))


def buyer_command(message):
    normalized = " ".join(message.casefold().strip().lstrip("/").rstrip(".!?").split())
    commands = {
        "wallet": "wallet", "wallet setup": "wallet", "buying wallet": "wallet",
        "set up my buying wallet": "wallet", "set up your buying wallet": "wallet",
        "help me set up my buying wallet": "wallet", "connect my wallet": "wallet",
        "help me connect my wallet": "wallet", "how do i connect my wallet": "wallet",
        "how do i pay": "wallet", "how do i pay for this": "wallet",
        "purchase guide": "purchase guide", "how do i buy a fahce check": "purchase guide",
        "help me buy a fahce check": "purchase guide",
        "prepare checkout": "check", "prepare fahce checkout": "check",
        "check my offer with fahce": "check",
        "purchase status": "purchase status", "refresh purchase status": "purchase status",
        "get my fahce result": "purchase status", "show my purchase result": "purchase status",
    }
    command = commands.get(normalized) or buyer_guide_request(message)
    if command:
        return command
    if wallet_information_question(message):
        return "wallet"
    return None


def buyer_guide_request(message):
    request = _guide_delivery_match(message)
    if request and not request.group("negative"):
        return "purchase guide" if request.group("guide").startswith("purchase") else "wallet"
    return None


def _guide_delivery_match(message):
    if "```" in message or re.search(r"^\s*(?:revise\s+)?[a-z_]+\s*:", message, re.I | re.M):
        return None
    text = re.sub(r'"[^"\n]*"|`[^`\n]*`|^\s*>[^\n]*', " ", message.casefold(), flags=re.M)
    return re.search(
        r"(?:^|[.!?]\s+|\n\s*)(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
        r"(?P<negative>(?:not|never|do not|don't|don’t)\s+)?"
        r"(?:send|show|give|share|provide|deliver)\s+(?:(?:me|us)\s+)?"
        r"(?:(?:the|your|my|our|full|complete|exact|documented|step-by-step)\s+)*"
        r"(?P<guide>wallet(?:\s+(?:setup|onboarding))?(?:\s+(?:guide|instructions|documentation|steps))?"
        r"|purchase\s+(?:guide|instructions|steps)|buyer\s+(?:setup|onboarding)\s+(?:guide|instructions|documentation|steps))"
        r"(?=\s*(?:[.!?:]|$|\b(?:for|please|without|so|as|in|again|verbatim)\b))", text,
    )


def wallet_information_question(message):
    if _guide_delivery_match(message):
        return False
    if re.search(r"https?://|```|^\s*(?:revise\s+)?[a-z_]+\s*:", message, re.I | re.M):
        return False
    text = " ".join(message.casefold().split())
    if re.search(r"\b(?:fictional|hypothetical|audit|seller billing|seller payment)\b|(?:do not|don't|don’t) (?:onboard|connect|set up)", text):
        return False
    has_wallet = re.search(r"\bwallet\b", text)
    has_setup_topic = re.search(r"\b(?:connect(?:ed|ing|ion)?|setup|set up|ready|permission|approval)\b", text)
    asks_question = re.search(r"(?:^|[.!?]\s+)(?:can|could|may|should|will|would|do|does|is|what|when|where|why|how)\b", text)
    asks_guidance = re.match(r"(?:please\s+)?(?:help me (?:understand|learn)|explain|tell me about|show me how)\b", text)
    return bool(has_wallet and has_setup_topic and (asks_question or asks_guidance))


def brief_wallet_information(state, configured):
    """Answer a setup/authority question without repeating the complete guide."""
    if state.get("fahce_checkout") or state.get("pending_payment") or not configured:
        return buyer_guide(state, configured)
    return (
        "Tool Offer Agent by Kingan Logic — Wallet guidance is available before you have an offer; "
        "actual connection happens only inside an eligible private checkout after offer preparation. "
        "Connecting shares your public account; it is not payment approval and grants no automatic spending authority. "
        "This answer creates no checkout, requests no signature and authorizes no purchase. "
        "Send wallet for the full setup guide or purchase status to inspect an existing purchase."
    )


def is_wallet_address_message(message):
    return bool(re.fullmatch(r"\s*(?:(?:my\s+)?(?:buyer\s+|buying\s+)?wallet(?:\s+address)?\s*(?::|is)\s*)?0x[a-fA-F0-9]{40}\s*", message, re.I))


WALLET_ADDRESS_GUIDANCE = (
    "Connect your wallet inside your private checkout rather than pasting its address here. "
    "An address alone cannot authorize spending. This message was not saved to the agent's "
    "intake or model history; your chat platform may retain it. Send wallet for setup guidance. "
    "Never send private keys or seed phrases."
)


def buyer_guide(state, configured):
    introduction = (
        "Tool Offer Agent by Kingan Logic — buyer wallet guide\n"
        "No repo, Codespace or developer login is needed for the normal buyer flow. "
        "Wallet guidance is available before you have an offer; actual connection happens only inside an eligible private checkout after offer preparation. "
        "This message provides instructions only: it does not create a checkout, connect a wallet, request a signature or authorize a purchase. "
        "Connect your own compatible wallet in the private checkout, not in chat. "
        "Connection shares your public account with this page; it is not payment approval. "
        "This agent does not create or fund wallets, store keys, or gain ongoing spending authority.\n"
    )
    checkout = state.get("fahce_checkout")
    if checkout:
        return introduction + (
            "An existing purchase is linked to this conversation. Do not start a second payment "
            "or reset this conversation. Send purchase status to retrieve its current status/result. "
            "A completed purchase needs no new wallet setup.\n"
            "[Open your existing private checkout](" + checkout["url"] + ")\n"
            "Keep this link private. Address masking does not hide the link's access capability, "
            "an external wallet popup, or public transaction history."
        )
    if state.get("pending_payment"):
        return introduction + "An earlier payment requires reconciliation. No new checkout or payment is offered. Send status."
    if not configured:
        return introduction + "Paid FAHCE checkout is not configured here. You can still draft and export; no wallet connection or purchase is available."
    readiness = ("Your current draft is ready for your review, not yet cleared for payment."
                 if state.get("draft") and not state.get("outdated") else
                 "First supply your public tool URL, documentation, customer, pricing, payment, access and invocation details. Then send draft. Unknown terms may be undecided.")
    return introduction + readiness + (
        "\n1. Review the offer; revise any incorrect fields. Send offer approve to record approval "
        "of this draft. That does not approve wallet spending.\n"
        "2. Send check to prepare one private FAHCE checkout and run its free input check. "
        "If input is blocked, stop; no payment should be requested. Not all generated offer "
        "formats are supported yet, and a repair may need operator help.\n"
        "3. Open that exact link. Review the request hash, offer, sources and policies. "
        "Choose your wallet and Connect wallet — no payment. To inspect your account, "
        "uncheck Hide wallet addresses while recording; turn it back on before screenshots.\n"
        "4. Only if you want this purchase, accept the policies, choose Pay now — 0.15 USDC "
        "and approve the one-time request in your wallet on Base.\n"
        "5. Return to THIS conversation; send purchase status, then export json. "
        "If delivery is uncertain, do not sign or pay again. A negative diagnosis can be billable.\n"
        "Checkout bridge: a dedicated authenticated US relay separates payment delivery from "
        "conversation hosting. It resolved the observed rejection of UK-origin server requests "
        "and forwards the unchanged buyer-approved x402 request. The recorded purchase used "
        "0.15 USDC on Base, not a separate ASI currency or native Fetch settlement rail.\n"
        "Provider policy, separately: Cloudflare Monetization Gateway currently requires buyers "
        "and sellers based in the United States. Relay location does not change buyer eligibility; "
        "this is not a US-only restriction on free offer preparation or agent hosting. "
        "See https://developers.cloudflare.com/monetization-gateway/eligibility/ .\n"
        "This buys a FAHCE evaluation, not the API in your offer. It does not certify the seller "
        "or execute that API. Other merchants, automatic budgets and native Fetch payment "
        "settlement are not supported by this checkout. Keep the checkout link and wallet popup out of recordings."
    )
