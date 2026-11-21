// A missed slot leaves block_roots[s mod 8192] equal to its predecessor's
// entry: process_slot writes the previous block's root again. So the cached
// anchor state names every missed slot in its own window, offline.
import { readFileSync } from "node:fs";
import { ssz } from "@lodestar/types";
const bytes = new Uint8Array(readFileSync(new URL("cache/state/finalized.ssz", import.meta.url)));
const state = ssz.fulu.BeaconState.deserialize(bytes);
const S = Number(state.slot);
const roots = state.blockRoots.map(r => Buffer.from(r).toString("hex"));
const hits = [];
for (let slot = S - 8191; slot < S; slot++) {
  const i = slot % 8192, j = (slot - 1 + 8192) % 8192;
  if (roots[i] === roots[j]) hits.push(slot);
}
console.log("anchor slot", S, "| window", S - 8192, "..", S - 1);
console.log("missed slots in the window:", hits.length);
console.log(hits.slice(0, 12).join(" "));
