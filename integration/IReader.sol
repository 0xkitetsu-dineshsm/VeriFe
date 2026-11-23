// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/// @title IReader — the execution half: a state root to a storage slot
/// @notice GENERATED from `out/Reader.abi.json` by
/// `tools/gen_solidity_iface.py`. Do not edit by hand.
///
/// Reads into a root. `read*` takes a state root as an ARGUMENT and verifies
/// only the trie walk; `prove*` proves the root it walks out of a beacon root.
///
/// Every function is `external returns`, none is `view`: the historical arms
/// write the period cache as a side effect of an honest proof, so they cannot
/// be `staticcall`ed. Use the `proveCached*` arms for a read-only query once a
/// period has been proven once.
/// @dev The five SSZ fields of a `BeaconBlockHeader`, in order.
///
/// NOT trusted for arriving: the verifier hashes it and requires the result to
/// equal a root it has already proven, so a wrong header reverts rather than
/// returning a wrong answer.
struct BeaconBlockHeader {
    uint64 slot;
    uint64 proposerIndex;
    uint256 parentRoot;
    uint256 stateRoot;
    uint256 bodyRoot;
}

interface IReader {
    function proveHistoricalCapellaStorageSlot(
        uint64 anchor_timestamp,
        BeaconBlockHeader calldata anchor_header,
        uint256[8] calldata fork_branch,
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint64 summary_index,
        uint64 summary_count,
        uint256[32] calldata summary_branch,
        uint256[7] calldata length_branch,
        uint256[13] calldata period_branch,
        uint256[8] calldata payload_branch,
        uint256 state_root,
        uint256 account,
        uint256 slot,
        bytes calldata account_proof,
        bytes calldata storage_proof
    ) external returns (uint256);

    function proveRecentReceiptLog(
        uint64 anchor_timestamp,
        BeaconBlockHeader calldata anchor_header,
        uint256[8] calldata fork_branch,
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[19] calldata block_roots_branch,
        uint256[9] calldata payload_branch,
        uint256 receipts_root,
        bytes calldata receipt_key,
        bytes calldata receipt_proof,
        uint256 log_index
    ) external returns (uint256);

    function readAccount(
        uint256 state_root,
        uint256 account,
        bytes calldata account_proof
    ) external returns (uint256);

    function readStorageSlot(
        uint256 state_root,
        uint256 account,
        uint256 slot,
        bytes calldata account_proof,
        bytes calldata storage_proof
    ) external returns (uint256);
}
