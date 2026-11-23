// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/// @title IVerife — the consensus half: an EIP-4788 root to an execution payload field
/// @notice GENERATED from `out/Verife.abi.json` by
/// `tools/gen_solidity_iface.py`. Do not edit by hand.
///
/// Establishes roots from the one trusted input -- whatever the beacon-roots
/// contract returns for a timestamp.
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

interface IVerife {
    function anchorRootAt(
        uint64 timestamp
    ) external returns (uint256);

    function cachePeriodSummaryRoot(
        uint64 anchor_timestamp,
        BeaconBlockHeader calldata anchor_header,
        uint256[8] calldata fork_branch,
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint64 summary_index,
        uint64 summary_count,
        uint256[32] calldata summary_branch,
        uint256[7] calldata length_branch,
        uint256[13] calldata period_branch
    ) external returns (uint256);

    function cachedSummaryRootForSlot(
        uint64 target_slot
    ) external returns (uint256);

    function proveCachedCapellaBlockHash(
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[13] calldata period_branch,
        uint256[8] calldata payload_branch,
        uint256 block_hash
    ) external returns (uint256);

    function proveCachedCapellaBlockNumber(
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[13] calldata period_branch,
        uint256[8] calldata payload_branch,
        uint64 block_number
    ) external returns (uint64);

    function proveCachedDenebBlockHash(
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[13] calldata period_branch,
        uint256[9] calldata payload_branch,
        uint256 block_hash
    ) external returns (uint256);

    function proveCachedElectraBlockHash(
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[13] calldata period_branch,
        uint256[9] calldata payload_branch,
        uint256 block_hash
    ) external returns (uint256);

    function proveHistoricalCapellaBlockHash(
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
        uint256 block_hash
    ) external returns (uint256);

    function proveHistoricalDenebBlockHash(
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
        uint256[9] calldata payload_branch,
        uint256 block_hash
    ) external returns (uint256);

    function proveHistoricalElectraBlockHash(
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
        uint256[9] calldata payload_branch,
        uint256 block_hash
    ) external returns (uint256);

    function proveRecentBlockHash(
        uint64 anchor_timestamp,
        BeaconBlockHeader calldata anchor_header,
        uint256[8] calldata fork_branch,
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[19] calldata recent_branch,
        uint256[9] calldata payload_branch,
        uint256 block_hash
    ) external returns (uint256);

    function proveRecentBlockNumber(
        uint64 anchor_timestamp,
        BeaconBlockHeader calldata anchor_header,
        uint256[8] calldata fork_branch,
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[19] calldata recent_branch,
        uint256[9] calldata payload_branch,
        uint64 block_number
    ) external returns (uint64);

    function proveRecentReceiptsRoot(
        uint64 anchor_timestamp,
        BeaconBlockHeader calldata anchor_header,
        uint256[8] calldata fork_branch,
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[19] calldata recent_branch,
        uint256[9] calldata payload_branch,
        uint256 receipts_root
    ) external returns (uint256);

    function proveRecentStateRoot(
        uint64 anchor_timestamp,
        BeaconBlockHeader calldata anchor_header,
        uint256[8] calldata fork_branch,
        uint64 target_slot,
        BeaconBlockHeader calldata target_header,
        uint256[19] calldata recent_branch,
        uint256[9] calldata payload_branch,
        uint256 state_root
    ) external returns (uint256);
}
