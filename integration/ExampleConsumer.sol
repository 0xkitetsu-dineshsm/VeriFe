// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

import {IReader, BeaconBlockHeader} from "./IReader.sol";

/// @title What a contract that wants old Ethereum state actually writes
/// @notice Not deployed and not audited. It exists to answer one question a
/// judge or an integrator will reasonably ask: *what does using this look
/// like?*
///
/// The scenario: an airdrop, a retroactive grant, a dispute — anything that
/// has to pay out based on what a contract's storage held at a block in the
/// past. On Ethereum today you cannot read that. You trust an oracle, or a
/// multisig, or a signed snapshot.
///
/// With VeriFe the claimant brings the proof and the contract checks it. The
/// contract trusts nothing but the beacon root the EVM already gives it.
contract ExampleConsumer {
    IReader public immutable reader;

    /// The block whose state this consumer pays out against, pinned at
    /// construction so a claimant cannot choose a block that suits them.
    uint64 public immutable targetSlot;

    /// The contract whose storage decides eligibility, and the slot in it.
    uint256 public immutable subject;
    uint256 public immutable slot;

    mapping(address => bool) public claimed;

    error AlreadyClaimed();
    error NotEligible();

    constructor(IReader reader_, uint64 targetSlot_, uint256 subject_, uint256 slot_) {
        reader = reader_;
        targetSlot = targetSlot_;
        subject = subject_;
        slot = slot_;
    }

    /// @notice Claim, by proving what `subject`'s storage held at `targetSlot`.
    ///
    /// Everything after `anchorTimestamp` is the proof the claimant built
    /// off-chain with `tools/prove.sh`. None of it is trusted: the chain of
    /// hashes either reaches the beacon root the EVM reports for
    /// `anchorTimestamp`, or the call reverts.
    ///
    /// @dev `targetSlot` is NOT a parameter. If a claimant could choose the
    /// block, they would choose one where they were eligible — the whole
    /// point is that the contract fixed it in advance. This is the mistake
    /// this library exists to make hard, applied one level up: the dangerous
    /// value is the one you let the caller pick.
    /// @notice The proof a claimant brings, bundled.
    ///
    /// @dev Bundled for a concrete reason, not tidiness: passing the sixteen
    /// arguments flat makes `claim` fail to compile with
    /// "Stack too deep" under solc 0.8.x without `--via-ir`. A `calldata`
    /// struct is read field by field straight from calldata, so it never
    /// occupies stack slots. Worth knowing before writing an integration --
    /// it is the first thing anyone calling this will hit.
    struct StorageProof {
        uint64 anchorTimestamp;
        BeaconBlockHeader anchorHeader;
        uint256[8] forkBranch;
        BeaconBlockHeader targetHeader;
        uint64 summaryIndex;
        uint64 summaryCount;
        uint256[32] summaryBranch;
        uint256[7] lengthBranch;
        uint256[13] periodBranch;
        uint256[8] payloadBranch;
        uint256 stateRoot;
        bytes accountProof;
        bytes storageProof;
    }

    /// @notice Claim, by proving what `subject`'s storage held at `targetSlot`.
    ///
    /// Everything in `p` is the proof the claimant built off-chain with
    /// `tools/prove.sh`. None of it is trusted: the chain of hashes either
    /// reaches the beacon root the EVM reports for `p.anchorTimestamp`, or the
    /// call reverts.
    ///
    /// @dev `targetSlot` is deliberately NOT in `p`. If a claimant could
    /// choose the block, they would choose one where they were eligible --
    /// the point is that the contract fixed it in advance. The same lesson
    /// this library is built around, one level up: the dangerous value is the
    /// one you let the caller pick.
    function claim(StorageProof calldata p) external {
        if (claimed[msg.sender]) revert AlreadyClaimed();

        uint256 value = reader.proveHistoricalCapellaStorageSlot(
            p.anchorTimestamp,
            p.anchorHeader,
            p.forkBranch,
            targetSlot,              // fixed at construction, never from calldata
            p.targetHeader,
            p.summaryIndex,
            p.summaryCount,
            p.summaryBranch,
            p.lengthBranch,
            p.periodBranch,
            p.payloadBranch,
            p.stateRoot,
            subject,
            slot,
            p.accountProof,
            p.storageProof
        );

        // `value` is now a proven fact about Ethereum's state in the past.
        // What it means is this contract's business; that it is true is the
        // library's.
        if (value == 0) revert NotEligible();

        claimed[msg.sender] = true;
        // ... pay out ...
    }
}
