# fixtures

Mainnet proof fixtures: headers, branches and expected values only. Never a
whole beacon state.

Each fixture records its source endpoint, the date it was downloaded, the slots
it covers, and the SHA-256 of the raw SSZ it was derived from. Every root is
cross-checked with a second, independent SSZ library before the fixture is
written.

**No fixture value is ever invented.** A fixture is either derived from real
mainnet data or labelled `"synthetic": true`, and anything synthetic is called
out in the README as well.

Empty for now; `tools/` generates these.
