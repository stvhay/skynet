# Design: Controller UI v0.3 — Event Log, Node Detail, Graph Polish

**Issue:** #12 — feat: controller UI v0.3 — event log, node detail, graph polish
**Date:** 2026-03-16
**Branch:** feature/12-controller-ui-v03

## Problem

After live-testing the mesh with real agents (improv troupe scenario), the controller couldn't follow conversation flow or see final output. The dashboard shows the graph but lacks monitoring depth — no event history, no way to inspect individual agents, no inbox for results.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | Vanilla JS (no build step) | Features are additive UI panels, not structural changes |
| Layout | Split bottom: event log + detail panel | Event log always visible; detail panel for drill-down |
| Inbox UX | Badge on controller node + dedicated panel | Badge for awareness, panel for reading |
| Message display | Auto-wrap (no expand/collapse) | Simpler; accept scrolling cost |
| Recency fade | 30s | Agents have long think times between messages |
| Detail panel | Repurpose existing bottom panel | Split into event log (left) + context-sensitive detail (right) |
| WCAG | AA requirements (not best-effort) | Color + icon dual-coding, contrast, ARIA, keyboard |
| Epic structure | Single issue #12 | All changes in one file; merge conflicts worse if split |
| Design direction | Precision & Density + Data & Analysis | Dense monitoring, technical users, dev tool |

## Layout

```
grid-template-areas:
  "header  header  sidebar"
  "graph   graph   sidebar"
  "evlog   detail  sidebar"

grid-template-rows: auto 1fr 280px
grid-template-columns: 1fr 1fr 280px
```

```
┌─────────── Header ──────────────────┬─ Sidebar ─┐
│ MCP Mesh  [connected/disconnected]  │ Spawn     │
├─────────────────────────────────────┤ --------- │
│                                     │ Send      │
│  Graph (D3 force-directed)          │           │
│                                     │           │
├────── Event Log ─────┬─ Detail ─────┼───────────┤
│ [12:01] ● a3f2 reg   │ Node: a3f2   │           │
│ [12:01] → a3f2→b7c1  │ UUID: ...    │           │
│ [12:02] ● b7c1 reg   │ Messages:    │           │
└──────────────────────┴──────────────┴───────────┘
```

Bottom area: 280px tall, split ~60/40. Draggable resize handle between graph and bottom panels.

## Design Direction

**Precision & Density** blended with **Data & Analysis**.

### Color System

| Variable | Value | Usage | Contrast |
|----------|-------|-------|----------|
| `--bg-primary` | `#1a1a2e` | Main background | — |
| `--bg-panel` | `#16213e` | Panel backgrounds | — |
| `--bg-hover` | `#1e2a4a` | Hover states | — |
| `--border` | `#2a2a4a` | Panel/element borders | — |
| `--text-primary` | `#e0e0e0` | Primary text | 9.5:1 |
| `--text-secondary` | `#a0a0b0` | Secondary text | 5.2:1 |
| `--text-muted` | `#707080` | Decorative only | 3.6:1 |
| `--accent` | `#00d4ff` | Cyan accent | 8.1:1 |
| `--status-green` | `#4ade80` | Registered, alive | — |
| `--status-red` | `#f87171` | Deregistered, dead | — |
| `--status-yellow` | `#fbbf24` | Active/processing | — |
| `--status-gray` | `#6b7280` | Idle, drained | — |

### Typography

- System monospace for data: `ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace`
- System sans for labels/headers
- `font-variant-numeric: tabular-nums` for columnar alignment
- No CDN fonts

### Surface Treatment

- Borders-only depth (no shadows — invisible on dark backgrounds)
- 4px border radius (sharp, technical)
- 4px spacing grid (8px within, 12px between, 16px panel padding)
- Restrained animation: 150ms micro, 200ms transitions

## Feature 1: Event Log Panel

**Location:** Bottom-left, ~60% width.

**Content:** All events chronologically — AgentRegistered, AgentDeregistered, MessageEnqueued, MessageDrained.

**Row format:**
```
[HH:MM:SS] ● a3f2 registered (pid 12345)
[HH:MM:SS] ✕ b7c1 shutdown (SELF_SHUTDOWN)
[HH:MM:SS] → a3f2 → b7c1: "Hello, I'm the director..."
[HH:MM:SS] ← b7c1 drained msg abc123
```

- Icon + color dual-coding (WCAG): `●` green, `✕` red, `→` cyan, `←` gray
- Full message text, auto-wrapped
- Append-only rendering (no innerHTML replacement)
- Events stored in `allEvents[]` array (separate from `allMessages[]`)

**Auto-scroll:**
- Scrolls to bottom on new events
- Pauses on manual scroll-up
- Resumes when scrolled back to bottom (20px threshold)
- "Auto-scroll paused" indicator bar when paused

**Accessibility:**
- `<div id="event-log" role="log" aria-live="polite" aria-label="Event log">`
- Tab-focusable, arrow keys to scroll

## Feature 2: Graph Visualization Polish

### Edge thickness/color by volume

