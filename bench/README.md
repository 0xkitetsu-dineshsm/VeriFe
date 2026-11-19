# bench

The gas benchmark: VeriFe's EVM verifier against a minimal Solidity baseline
written in this repo, in the style of Lido's `GIndex`/`SSZ` libraries.

Both sides run the same fixtures on a local EVM from one script that CI reruns.
The report covers total gas for the recent and the historical path, gas per
Merkle level, calldata bytes and runtime size, with the EIP-4788 call counted
equally on both sides. The solc version and optimizer settings are stated with
the numbers.

Where Fe costs more, the number goes in the table as it is, with the cause
named next to it.

Empty for now.
