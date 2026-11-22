// The proof generator: turns live mainnet data into a VeriFe fixture.
//
// Not Fe, and declared as supporting tooling in the README. It exists because
// the library's tests must run against real beacon-chain data rather than
// trees this repository built for itself.
//
//     cd tools && npm install
//     node gen_fixture.mjs recent --slot 15697000 --out ../fixtures/recent_fulu.json
//
// What it produces, per leg of the chain of commitments, is a *single* branch
// with a composite gindex: the Fe verifier derives that gindex from its layout
// type with `const fn`s and walks the branch in one pass, so a fixture carries
// no positions of its own. The gindex is written into the fixture anyway, under
// `expected_gindex`, purely so that a mismatch between this tool and the Fe
// side is a loud failure rather than a silent one.
//
// Nothing here is trusted by the library: every root in a fixture is either
// re-derived by hashing during the test, or is the one anchor root the test
// starts from.

import { createHash } from "node:crypto";
import { request } from "node:https";
import { readFileSync, writeFileSync } from "node:fs";
import { ssz } from "@lodestar/types";
import { createProof, ProofType } from "@chainsafe/persistent-merkle-tree";

const BEACON_API = "https://ethereum-beacon-api.publicnode.com";
const EXECUTION_RPC = "https://ethereum-rpc.publicnode.com";
const EIP_4788_ADDRESS = "0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02";
const SLOTS_PER_HISTORICAL_ROOT = 8192;
const STATE_PATH = "cache/state/finalized.ssz";

// Node 16 has no global `fetch` and this tool is not worth a dependency for
// it, so here is the slice of it that gets used. Node 18 and later shadow this
// with the real thing.
const fetchShim =
  globalThis.fetch ??
  ((url, options = {}) =>
    new Promise((resolve, reject) => {
      const target = new URL(url);
      const call = request(
        {
          hostname: target.hostname,
          path: target.pathname + target.search,
          method: options.method ?? "GET",
          headers: options.headers ?? {},
        },
        (response) => {
          const chunks = [];
          response.on("data", (chunk) => chunks.push(chunk));
          response.on("end", () => {
            const body = Buffer.concat(chunks);
            resolve({
              ok: response.statusCode >= 200 && response.statusCode < 300,
              status: response.statusCode,
              headers: { get: (name) => response.headers[name.toLowerCase()] ?? null },
              json: async () => JSON.parse(body.toString("utf8")),
              text: async () => body.toString("utf8"),
              arrayBuffer: async () => body,
            });
          });
        },
      );
      call.on("error", reject);
      if (options.body) call.write(options.body);
      call.end();
    }));

const hex = (bytes) => "0x" + Buffer.from(bytes).toString("hex");
const u64 = (value) => Number(value);

function fail(message) {
  console.error("error: " + message);
  process.exit(1);
}

async function getJson(url, headers = {}) {
  const response = await fetchShim(url, { headers: { Accept: "application/json", ...headers } });
  if (!response.ok) fail(`${url} -> ${response.status}`);
  return response.json();
}

/** Fork boundaries, from the fork epochs verified in tools/README.md. */
const FORK_BOUNDARIES = [
  ["fulu", 13164544],
  ["electra", 11649024],
  ["deneb", 8626176],
  ["capella", 6209536],
];

/** Which fork's layout a slot belongs to. Derived, never taken from an input. */
function forkForSlot(slot) {
  for (const [name, first] of FORK_BOUNDARIES) {
    if (slot >= first) return name;
  }
  fail(`slot ${slot} is before Capella (6,209,536); VeriFe does not reach it`);
}

/**
 * A signed block, as a decoded value plus the fork whose layout it uses.
 *
 * The endpoint serves JSON only -- it ignores `Accept: application/octet-stream`
 * and sends no `Eth-Consensus-Version` header -- so the fork comes from the
 * slot, and the response's own `version` field is used to check that choice
 * rather than to make it. A disagreement means the fork boundaries in this file
 * are wrong, which is worth failing over.
 */
