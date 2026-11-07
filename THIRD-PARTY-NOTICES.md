# Third-party software and notices

The root [LICENSE](LICENSE) covers the original first-party Tool Offer Agent software, **not third-party dependencies or their bundled code**. Those components retain their own terms. The owner of Tool Offer Agent and FAHCE does not claim ownership of the libraries below. The added notices do not modify the existing executable bundle or its embedded notices.

## Dependency references

These declarations were checked against the included package/lock files and the already installed matching distributions on November 7, 2026, without installing or upgrading dependencies. Python dependencies are installed separately, not vendored in this snapshot. This is a focused license/notice inventory, not a complete transitive SBOM, vulnerability clearance or legal certification.

| Component | Declared version | Upstream license |
| --- | --- | --- |
| uagents | 0.26.1 | Apache-2.0 |
| uagents-core | 0.4.11 | Apache-2.0 |
| openai | 1.99.5 | Apache-2.0 |
| jsonschema (test extra) | >=4,<5; validated constraints select 4.26.0 | MIT |
| @noble/curves (site) | 2.4.0 | MIT |
| @noble/hashes (site) | 2.4.0 | MIT |
| @scure/base (site) | 2.4.0 | MIT |
| wrangler (site development) | 4.156.0 | MIT OR Apache-2.0 |
| @base-org/account (checkout) | 2.6.0 | Apache-2.0 |
| @x402/core (checkout) | 2.29.0 | Apache-2.0 |
| @x402/evm (checkout) | 2.29.0 | Apache-2.0 |
| viem (checkout) | 2.57.13 | MIT |
| esbuild (checkout development) | 0.28.2 | MIT |

See [pyproject.toml](pyproject.toml), [validated Python constraints](constraints-validated.txt), [site lockfile](site/package-lock.json) and [checkout lockfile](bridge/checkout/package-lock.json). The setuptools build backend and other transitive dependencies have their own distribution licenses too; installing a dependency does not place it under PolyForm. Retain upstream license files and notices when redistributing those packages.

## Code included in the checkout browser bundle

The existing [checkout browser bundle](bridge/checkout/public/app.js) contains package source markers for these 15 installed package instances. Their versions match the included checkout lockfile. The two `ox` versions are separate instances; site dependencies have different versions and are not substituted for the bundled ones.

| Package | Bundled version | License | Copyright notice |
| --- | --- | --- | --- |
| @base-org/account | 2.6.0 | Apache-2.0 | Copyright (c) 2018-2025 Coinbase, Inc. |
| @x402/core | 2.29.0 | Apache-2.0 | Copyright 2026 x402 Foundation |
| @x402/evm | 2.29.0 | Apache-2.0 | Copyright 2026 x402 Foundation |
| idb-keyval | 6.2.1 | Apache-2.0 | Copyright 2016, Jake Archibald |
| @noble/curves | 1.9.1 | MIT | Copyright (c) 2022 Paul Miller (https://paulmillr.com) |
| @noble/hashes | 1.8.0 | MIT | Copyright (c) 2022 Paul Miller (https://paulmillr.com) |
| abitype | 1.2.3 | MIT | Copyright (c) 2022-present weth, LLC |
| clsx | 1.2.1 | MIT | Copyright (c) Luke Edwards <luke.edwards05@gmail.com> (lukeed.com) |
| eventemitter3 | 5.0.1 | MIT | Copyright (c) 2014 Arnout Kazemier |
| ox | 0.14.59 and nested 0.6.9 | MIT | Copyright (c) 2023-present wevm |
| preact | 10.24.2 | MIT | Copyright (c) 2015-present Jason Miller |
| viem | 2.57.13 | MIT | Copyright (c) 2023-present weth, LLC |
| zod | 4.6.7 | MIT | Copyright (c) 2025 Colin McDonnell |
| zustand | 5.0.3 | MIT | Copyright (c) 2019 Paul Henschel |

The author contact in the `clsx` notice is its upstream public copyright attribution, not a project credential or customer record. This inventory is based on the existing bundle's source markers; it is not a fresh build or a claim that the original build can be reconstructed from markers alone.

## MIT terms for the MIT components above

The copyright notices in the table identify the respective works. The following MIT permission and warranty terms apply to those works, not to Tool Offer Agent's first-party code:

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Whitespace and quotation typography are normalized here; the original bundle's embedded notices are retained unchanged. If distributing the browser bundle separately, include this notice file and the Apache license copy with it.

## Apache terms and notices

The full [Apache License, Version 2.0](LICENSES/Apache-2.0.txt) is included unchanged from the installed `@x402/core` distribution. It also supplies the full license referenced by the Apache-licensed components above. The Coinbase and Jake Archibald copyright notices above accompany this upstream boilerplate from their license files:

```text
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

Both `@x402/core` and `@x402/evm` provide the following NOTICE text:

```text
Apache-2.0 License

Copyright 2026 x402 Foundation

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

The `@x402/evm` NOTICE additionally contains the following upstream attribution. Its inclusion preserves the package notice and does not claim that Tool Offer Agent enables this payment scheme:

```text
auth-capture scheme:

The auth-capture payment scheme v1.0 and the client portion of its TypeScript
implementation in @x402/evm were contributed by the x402r team. See
proposal issue #1011 and specification PR #1425. The implementation was
developed in https://github.com/BackTrackCo/x402r-scheme prior to
upstreaming.

The implementation originated from the "x402-escrow" proposal by
Agentokratia in issue #834, published as @agentokratia/x402-escrow
on npm under the MIT License, and incorporates code from that
package.
```

## External services and content

Agentverse, ASI:One, model-provider services, Cloudflare, wallet services and any linked documentation or screenshots have their own terms. Kingan Logic's external FAHCE service and private signing infrastructure are not licensed by this repository. [The bridge architecture](docs/BRIDGE.md) explains which source is included and which services are separate. None of these notices certify execution, authorize purchases or resolve the disclosed delivery/dependency findings.
