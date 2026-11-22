// Build a block's receipts trie and emit a proof for one transaction.
//
//     node gen_receipt_fixture.mjs --block <n|latest> --out ../fixtures/mpt/receipts_mainnet.json
//
// Not Fe, and declared as supporting tooling. `eth_getProof` proves accounts
// and storage but there is no RPC that proves a *receipt*, so the receipts
// trie has to be rebuilt from the block's receipts and a proof read out of it.
//
// That rebuild is only trusted because it is checked: the trie this file
// builds must hash to the `receiptsRoot` in the block header, exactly as the
// period rebuild in gen_fixture.mjs must hash to the `block_summary_root` the
// anchor state commits to. If it does not match, nothing is written.
//
// It is also deliberately a second, independent implementation: VeriFe's own
// trie verifier is in Fe, and the proofs it is tested against are built here,
// in different code, from data neither wrote.
import { keccak256 } from "ethereum-cryptography/keccak.js";
import { writeFileSync } from "node:fs";
import { request } from "node:https";

const RPC = process.env.EXEC_RPC ?? "https://ethereum-rpc.publicnode.com";
const hex = (b) => "0x" + Buffer.from(b).toString("hex");
const bytes = (h) => Buffer.from(h.slice(2).padStart(h.length % 2 ? h.length - 1 : h.length - 2, "0"), "hex");
const fail = (m) => { console.error("error: " + m); process.exit(1); };

// Node 16 has no global `fetch`, and a 20-second timeout is not optional:
// `https.request` has no default, so a dropped socket hangs the run for ever.
function post(body) {
  return new Promise((resolve, reject) => {
    const url = new URL(RPC);
    const req = request(
      {
        hostname: url.hostname,
        path: url.pathname + url.search,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
        timeout: 20000,
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString("utf8") }));
      },
    );
    req.on("timeout", () => req.destroy(new Error("timed out after 20000ms")));
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

async function rpc(method, params) {
  const body = JSON.stringify({ jsonrpc: "2.0", id: 1, method, params });
  let last = null;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const r = await post(body);
      if (r.status >= 200 && r.status < 300) {
        const j = JSON.parse(r.text);
        if (j.error) fail(`${method} -> ${JSON.stringify(j.error)}`);
        return j.result;
      }
      last = `HTTP ${r.status}`;
    } catch (e) {
      last = e.message;
    }
    if (attempt < 3) await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
  }
  fail(`${method} -> ${last}`);
}

// --- RLP --------------------------------------------------------------------

const lenPrefix = (n, short, long) => {
  if (n <= 55) return Buffer.from([short + n]);
  const be = [];
  for (let v = n; v > 0; v = Math.floor(v / 256)) be.unshift(v % 256);
  return Buffer.from([long + be.length, ...be]);
};
const rlpStr = (b) =>
  b.length === 1 && b[0] < 0x80 ? Buffer.from(b) : Buffer.concat([lenPrefix(b.length, 0x80, 0xb7), b]);
const rlpList = (items) => {
  const body = Buffer.concat(items);
  return Buffer.concat([lenPrefix(body.length, 0xc0, 0xf7), body]);
};
/// A non-negative integer, with no leading zero byte; zero is the empty string.
const rlpInt = (v) => {
  let n = BigInt(v);
  const out = [];
  while (n > 0n) { out.unshift(Number(n & 0xffn)); n >>= 8n; }
  return rlpStr(Buffer.from(out));
};

// --- The trie ---------------------------------------------------------------

const nibbles = (b) => { const out = []; for (const x of b) { out.push(x >> 4, x & 0xf); } return out; };

/// Hex-prefix encoding: two flag bits in the top nibble, and a zero padding
/// nibble when the path has an even number of nibbles.
function hexPrefix(path, isLeaf) {
  const flag = (isLeaf ? 2 : 0) + (path.length % 2);
  const nib = path.length % 2 ? [flag, ...path] : [flag, 0, ...path];
  const out = [];
  for (let i = 0; i < nib.length; i += 2) out.push((nib[i] << 4) | nib[i + 1]);
  return Buffer.from(out);
}

/// A node's reference as its parent names it: the node inline if its encoding
/// is shorter than 32 bytes, otherwise its keccak hash.
const ref = (enc) => (enc.length < 32 ? enc : rlpStr(Buffer.from(keccak256(enc))));

/// Build the subtree for `entries`, all of which agree on their first `depth`
/// nibbles. Returns the node's own RLP encoding.
function build(entries, depth) {
  if (entries.length === 1) {
    const [path, value] = entries[0];
    return rlpList([rlpStr(hexPrefix(path.slice(depth), true)), rlpStr(value)]);
  }
  // An extension, if every entry shares more nibbles beyond `depth`.
  let shared = 0;
  const first = entries[0][0];
  outer: for (;;) {
    const at = depth + shared;
    if (at >= first.length) break;
    const want = first[at];
    for (const [path] of entries) {
      if (at >= path.length || path[at] !== want) break outer;
    }
    shared += 1;
  }
  if (shared > 0) {
    const child = build(entries, depth + shared);
    return rlpList([rlpStr(hexPrefix(first.slice(depth, depth + shared), false)), ref(child)]);
  }
  // Otherwise a branch: one slot per nibble, plus a value for a key that ends
  // exactly here.
  const slots = Array.from({ length: 16 }, () => []);
  let value = Buffer.alloc(0);
  for (const entry of entries) {
    const [path, v] = entry;
    if (path.length === depth) value = v;
    else slots[path[depth]].push(entry);
  }
  const items = slots.map((group) => (group.length ? ref(build(group, depth + 1)) : rlpStr(Buffer.alloc(0))));
  items.push(rlpStr(value));
  return rlpList(items);
}