async function getBlock(slot) {
  const json = await getJson(`${BEACON_API}/eth/v2/beacon/blocks/${slot}`);
  const fork = forkForSlot(slot);
  if (json.version && json.version.toLowerCase() !== fork) {
    fail(
      `slot ${slot}: the boundaries here say ${fork}, the endpoint says ` +
        `${json.version}`,
    );
  }
  return { fork, value: ssz[fork].SignedBeaconBlock.fromJson(json.data) };
}

/** The five `BeaconBlockHeader` fields, as VeriFe's struct wants them. */
function headerFixture(message) {
  return {
    slot: u64(message.slot),
    proposer_index: u64(message.proposer_index ?? message.proposerIndex),
    parent_root: message.parent_root ?? message.parentRoot,
    state_root: message.state_root ?? message.stateRoot,
    body_root: message.body_root ?? message.bodyRoot,
  };
}

/** A single-leaf proof as a flat branch, leaf-first, which is SSZ's order. */
function singleBranch(type, view, path) {
  const info = type.getPathInfo(path);
  const proof = createProof(view.node, { type: ProofType.single, gindex: info.gindex });
  return {
    gindex: Number(info.gindex),
    leaf: hex(proof.leaf),
    branch: proof.witnesses.map(hex),
  };
}

async function loadState() {
  let bytes;
  try {
    bytes = new Uint8Array(readFileSync(new URL(STATE_PATH, import.meta.url)));
  } catch {
    fail(`no cached state at tools/${STATE_PATH}. See tools/README.md for the fetch.`);
  }
  // The checkpoint endpoints serve whatever fork is current; try the ones
  // VeriFe knows, newest first, and say so if none fits.
  for (const fork of ["fulu", "electra", "deneb", "capella"]) {
    try {
      const view = ssz[fork].BeaconState.deserializeToViewDU(bytes);
      return { fork, view, bytes, sha256: "0x" + createHash("sha256").update(bytes).digest("hex") };
    } catch (error) {
      if (fork === "capella") fail(`cannot deserialize the cached state: ${error.message}`);
    }
  }
}

/** The EIP-4788 timestamp for an anchor root: the next block's payload time. */
async function anchorTimestamp(anchorSlot, anchorRoot) {
  for (let slot = anchorSlot + 1; slot <= anchorSlot + 32; slot++) {
    const response = await fetchShim(`${BEACON_API}/eth/v1/beacon/blocks/${slot}/root`, {
      headers: { Accept: "application/json" },
    });
    if (response.status === 404) continue; // missed slot
    if (!response.ok) fail(`blocks/${slot}/root -> ${response.status}`);
    const { value: block } = await getBlock(slot);
    const parent = hex(block.message.parentRoot);
    if (parent !== anchorRoot) {
      fail(
        `block at slot ${slot} has parent_root ${parent}, expected the anchor ${anchorRoot}`,
      );
    }
    return {
      timestamp: u64(block.message.body.executionPayload.timestamp),
      execution_slot: slot,
    };
  }
  fail("no block found in the 32 slots after the anchor");
}

/** Ask the real EIP-4788 contract what it returns for `timestamp`. */
async function eip4788Lookup(timestamp) {
  const data = "0x" + BigInt(timestamp).toString(16).padStart(64, "0");
  const body = {
    jsonrpc: "2.0",
    id: 1,
    method: "eth_call",
    params: [{ to: EIP_4788_ADDRESS, data }, "latest"],
  };
  const response = await fetchShim(EXECUTION_RPC, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) return null;
  const json = await response.json();
  return json.result ?? null;
}

