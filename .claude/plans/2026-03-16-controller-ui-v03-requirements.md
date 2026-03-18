# Controller UI v0.3 — UX Requirements

## Problem Statement

After live-testing the mesh with real agents (an improv troupe scenario), the controller couldn't follow conversation flow or see final output. The dashboard shows the graph but lacks monitoring depth — no event history, no way to inspect individual agents, no inbox for results addressed to the controller.

## User Model

- **Primary user:** Human controller — the developer who spawned the agents, monitoring locally
- **Context:** Active monitoring during mesh runs (minutes to hours). Split attention between dashboard and terminal/editor. Exploration/experimentation, not production ops.
- **Expertise:** High technical (wrote the mesh), moderate dashboard (wants it to work without learning)
- **Task frequency:** Per-session, sustained attention with bursts of interaction
- **Key behavior pattern:** Scan graph for activity → notice something → drill into detail → possibly act (send/shutdown)

## Success Criteria

- Controller can follow real-time conversation flow across 5+ agents without losing context
- Final results addressed to controller are immediately visible (not buried in event stream)
- Any agent can be inspected in 1 click (UUID, state, messages, controls)
- Graph conveys activity recency and volume at a glance
- All panels meet WCAG AA contrast and keyboard accessibility

## Modality

**GUI** — monitoring dashboard. Visual scanning, spatial layout, and drill-down are essential.

## Design Direction

**Precision & Density** blended with **Data & Analysis**.

- Dark theme (`#1a1a2e` foundation), cyan accent (`#00d4ff`)
- Borders-only depth (no shadows)
- 4px spacing grid, tight density
- System fonts — monospace for all data values, sans for labels
- Sharp 4px border radius
- Restrained animation (150ms micro, 200ms transitions; graph pulses are functional exceptions)
- Unicode symbols for event type indicators (no icon library)
- `tabular-nums` for columnar alignment

## Color System

| Variable | Value | Usage | Contrast on bg-primary |
|----------|-------|-------|----------------------|
| `--bg-primary` | `#1a1a2e` | Main background | — |
| `--bg-panel` | `#16213e` | Panel backgrounds | — |
| `--bg-hover` | `#1e2a4a` | Hover states | — |
| `--border` | `#2a2a4a` | Panel/element borders | — |
| `--text-primary` | `#e0e0e0` | Primary text | 9.5:1 ✓ |
| `--text-secondary` | `#a0a0b0` | Secondary text | 5.2:1 ✓ |
| `--text-muted` | `#707080` | Decorative only | 3.6:1 (not for readable text) |
| `--accent` | `#00d4ff` | Cyan accent | 8.1:1 ✓ |
| `--status-green` | `#4ade80` | Registered, alive | — |
| `--status-red` | `#f87171` | Deregistered, dead | — |
| `--status-yellow` | `#fbbf24` | Active/processing | — |
| `--status-gray` | `#6b7280` | Idle, drained | — |

## Constraints

- Single-file vanilla JS + D3.js v7 (CDN), no build step
- No framework (React/Vue/Svelte)
- No additional CDN dependencies beyond D3
- WCAG AA required for all readable text and interactive elements
- Must work in modern browsers (Chrome, Firefox, Safari)

## Interaction Patterns

### Scan → Notice → Drill → Act

1. **Scan:** Graph overview shows all agents, edges pulse and fade with activity
2. **Notice:** Bright edges = recent activity, thick edges = high volume, badge on controller = inbox messages
3. **Drill:** Click node → detail panel shows full info; click edge → filtered messages
4. **Act:** Send message from sidebar, shutdown from detail panel, spawn from sidebar

### Panel Focus Model

- Only one bottom-right panel mode active at a time (node detail, edge detail, inbox, empty)
- Selection state: click node/edge to select, click background to deselect
- Inbox accessible via controller node badge click OR tab in detail panel