/// Walk the trie for `target`, collecting the encodings of the nodes a
/// verifier has to be given: every node reached through a *hash* reference.
/// An embedded node is inside its parent's bytes and is not a proof element.
function prove(entries, target, depth, out) {
  const node = build(entries, depth);
  out.push(node);
  if (entries.length === 1) return;
  let shared = 0;
  const first = entries[0][0];
  outer: for (;;) {
    const at = depth + shared;
    if (at >= first.length) break;
    const want = first[at];
    for (const [path] of entries) { if (at >= path.length || path[at] !== want) break outer; }
    shared += 1;
  }
  if (shared > 0) {
    if (build(entries, depth + shared).length >= 32) prove(entries, target, depth + shared, out);
    return;
  }
  if (target.length === depth) return;
  const group = entries.filter(([p]) => p.length > depth && p[depth] === target[depth]);
  if (!group.length) return;
  if (build(group, depth + 1).length >= 32) prove(group, target, depth + 1, out);
}

// --- Receipts ---------------------------------------------------------------

/// A receipt as the trie stores it: the post-Byzantium four-item list, with a
/// one-byte type prefix for every envelope type but legacy.
function encodeReceipt(r) {
  const logs = rlpList(
    r.logs.map((log) =>
      rlpList([
        rlpStr(bytes(log.address)),
        rlpList(log.topics.map((t) => rlpStr(bytes(t)))),
        rlpStr(log.data === "0x" ? Buffer.alloc(0) : bytes(log.data)),
      ]),
    ),
  );
  const body = rlpList([
    rlpInt(BigInt(r.status)),
    rlpInt(BigInt(r.cumulativeGasUsed)),
    rlpStr(bytes(r.logsBloom)),
    logs,
  ]);
  const type = Number(BigInt(r.type ?? "0x0"));
  return type === 0 ? body : Buffer.concat([Buffer.from([type]), body]);
}

// --- Main -------------------------------------------------------------------

const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, "")] = process.argv[i + 1];
const blockArg = args.block ?? "latest";
const out = args.out ?? fail("usage: --block <n|latest> --out PATH");

const tag = blockArg === "latest" ? "latest" : "0x" + Number(blockArg).toString(16);
const header = await rpc("eth_getBlockByNumber", [tag, false]);
const number = Number(BigInt(header.number));
console.log(`block ${number}, receiptsRoot ${header.receiptsRoot}`);

const receipts = await rpc("eth_getBlockReceipts", ["0x" + number.toString(16)]);
if (!receipts?.length) fail("the block has no receipts");
console.log(`  ${receipts.length} receipts`);

const entries = receipts.map((r, i) => [nibbles(keccakKey(i)), encodeReceipt(r)]);
function keccakKey(i) { return rlpInt(BigInt(i)); }   // receipts are keyed by rlp(index), unhashed
entries.sort((a, b) => (a[0] < b[0] ? -1 : 1));

const rootEnc = build(entries, 0);
const root = hex(keccak256(rootEnc));
console.log(`  rebuilt root ${root}`);
if (root !== header.receiptsRoot) {
  fail(`the rebuilt receipts trie hashes to ${root} but the header says ` +
       `${header.receiptsRoot}. The rebuild is wrong and must not be used.`);
}
console.log("  matches the header: the rebuild is accepted");

// Prove the first receipt that carries at least two logs, so the Fe side has
// something worth decoding.
let index = receipts.findIndex((r) => (r.logs?.length ?? 0) >= 2);
if (index < 0) index = receipts.findIndex((r) => (r.logs?.length ?? 0) >= 1);
if (index < 0) fail("no receipt in this block has a log");
const target = nibbles(keccakKey(index));
const nodes = [];
prove(entries, target, 0, nodes);
console.log(`  proving receipt ${index} (${receipts[index].logs.length} logs): ${nodes.length} nodes`);

const chosen = receipts[index];
const fixture = {
  schema: "verife-receipt-fixture-1",
  synthetic: false,
  provenance: {
    execution_rpc: RPC,
    method: "eth_getBlockByNumber + eth_getBlockReceipts, trie rebuilt locally",
    block_number: number,
    block_hash: header.hash,
    receipts_root: header.receiptsRoot,
    receipt_count: receipts.length,
    note: "The receipts trie was rebuilt from the block's receipts and accepted " +
          "only because it hashes to the receiptsRoot in the header. There is no " +
          "RPC that serves a receipt proof.",
  },
  receipt: {
    tx_index: index,
    tx_hash: chosen.transactionHash,
    type: chosen.type,
    status: chosen.status,
    cumulative_gas_used: chosen.cumulativeGasUsed,
    key: hex(keccakKey(index)),
    encoded: hex(encodeReceipt(chosen)),
    proof: nodes.map(hex),
    logs: chosen.logs.map((l) => ({ address: l.address, topics: l.topics, data: l.data })),
  },
};
writeFileSync(out, JSON.stringify(fixture, null, 2));
console.log(`wrote ${out}`);