async function recent(args) {
  const state = await loadState();
  const stateSlot = u64(state.view.slot);
  const stateRoot = hex(ssz[state.fork].BeaconState.hashTreeRoot(state.view.toValue()));

  // The anchor block is the one whose `state_root` is this state's root.
  const anchorHeaderJson = await getJson(`${BEACON_API}/eth/v1/beacon/headers/${stateSlot}`);
  const anchorHeader = headerFixture(anchorHeaderJson.data.header.message);
  const anchorRoot = anchorHeaderJson.data.root;
  if (anchorHeader.state_root !== stateRoot) {
    fail(
      `the cached state hashes to ${stateRoot}, but the header at slot ${stateSlot} ` +
        `commits to ${anchorHeader.state_root}. Re-download the state.`,
    );
  }

  const targetSlot = Number(args.slot);
  if (!(targetSlot >= stateSlot - SLOTS_PER_HISTORICAL_ROOT && targetSlot < stateSlot)) {
    fail(
      `slot ${targetSlot} is not on the recent path: it must be in ` +
        `[${stateSlot - SLOTS_PER_HISTORICAL_ROOT}, ${stateSlot - 1}]`,
    );
  }

  const index = targetSlot % SLOTS_PER_HISTORICAL_ROOT;
  const blockRoots = singleBranch(
    ssz[state.fork].BeaconState,
    state.view,
    ["blockRoots", index],
  );
  const forkVersion = singleBranch(
    ssz[state.fork].BeaconState,
    state.view,
    ["fork", "currentVersion"],
  );

  // The target header, which must hash to the leaf the state proof reached.
  const targetHeaderJson = await getJson(`${BEACON_API}/eth/v1/beacon/headers/${targetSlot}`);
  const targetHeader = headerFixture(targetHeaderJson.data.header.message);
  const targetRoot = targetHeaderJson.data.root;
  if (targetRoot !== blockRoots.leaf) {
    fail(
      `block_roots[${index}] is ${blockRoots.leaf} but the header at slot ` +
        `${targetSlot} has root ${targetRoot} (a missed slot repeats the ` +
        `previous root -- pick a slot that has a block)`,
    );
  }

  // The payload field, proven from the target block's body root.
  const { fork: targetFork, value: signed } = await getBlock(targetSlot);
  const body = ssz[targetFork].BeaconBlockBody.toViewDU(signed.message.body);
  const bodyRoot = hex(ssz[targetFork].BeaconBlockBody.hashTreeRoot(signed.message.body));
  if (bodyRoot !== targetHeader.body_root) {
    fail(`the block body hashes to ${bodyRoot}, header says ${targetHeader.body_root}`);
  }
  const fields = {};
  for (const [name, path] of [
    ["state_root", ["executionPayload", "stateRoot"]],
    ["receipts_root", ["executionPayload", "receiptsRoot"]],
    ["block_number", ["executionPayload", "blockNumber"]],
    ["timestamp", ["executionPayload", "timestamp"]],
    ["block_hash", ["executionPayload", "blockHash"]],
  ]) {
    fields[name] = singleBranch(ssz[targetFork].BeaconBlockBody, body, path);
  }
  const payload = signed.message.body.executionPayload;

  const anchor = await anchorTimestamp(stateSlot, anchorRoot);
  const onChain = await eip4788Lookup(anchor.timestamp);

  const fixture = {
    schema: "verife-fixture-1",
    kind: "recent",
    synthetic: false,
    provenance: {
      generated_at: new Date().toISOString().slice(0, 10),
      beacon_api: BEACON_API,
      state_endpoint: "https://beaconstate.ethstaker.cc/eth/v2/debug/beacon/states/finalized",
      state_ssz_sha256: state.sha256,
      state_ssz_bytes: state.bytes.length,
      consensus_specs: "v1.6.1",
      lodestar_types: "1.51.0",
      note:
        "Branch orders are leaf-first, as SSZ's is_valid_merkle_branch and " +
        "every consensus client emit them. expected_gindex values are for " +
        "cross-checking only: the Fe verifier derives its own.",
    },
    anchor: {
      fork: state.fork,
      slot: stateSlot,
      root: anchorRoot,
      header: anchorHeader,
      state_root: stateRoot,
      eip4788: {
        timestamp: anchor.timestamp,
        execution_payload_slot: anchor.execution_slot,
        contract: EIP_4788_ADDRESS,
        returns: onChain,
        matches_anchor_root: onChain === anchorRoot,
      },
      fork_version: {
        value: hex(state.view.fork.currentVersion),
        expected_gindex: forkVersion.gindex,
        leaf: forkVersion.leaf,
        branch: forkVersion.branch,
      },
    },
    target: {
      fork: targetFork,
      slot: targetSlot,
      root: targetRoot,
      header: targetHeader,
      block_roots: {
        index,
        expected_gindex: blockRoots.gindex,
        leaf: blockRoots.leaf,
        branch: blockRoots.branch,
      },
      payload: {
        values: {
          state_root: hex(payload.stateRoot),
          receipts_root: hex(payload.receiptsRoot),
          block_number: u64(payload.blockNumber),
          timestamp: u64(payload.timestamp),
          block_hash: hex(payload.blockHash),
        },
        proofs: Object.fromEntries(
          Object.entries(fields).map(([name, proof]) => [
            name,
            { expected_gindex: proof.gindex, leaf: proof.leaf, branch: proof.branch },
          ]),
        ),
      },
    },
  };

  const out = new URL(args.out, import.meta.url);
  writeFileSync(out, JSON.stringify(fixture, null, 2) + "\n");
  console.log(`wrote ${args.out}`);
  console.log(
    `  anchor  slot ${stateSlot} (${state.fork}) root ${anchorRoot.slice(0, 18)}…`,
  );
  console.log(
    `  target  slot ${targetSlot} (${targetFork}) block_roots[${index}], ` +
      `branch ${blockRoots.branch.length} deep`,
  );
  console.log(
    `  eip4788 t=${anchor.timestamp} -> ${onChain ? onChain.slice(0, 18) + "…" : "(no answer)"}` +
      `  ${onChain === anchorRoot ? "matches the anchor root" : "DOES NOT MATCH"}`,
  );
  console.log(
    `  payload block_hash ${fixture.target.payload.values.block_hash.slice(0, 18)}…, ` +
      `branch ${fields.block_hash.branch.length} deep`,
  );
}


