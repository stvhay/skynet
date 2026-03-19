# channels Subsystem Specification

## Purpose

XOR-derived filesystem channels for attachment exchange between mesh agents. Provides deterministic shared directories computed from participant UUIDs.

## Public Interface

| Function | Description |
|---|---|
| `resolve_channel(mesh_dir, participants)` | Compute XOR path, create dir, return `{channel_dir, attachments_dir}` |
| `ensure_channel_dir(channel_dir)` | Create channel dir with `attachments/` subdirectory |
| `xor_uuids(uuids)` | XOR sorted UUIDs as 128-bit ints, return full UUID string |

## Invariants

- **CH-INV-1**: XOR of two UUIDs is symmetric — `XOR(A,B) == XOR(B,A)`
- **CH-INV-2**: XOR of three+ UUIDs is associative — order-independent
- **CH-INV-3**: XOR result is a valid full UUID string (8-4-4-4-12 hex)
- **CH-INV-4**: Broadcast UUID resolves to `.mesh/channels/all/`
- **CH-INV-5**: `ensure_channel_dir` creates directory with `attachments/` subdirectory
- **CH-INV-6**: `resolve_channel` computes XOR path and creates directory lazily

## Failure Modes

- **CH-FAIL-1**: `resolve_channel` with fewer than 2 participants raises ValueError

## Filesystem Layout

```
.mesh/
  channels/
    <xor-uuid>/           <- XOR-derived pair/group channel
      attachments/
    all/                  <- well-known broadcast channel
      attachments/
```

## Properties

- **Symmetric**: `XOR(A,B) = XOR(B,A)` — both parties compute the same directory
- **Associative**: `XOR(A,B,C)` = same regardless of grouping
- **Deterministic**: No coordination or lookup needed
- **Standalone**: No imports from mesh-server or agent-runtime
