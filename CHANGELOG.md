# Changelog

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