/**
 * A missed-slot fixture: the one input that makes invariant 10 necessary.
 *
 * When a slot is missed, `process_slot` writes the previous block's root into
 * `block_roots[slot mod 8192]` again, so two slots map to one root. A prover
 * can then present a genuinely valid branch, at the genuinely correct gindex
 * for the slot they are claiming, carrying a header from an *earlier* slot.
 * Every check in the chain of commitments passes except `header.slot == s`.
 *
 * This is the recent-path cousin of the Lido 2025 bug: the node exists, the
 * branch is real, and only an exact-position check stands in the way.
 */
async function missed(args) {
  const state = await loadState();
  const stateSlot = u64(state.view.slot);
  const stateRoot = hex(ssz[state.fork].BeaconState.hashTreeRoot(state.view.toValue()));
  const anchorHeaderJson = await getJson(`${BEACON_API}/eth/v1/beacon/headers/${stateSlot}`);
  const anchorHeader = headerFixture(anchorHeaderJson.data.header.message);
  const anchorRoot = anchorHeaderJson.data.root;
  if (anchorHeader.state_root !== stateRoot) {
    fail(`the cached state hashes to ${stateRoot}, header says ${anchorHeader.state_root}`);
  }

  const claimed = Number(args.slot);
  if (!(claimed >= stateSlot - SLOTS_PER_HISTORICAL_ROOT && claimed < stateSlot)) {
    fail(`slot ${claimed} is not in the anchor's block_roots window`);
  }

  // It must really have been missed: no block, confirmed against the endpoint.
  const probe = await fetchShim(`${BEACON_API}/eth/v1/beacon/blocks/${claimed}/root`, {
    headers: { Accept: "application/json" },
  });
  if (probe.status !== 404) {
    fail(`slot ${claimed} has a block (status ${probe.status}); it was not missed`);
  }

  const index = claimed % SLOTS_PER_HISTORICAL_ROOT;
  const blockRoots = singleBranch(ssz[state.fork].BeaconState, state.view, ["blockRoots", index]);

  // The header that root actually belongs to: walk back to the last slot that
  // had a block.
  let holder = null;
  for (let slot = claimed - 1; slot > claimed - 32; slot--) {
    const response = await fetchShim(`${BEACON_API}/eth/v1/beacon/headers/${slot}`, {
      headers: { Accept: "application/json" },
    });
    if (response.status === 404) continue;
    const json = await response.json();
    if (json.data.root === blockRoots.leaf) {
      holder = { header: headerFixture(json.data.header.message), root: json.data.root, slot };
      break;
    }
  }
  if (!holder) fail(`no header in the 32 slots before ${claimed} matches block_roots[${index}]`);

  const anchor = await anchorTimestamp(stateSlot, anchorRoot);
  const onChain = await eip4788Lookup(anchor.timestamp);

  const fixture = {
    schema: "verife-fixture-1",
    kind: "missed_slot",
    synthetic: false,
    provenance: {
      generated_at: new Date().toISOString().slice(0, 10),
      beacon_api: BEACON_API,
      state_endpoint: "https://beaconstate.ethstaker.cc/eth/v2/debug/beacon/states/finalized",
      state_ssz_sha256: state.sha256,
      state_ssz_bytes: state.bytes.length,
      consensus_specs: "v1.6.1",
      lodestar_types: "1.51.0",
      note:
        "Slot " + claimed + " was missed: block_roots[" + index + "] repeats the root of " +
        "slot " + holder.slot + ". The branch and gindex are correct for the claimed slot, " +
        "so only header.slot == s (invariant 10) rejects this.",
    },
    anchor: {
      fork: state.fork,
      slot: stateSlot,
      root: anchorRoot,
      header: anchorHeader,
      state_root: stateRoot,
      eip4788: {
        timestamp: anchor.timestamp,
        execution_payload_slot: anchor.execution_slot,
        contract: EIP_4788_ADDRESS,
        returns: onChain,
        matches_anchor_root: onChain === anchorRoot,
      },
    },
    claim: {
      claimed_slot: claimed,
      missed: true,
      block_roots: {
        index,
        expected_gindex: blockRoots.gindex,
        leaf: blockRoots.leaf,
        branch: blockRoots.branch,
      },
      repeated_header: holder.header,
      repeated_header_slot: holder.slot,
      repeated_header_root: holder.root,
    },
  };

  writeFileSync(new URL(args.out, import.meta.url), JSON.stringify(fixture, null, 2) + "\n");
  console.log(`wrote ${args.out}`);
  console.log(`  anchor slot ${stateSlot}, claimed slot ${claimed} (missed)`);
  console.log(
    `  block_roots[${index}] is slot ${holder.slot}'s root ${holder.root.slice(0, 18)}…, ` +
      `branch ${blockRoots.branch.length} deep`,
  );
}


