# Changelog

## Unreleased
<!-- bump: patch -->

### Added
- New `channels/` subsystem: XOR-derived filesystem channels for attachment exchange between agents
- `resolve_channel` MCP tool (#7): returns deterministic shared directory path for file exchange
- `attachments` parameter on `send()` tool: typed attachment descriptors (inline or file-ref)
- `attachments` field in `read_inbox()` response: resolved absolute paths for file-ref attachments
- `channels/SPEC.md` with 6 invariants and 1 failure mode
- Attachment validation: type field required, path traversal (`..`) rejected
- Backward-compatible event replay: old events without `attachments` field replay with `None`

### Changed
- CI: split monolithic job into parallel lint, test, smoke, version-check jobs
- CI: pin Python 3.13, bump `requires-python` to `>=3.13` in both packages
- CI: add agent-runtime test step (previously only mesh-server tested)
- CI: add push trigger for main (previously PR-only)
- CI: enable uv dependency caching via `astral-sh/setup-uv@v4`
- CI: add smoke test job using `pytest -m smoke` (live pipeline test)

## 0.3.0

### Added
- Controller UI v0.3: event log panel with color-coded icons, auto-scroll, and pause indicator
- Controller UI v0.3: graph visualization polish — logarithmic edge width, volume-based color, 30s recency fade, 3-state nodes (active/idle/dead), edge hover tooltips
- Controller UI v0.3: node detail panel — UUID, PID, uptime, state, message sub-transcript, shutdown button
- Controller UI v0.3: controller inbox with unread badge on controller node
- Controller UI v0.3: WCAG AA accessibility — skip link, focus-visible outlines, ARIA roles, contrast compliance
- Controller UI v0.3: split bottom layout (event log left, detail panel right)
- Controller UI v0.3: updated design system with CSS variable rename and new color palette

### Changed
- Controller UI: CSS grid layout restructured from 2-panel to 5-panel (header, graph, event log, detail, sidebar)
- docs/ARCHITECTURE.md: controller-ui subsystem bumped to v0.3, new Controller UI Design section
- docs/DESIGN.md: Controller Interface section updated with v0.3 feature descriptions

## 0.2.0

### Added
- Project-init audit remediation: writing standards, contributing, lessons learned, work tracking sections in CLAUDE.md
- Release infrastructure: compute-version, release workflow, CI version-check
- CHANGELOG.md with bump convention