- Logarithmic scale: `strokeWidth = Math.min(1 + Math.log2(count + 1) * 1.5, 6)`
- Color interpolation: dim gray (#666) → bright cyan (#0ff) based on normalized count
- `d3.interpolateRgb` for smooth gradient

### Recency indicators (30s fade)

- Each edge/node tracks `lastActivityTime`
- 1s `requestAnimationFrame` tick updates opacity: `Math.max(0.3, 1.0 - (now - lastActivityTime) / 30000)`
- Resets on new message
- Controller node exempt (always full opacity)

### Node states (3 visual modes)

| State | Visual | Condition |
|-------|--------|-----------|
| Active | Solid green + animated pulse ring | Message in last 5s |
| Idle | Green fill, no pulse, glow | Alive, no recent activity |
| Dead | Gray outline, no fill, no glow | AgentDeregistered |

- Pulse ring: CSS `@keyframes pulse-ring` — expanding ring, 2s loop

### Edge labels on hover

- Positioned `<div>` tooltip (not SVG `<title>`)
- Content: "a3f2 → b7c1 / 12 messages / Last: truncated 40 chars"
- Show on mouseenter, hide on mouseleave

## Feature 3: Node Detail Panel

**Location:** Bottom-right, ~40% width. Context-sensitive.

### Modes

**Node detail** (click a node):
- UUID (full), PID, state (Active/Idle/Dead), uptime (live-updating 1s)
- Sub-transcript: all messages to/from this agent, chronological
- Shutdown button (calls POST /api/agents/{uuid}/shutdown, confirm dialog, disabled for dead/controller)

**Edge detail** (click an edge):
- Filtered message list between two nodes (current behavior, relocated)

**Controller inbox** (click controller badge or "Inbox" tab):
- Fetches GET /api/inbox
- Messages addressed to controller, newest first
- Badge on controller node shows unread count (since last inbox view)
- Badge clears on open

**Empty state:**
- "Click a node or edge to inspect"

**Accessibility:**
- `role="tabpanel"` with ARIA tabs pattern
- `aria-label` on shutdown button
- Focus-visible outlines

## Feature 4: WCAG AA Requirements

| Requirement | Implementation |
|-------------|---------------|
| Color + icon | Event types have icon prefixes alongside color |
| Contrast 4.5:1 | All readable text meets ratio against bg-primary |
| `role="log"` | Event log with `aria-live="polite"` |
| `role="tabpanel"` | Detail panel modes use ARIA tabs |
| Focus visible | `:focus-visible` ring on all interactive elements |
| Keyboard nav | Tab to reach panels; buttons keyboard-operable |
| Status announcements | Connection changes via `aria-live` region |
| Button labels | `aria-label` on shutdown, spawn, send |
| Skip link | Skip-to-content for keyboard users |

## Implementation Notes

- All changes in single file: `mesh-server/src/mesh_server/static/index.html`
- No new backend endpoints needed (all endpoints exist)
- No new dependencies (D3.js CDN already loaded)
- Current file: ~830 lines; expect ~1200-1400 after changes

## Documentation Updates

### docs/ARCHITECTURE.md

**Subsystem Map table** — bump controller-ui to v0.3:
```markdown
| [controller-ui](../mesh-server/src/mesh_server/static/) | Web UI for human controller | v0.3 | — |
```

**New section after REST/SSE API:**
```markdown
## Controller UI Design

In the context of needing a monitoring dashboard for active mesh sessions, facing the choice between a framework-based SPA or vanilla JS, we decided to keep the single-file vanilla JS + D3.js v7 approach to maintain zero-build-step simplicity, accepting the trade-off of manual DOM management at scale.

### Design Direction

Precision & Density blended with Data & Analysis. Dark theme (`#1a1a2e`), cyan accent (`#00d4ff`), borders-only depth, monospace for all data values, 4px spacing grid. WCAG AA required for all readable text and interactive elements.

### Panel Layout

| Panel | Position | Content |
|-------|----------|---------|
| Header | Top | Title, SSE connection status |
| Graph | Center | D3 force-directed visualization with recency fade, volume-weighted edges, 3-state nodes |
| Event Log | Bottom-left | All events, color-coded + icon-prefixed, auto-tailing with pause-on-scroll |
| Detail Panel | Bottom-right | Context-sensitive: node detail, edge messages, or controller inbox |
| Sidebar | Right | Spawn and send controls |
```

### docs/DESIGN.md

**Replace Controller Interface section (lines 276-282):**
```markdown
### Controller Interface

The controller connects to the MCP server via streamable-HTTP. The Web UI renders:

- **Event log** — all events (register, deregister, message, drain) in a scrollable auto-tailing panel with color + icon coding
- **Graph visualization** — force-directed D3 graph with recency-fading edges (30s), volume-weighted edge thickness, 3-state nodes (active/idle/dead), hover tooltips
- **Node detail panel** — click a node to see UUID, PID, uptime, state, message sub-transcript, and shutdown button
- **Controller inbox** — badge on controller node + dedicated panel for messages addressed to controller, with unread tracking
- **Send interface** — select recipient, compose message
- **Spawn interface** — launch new agents with model, thinking budget, role, initial message
```

### Recommendation

After implementation, run `/codify-subsystem` on controller-ui to create a dedicated SPEC.md with UI-specific invariants.