const HISTORICAL_ROOTS_LIMIT = 16777216;
const CAPELLA_FIRST_PERIOD = 758;

/** `gindex.fe`'s `concat`, in JS: splice `inner` under `outer`. */
function concatGindex(outer, inner) {
  const depth = BigInt(inner).toString(2).length - 1;
  return outer * 2 ** depth + (inner - 2 ** depth);
}

/** A proof of one gindex, for a position no `getPathInfo` path names. */
function gindexBranch(view, gindex) {
  const proof = createProof(view.node, { type: ProofType.single, gindex: BigInt(gindex) });
  return { gindex, leaf: hex(proof.leaf), branch: proof.witnesses.map(hex) };
}

/**
 * Rebuild a period's `Vector[Root, 8192]` from block roots.
 *
 * `process_slot` writes `hash_tree_root(state.latest_block_header)` into
 * `block_roots[slot mod 8192]` at every slot, so a missed slot leaves the
 * previous block's root there again. Rebuilding therefore means walking the
 * period in order and carrying the last root forward across gaps -- including
 * at the period's own start, where the carried root belongs to a block from
 * the period before.
 *
 * The result is only usable if it hashes to the `block_summary_root` the anchor
 * state commits to, which the caller checks. That check is what makes 8,192
 * fetched roots trustworthy rather than merely plausible.
 */
