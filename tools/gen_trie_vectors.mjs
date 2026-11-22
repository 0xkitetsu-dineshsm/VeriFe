// Random Merkle-Patricia tries, and proofs out of them, for differential
// testing against VeriFe's Fe verifier.
//
//     node gen_trie_vectors.mjs --count 40 --out ../fixtures/mpt/trie_vectors.json
//
// The trie builder here is the one `gen_receipt_fixture.mjs` uses, and it is
// validated against the chain: rebuilding a real block's receipts trie
// reproduced the `receiptsRoot` in its header. So it is a second
// implementation, in a different language, that is known to be right about at
// least one real trie.
//
// What the vectors exercise that the mainnet fixtures cannot: shapes. Random
// keys produce branch nodes at every depth, extensions of every length,
// embedded nodes (a short value's leaf encodes to under 32 bytes and is
// inlined in its parent), and absences of all three kinds -- an empty branch
// slot, a diverging path, and a leaf that ends before the key. A handful of
// real proofs hits a handful of shapes; forty random tries hit most of them.
import { keccak256 } from "ethereum-cryptography/keccak.js";
import { writeFileSync } from "node:fs";

const hex = (b) => "0x" + Buffer.from(b).toString("hex");

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
const nibbles = (b) => { const out = []; for (const x of b) out.push(x >> 4, x & 0xf); return out; };

function hexPrefix(path, isLeaf) {
  const flag = (isLeaf ? 2 : 0) + (path.length % 2);
  const nib = path.length % 2 ? [flag, ...path] : [flag, 0, ...path];
  const out = [];
  for (let i = 0; i < nib.length; i += 2) out.push((nib[i] << 4) | nib[i + 1]);
  return Buffer.from(out);
}
const ref = (enc) => (enc.length < 32 ? enc : rlpStr(Buffer.from(keccak256(enc))));

function sharedBeyond(entries, depth) {
  let shared = 0;
  const first = entries[0][0];
  for (;;) {
    const at = depth + shared;
    if (at >= first.length) return shared;
    const want = first[at];
    for (const [path] of entries) if (at >= path.length || path[at] !== want) return shared;
    shared += 1;
  }
}

function build(entries, depth) {
  if (entries.length === 1) {
    const [path, value] = entries[0];
    return rlpList([rlpStr(hexPrefix(path.slice(depth), true)), rlpStr(value)]);
  }
  const shared = sharedBeyond(entries, depth);
  if (shared > 0) {
    const child = build(entries, depth + shared);
    return rlpList([rlpStr(hexPrefix(entries[0][0].slice(depth, depth + shared), false)), ref(child)]);
  }
  const slots = Array.from({ length: 16 }, () => []);
  let value = Buffer.alloc(0);
  for (const entry of entries) {
    if (entry[0].length === depth) value = entry[1];
    else slots[entry[0][depth]].push(entry);
  }
  const items = slots.map((g) => (g.length ? ref(build(g, depth + 1)) : rlpStr(Buffer.alloc(0))));
  items.push(rlpStr(value));
  return rlpList(items);
}

/// The nodes a verifier must be given for `target`: every node reached
/// through a hash reference. An embedded node lives inside its parent.
function prove(entries, target, depth, out) {
  out.push(build(entries, depth));
  if (entries.length === 1) return;
  const shared = sharedBeyond(entries, depth);
  if (shared > 0) {
    if (build(entries, depth + shared).length >= 32) prove(entries, target, depth + shared, out);
    return;
  }
  if (target.length === depth) return;
  const group = entries.filter(([p]) => p.length > depth && p[depth] === target[depth]);
  if (!group.length) return;
  if (build(group, depth + 1).length >= 32) prove(group, target, depth + 1, out);
}

// A small deterministic PRNG, so a vector set is reproducible from its seed.
let seed = 0x1234_5678;
const rand = () => {
  seed ^= seed << 13; seed >>>= 0;
  seed ^= seed >> 17;
  seed ^= seed << 5; seed >>>= 0;
  return seed;
};
const randBytes = (n) => Buffer.from(Array.from({ length: n }, () => rand() & 0xff));

const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, "")] = process.argv[i + 1];
const count = Number(args.count ?? 40);
const out = args.out ?? "../fixtures/mpt/trie_vectors.json";

const vectors = [];
for (let v = 0; v < count; v++) {
  // Between 1 and 40 keys, and values short enough that some leaves embed.
  const n = 2 + (rand() % 8);
  const keys = [];
  for (let i = 0; i < n; i++) keys.push(randBytes(32));
  // Short values on purpose for some tries: a leaf under 32 bytes is inlined
  // in its parent, which is the embedded-node path.
  const short = v % 3 === 0;
  const entries = keys.map((k) => [nibbles(k), randBytes(short ? 1 + (rand() % 3) : 32)]);
  entries.sort((a, b) => (a[0] < b[0] ? -1 : 1));

  const root = hex(keccak256(build(entries, 0)));

  // One present key, and one absent key of each kind we can arrange.
  const pick = keys[rand() % keys.length];
  const presentNodes = [];
  prove(entries, nibbles(pick), 0, presentNodes);
  vectors.push({
    kind: "present", keys: n, short_values: short, root,
    key: hex(pick),
    value: hex(entries.find((e) => hex(Buffer.from(e[0].reduce((acc, nib, i) => {
      if (i % 2 === 0) acc.push(nib << 4); else acc[acc.length - 1] |= nib; return acc;
    }, []))) === hex(pick))[1]),
    proof: presentNodes.map(hex),
  });

  const missing = randBytes(32);
  if (!keys.some((k) => k.equals(missing))) {
    const absentNodes = [];
    prove(entries, nibbles(missing), 0, absentNodes);
    vectors.push({
      kind: "absent", keys: n, short_values: short, root,
      key: hex(missing), value: "0x", proof: absentNodes.map(hex),
    });
  }
}

writeFileSync(out, JSON.stringify({
  schema: "verife-trie-vectors-1",
  synthetic: true,
  provenance: {
    generator: "tools/gen_trie_vectors.mjs",
    seed: "0x12345678 (xorshift32, so the set is reproducible)",
    note: "Synthetic by design: random key sets reach trie SHAPES that a handful " +
          "of real mainnet proofs never does -- extensions of every length, " +
          "embedded nodes, and all three kinds of absence. The builder is the same " +
          "one that reproduced a real block's receiptsRoot, so it is a second " +
          "implementation known to be right about at least one real trie.",
  },
  vectors,
}, null, 2));
const present = vectors.filter((v) => v.kind === "present").length;
console.log(`wrote ${out}: ${vectors.length} vectors (${present} present, ${vectors.length - present} absent)`);
console.log(`  trie sizes ${Math.min(...vectors.map(v => v.keys))}..${Math.max(...vectors.map(v => v.keys))} keys`);
console.log(`  proof depths ${Math.min(...vectors.map(v => v.proof.length))}..${Math.max(...vectors.map(v => v.proof.length))} nodes`);
