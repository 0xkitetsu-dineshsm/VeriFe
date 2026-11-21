// The independent half of the layout check: the same numbers, from an SSZ
// library that shares no code with `layout_check.py` and does not read the
// spec markdown at all.
//
// @lodestar/types defines every fork's containers by hand in TypeScript and
// @chainsafe/ssz computes the generalized indices with its own tree
// machinery. Agreement between this and the spec-derived values is what
// open question 1 asks for: "the consensus-specs repository *and* an
// independent SSZ library".
//
//     cd tools && npm install && node layout_cross_check.mjs
//
// Prints JSON on stdout; `layout_check.py --cross-check` diffs it.

import { ssz } from "@lodestar/types";

const FORKS = ["capella", "deneb", "electra", "fulu"];
const out = {};

for (const fork of FORKS) {
  const types = ssz[fork];
  if (!types) throw new Error(`@lodestar/types has no ${fork}`);
  const state = types.BeaconState;
  const body = types.BeaconBlockBody;
  const payload = types.ExecutionPayload;
  const gindex = (type, path) => Number(type.getPathInfo(path).gindex);

  out[fork] = {
    state_fields: Object.keys(state.fields).length,
    state_fork_gi: gindex(state, ["fork"]),
    state_fork_current_version_gi: gindex(state, ["fork", "currentVersion"]),
    block_roots_gi: gindex(state, ["blockRoots"]),
    historical_summaries_gi: gindex(state, ["historicalSummaries"]),
    body_fields: Object.keys(body.fields).length,
    execution_payload_gi: gindex(body, ["executionPayload"]),
    payload_fields: Object.keys(payload.fields).length,
    body_to_state_root_gi: gindex(body, ["executionPayload", "stateRoot"]),
    body_to_receipts_root_gi: gindex(body, ["executionPayload", "receiptsRoot"]),
    body_to_block_number_gi: gindex(body, ["executionPayload", "blockNumber"]),
    body_to_timestamp_gi: gindex(body, ["executionPayload", "timestamp"]),
    body_to_block_hash_gi: gindex(body, ["executionPayload", "blockHash"]),
    header_fields: Object.keys(ssz.phase0.BeaconBlockHeader.fields).length,
  };
}

process.stdout.write(JSON.stringify(out, null, 1) + "\n");