async function rebuildPeriod(period) {
  const first = period * SLOTS_PER_HISTORICAL_ROOT;
  const last = first + SLOTS_PER_HISTORICAL_ROOT - 1;
  const roots = new Array(SLOTS_PER_HISTORICAL_ROOT).fill(null);

  // One slot before the period: whatever is carried into index 0 if the
  // period's first slots were missed.
  let carried = null;
  for (let slot = first - 1; slot > first - 64; slot--) {
    const response = await fetchShim(`${BEACON_API}/eth/v1/beacon/blocks/${slot}/root`, {
      headers: { Accept: "application/json" },
    });
    if (response.status === 404) continue;
    if (!response.ok) fail(`blocks/${slot}/root -> ${response.status}`);
    carried = (await response.json()).data.root;
    break;
  }
  if (!carried) fail(`no block in the 64 slots before period ${period}`);

  // Fetch in batches, with a retry: 8,192 requests against a public endpoint.
  const BATCH = 12;
  const fetched = new Array(SLOTS_PER_HISTORICAL_ROOT).fill(undefined);
  let done = 0;
  for (let base = 0; base < SLOTS_PER_HISTORICAL_ROOT; base += BATCH) {
    const jobs = [];
    for (let k = 0; k < BATCH && base + k < SLOTS_PER_HISTORICAL_ROOT; k++) {
      const offset = base + k;
      jobs.push(
        (async () => {
          for (let attempt = 0; attempt < 4; attempt++) {
            const response = await fetchShim(
              `${BEACON_API}/eth/v1/beacon/blocks/${first + offset}/root`,
              { headers: { Accept: "application/json" } },
            ).catch(() => null);
            if (response && response.status === 404) return (fetched[offset] = null);
            if (response && response.ok) {
              return (fetched[offset] = (await response.json()).data.root);
            }
            await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)));
          }
          fail(`gave up on blocks/${first + offset}/root`);
        })(),
      );
    }
    await Promise.all(jobs);
    done += jobs.length;
    if (done % 1024 === 0) console.log(`  ... ${done}/${SLOTS_PER_HISTORICAL_ROOT} roots`);
  }

  let missed = 0;
  for (let offset = 0; offset < SLOTS_PER_HISTORICAL_ROOT; offset++) {
    if (fetched[offset] === null) missed++;
    else carried = fetched[offset];
    roots[offset] = carried;
  }
  console.log(`  period ${period}: slots ${first}..${last}, ${missed} missed`);
  return { roots, missed, first, last };
}

