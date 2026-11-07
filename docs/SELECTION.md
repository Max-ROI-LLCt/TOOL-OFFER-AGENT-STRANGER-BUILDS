# Exact source selection

This package is a local snapshot built by the inner private repository's `judging/package.py` from `judging/selection.json`. It is not a second development history or an automatic public release. `evidence/package-manifest.json` records the original source commit, release, exact selected paths, source/output SHA-256 hashes and any reviewed adaptation.

Included: all current Python runtime modules, hosted builders, native/machine workflow tests, Worker gateway and discovery, website, configuration placeholders, current checkout/relay/wallet runtime and its browser bundle, separate custody Worker/Python client, safe offline test helpers, and specifically reviewed historical evidence. `bridge/checkout/SOURCE-PROVENANCE.json` binds the preserved source to the separate outer checkout. The obsolete inner wallet adapter is not substituted.

Excluded: Git history, credentials, secrets, private acceptance directory, raw customer/signed purchase exports, session databases, .wrangler state, caches, engine repair tooling, and captured private chat. The sole selected `.avctl/config.toml` is a reviewed public starter configuration, not authentication state.

The original customer-derived fixture is replaced only in this package by a labeled synthetic fixture; original private records remain untouched. Exact reviewed test adaptations remove dependencies on founder-local image paths and original Git metadata without pretending to reconstruct private history. Historical source archives preserve their original bytes and release identities.

A bounded credential-pattern scan and archive readback are safeguards, not a privacy guarantee. The owner must approve the manifest and confirm organizer requirements before making any source public or submitting it. This job creates no public repository or video and does not claim hackathon acceptance.