/** A historical-path fixture: a target older than the EIP-4788 window. */
async function historical(args) {
  const state = await loadState();
  const stateSlot = u64(state.view.slot);
  const stateType = ssz[state.fork].BeaconState;
  const stateRoot = hex(stateType.hashTreeRoot(state.view.toValue()));
  const anchorHeaderJson = await getJson(`${BEACON_API}/eth/v1/beacon/headers/${stateSlot}`);
  const anchorHeader = headerFixture(anchorHeaderJson.data.header.message);
  const anchorRoot = anchorHeaderJson.data.root;
  if (anchorHeader.state_root !== stateRoot) {
    fail(`the cached state hashes to ${stateRoot}, header says ${anchorHeader.state_root}`);
  }

  const targetSlot = Number(args.slot);
  const period = Math.floor(targetSlot / SLOTS_PER_HISTORICAL_ROOT);
  const index = period - CAPELLA_FIRST_PERIOD;
  if (index < 0) fail(`slot ${targetSlot} is before Capella's first period`);
  if (targetSlot >= stateSlot - SLOTS_PER_HISTORICAL_ROOT) {
    fail(`slot ${targetSlot} is on the recent path, not the historical one`);
  }

  // The summary's field 0, and the list's length mix-in leaf.
  const summary = singleBranch(stateType, state.view, [
    "historicalSummaries",
    index,
    "blockSummaryRoot",
  ]);
  const summariesGindex = Number(stateType.getPathInfo(["historicalSummaries"]).gindex);
  const length = state.view.historicalSummaries.length;
  const lengthProof = gindexBranch(state.view, concatGindex(summariesGindex, 3));
  // The mix-in leaf must be the little-endian `uint64` chunk of the length:
  // the same encoding `ssz::uint64_leaf` applies on the Fe side.
  const lengthChunk =
    "0x" +
    Buffer.concat([
      Buffer.from(BigInt(length).toString(16).padStart(16, "0").match(/../g).reverse().join(""), "hex"),
      Buffer.alloc(24),
    ]).toString("hex");
  if (lengthProof.leaf !== lengthChunk) {
    fail(
      `the mix-in leaf is ${lengthProof.leaf}, but length ${length} encodes to ${lengthChunk}. ` +
        `Either the gindex is wrong or the list length is not what it claims.`,
    );
  }
  if (!(index < length)) fail(`summary index ${index} is past the list length ${length}`);

  // The period vector, rebuilt and then required to match what the state
  // commits to.
  const period_data = await rebuildPeriod(period);
  const vectorType = stateType.fields.blockRoots;
  const vectorView = vectorType.toViewDU(
    period_data.roots.map(r => Buffer.from(r.slice(2), "hex")),
  );
  const rebuiltRoot = hex(vectorType.hashTreeRoot(vectorView.toValue()));
  if (rebuiltRoot !== summary.leaf) {
    fail(
      `the rebuilt period hashes to ${rebuiltRoot}, but the anchor state's ` +
        `block_summary_root for index ${index} is ${summary.leaf}. The rebuild is wrong ` +
        `and must not be used.`,
    );
  }
  const inPeriod = targetSlot % SLOTS_PER_HISTORICAL_ROOT;
  const periodProof = singleBranch(vectorType, vectorView, [inPeriod]);

  // The target header, which must hash to the leaf the period proof reached.
  const targetHeaderJson = await getJson(`${BEACON_API}/eth/v1/beacon/headers/${targetSlot}`);
  const targetHeader = headerFixture(targetHeaderJson.data.header.message);
  const targetRoot = targetHeaderJson.data.root;
  if (targetRoot !== periodProof.leaf) {
    fail(
      `the period vector holds ${periodProof.leaf} at index ${inPeriod}, but slot ` +
        `${targetSlot} has root ${targetRoot} (a missed slot repeats the previous root)`,
    );
  }

  // The payload fields, from the target body.
  const { fork: targetFork, value: signed } = await getBlock(targetSlot);
  const body = ssz[targetFork].BeaconBlockBody.toViewDU(signed.message.body);
  const bodyRoot = hex(ssz[targetFork].BeaconBlockBody.hashTreeRoot(signed.message.body));
  if (bodyRoot !== targetHeader.body_root) {
    fail(`the block body hashes to ${bodyRoot}, header says ${targetHeader.body_root}`);
  }
  const fields = {};
  for (const [name, path] of [
    ["state_root", ["executionPayload", "stateRoot"]],
    ["receipts_root", ["executionPayload", "receiptsRoot"]],
    ["block_number", ["executionPayload", "blockNumber"]],
    ["timestamp", ["executionPayload", "timestamp"]],
    ["block_hash", ["executionPayload", "blockHash"]],
  ]) {
    fields[name] = singleBranch(ssz[targetFork].BeaconBlockBody, body, path);
  }
  const payload = signed.message.body.executionPayload;

  const anchor = await anchorTimestamp(stateSlot, anchorRoot);
  const onChain = await eip4788Lookup(anchor.timestamp);

  const fixture = {
    schema: "verife-fixture-1",
    kind: "historical",
    synthetic: false,
    provenance: {
      generated_at: new Date().toISOString().slice(0, 10),
      beacon_api: BEACON_API,
      state_endpoint: "https://beaconstate.ethstaker.cc/eth/v2/debug/beacon/states/finalized",
      state_ssz_sha256: state.sha256,
      state_ssz_bytes: state.bytes.length,
      consensus_specs: "v1.6.1",
      lodestar_types: "1.51.0",
      period_rebuild: {
        period,
        first_slot: period_data.first,
        last_slot: period_data.last,
        missed_slots: period_data.missed,
        note:
          "Rebuilt from 8,192 block roots, carrying the previous root across " +
          "missed slots, and accepted only because it hashes to the " +
          "block_summary_root the anchor state commits to.",
      },
    },
    anchor: {
      fork: state.fork,
      slot: stateSlot,
      root: anchorRoot,
      header: anchorHeader,
      state_root: stateRoot,
      eip4788: {
        timestamp: anchor.timestamp,
        execution_payload_slot: anchor.execution_slot,
        contract: EIP_4788_ADDRESS,
        returns: onChain,
        matches_anchor_root: onChain === anchorRoot,
      },
    },
    target: {
      fork: targetFork,
      slot: targetSlot,
      root: targetRoot,
      header: targetHeader,
      summary: {
        index,
        length,
        expected_gindex: summary.gindex,
        block_summary_root: summary.leaf,
        branch: summary.branch,
        length_leaf: lengthProof.leaf,
        length_expected_gindex: lengthProof.gindex,
        length_branch: lengthProof.branch,
      },
      period: {
        index_in_period: inPeriod,
        expected_gindex: periodProof.gindex,
        leaf: periodProof.leaf,
        branch: periodProof.branch,
      },
      payload: {
        values: {
          state_root: hex(payload.stateRoot),
          receipts_root: hex(payload.receiptsRoot),
          block_number: u64(payload.blockNumber),
          timestamp: u64(payload.timestamp),
          block_hash: hex(payload.blockHash),
        },
        proofs: Object.fromEntries(
          Object.entries(fields).map(([name, proof]) => [
            name,
            { expected_gindex: proof.gindex, leaf: proof.leaf, branch: proof.branch },
          ]),
        ),
      },
    },
  };

  writeFileSync(new URL(args.out, import.meta.url), JSON.stringify(fixture, null, 2) + "\n");
  console.log(`wrote ${args.out}`);
  console.log(`  anchor slot ${stateSlot} (${state.fork}), target slot ${targetSlot} (${targetFork})`);
  console.log(
    `  summary[${index}] of ${length}: gindex ${summary.gindex}, branch ${summary.branch.length} deep`,
  );
  console.log(`  length leaf at gindex ${lengthProof.gindex}, branch ${lengthProof.branch.length} deep`);
  console.log(
    `  period ${period} rebuilt and matches block_summary_root; index ${inPeriod}, ` +
      `branch ${periodProof.branch.length} deep`,
  );
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith("--")) fail(`unexpected argument ${argv[i]}`);
    args[argv[i].slice(2)] = argv[i + 1];
  }
  return args;
}

const [command, ...rest] = process.argv.slice(2);
const args = parseArgs(rest);
if (command === "recent") {
  if (!args.slot || !args.out) fail("usage: gen_fixture.mjs recent --slot N --out PATH");
  await recent(args);
} else if (command === "historical") {
  if (!args.slot || !args.out) fail("usage: gen_fixture.mjs historical --slot N --out PATH");
  await historical(args);
} else if (command === "missed") {
  if (!args.slot || !args.out) fail("usage: gen_fixture.mjs missed --slot N --out PATH");
  await missed(args);
} else {
  fail("usage: gen_fixture.mjs (recent|historical|missed) --slot N --out PATH");
}
