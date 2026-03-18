# Controller UI v0.3 Implementation Plan

**Issue:** #12 — feat: controller UI v0.3 — event log, node detail, graph polish
**Design:** docs/plans/2026-03-16-controller-ui-v03-design.md

> **For Claude:** Execute this plan using subagent-driven-development (same session) or executing-plans (separate session / teammate).

**Goal:** Upgrade the controller web UI with an event log panel, graph visualization polish (recency fade, volume-weighted edges, 3-state nodes), node detail panel with shutdown, and controller inbox with badge — all with WCAG AA accessibility.

**Architecture:** All changes are in the single-file UI (`mesh-server/src/mesh_server/static/index.html`). No backend changes needed — all API endpoints already exist. The CSS grid layout is restructured from 2-column to 3-column bottom area (event log + detail panel). D3.js v7 rendering is enhanced with recency fading, volume-weighted edge styling, and 3-state node visuals.

**Tech Stack:** Vanilla JS, D3.js v7 (CDN), CSS Grid, SSE

**Acceptance Criteria — what must be TRUE when this plan is done:**
- [ ] Bottom area splits into event log (left, ~60%) and detail panel (right, ~40%)
- [ ] Event log shows all 4 event types with icon + color dual-coding and timestamps
- [ ] Event log auto-scrolls to bottom, pauses on manual scroll-up, shows pause indicator
- [ ] Graph edges use logarithmic stroke width and volume-based color interpolation
- [ ] Graph edges and nodes fade from full opacity to 30% over 30 seconds of inactivity
- [ ] Agent nodes show 3 states: active (pulse ring), idle (glow only), dead (gray outline)
- [ ] Edge hover shows tooltip with message count and last message preview
- [ ] Clicking a node shows full UUID, PID, state, uptime, message sub-transcript, and shutdown button
- [ ] Clicking an edge shows filtered messages between the two nodes
- [ ] Controller node badge shows unread inbox count; clicking opens inbox panel
- [ ] Shutdown button calls POST /api/agents/{uuid}/shutdown with confirmation dialog
- [ ] All readable text meets WCAG AA 4.5:1 contrast ratio
- [ ] Event log has `role="log"` and `aria-live="polite"`
- [ ] Detail panel uses ARIA tabs pattern
- [ ] All interactive elements have `:focus-visible` outlines and `aria-label`
- [ ] docs/ARCHITECTURE.md and docs/DESIGN.md updated per design doc
- [ ] All existing tests still pass (`cd mesh-server && uv run pytest`)

**Dependencies:** None

---

### Task 1: Layout Restructure + CSS Variables + Event Log Panel

**Context:** The current UI is a single 829-line HTML file at `mesh-server/src/mesh_server/static/index.html`. It uses a CSS Grid layout with 2 columns (`1fr 280px`) and 3 rows (`auto 1fr 200px`). The bottom row is a single "detail panel" showing messages for selected nodes/edges.

This task restructures the grid to split the bottom area into two panels (event log left, detail panel right), updates CSS variables to the new design system, and implements the event log panel that shows all events with icon + color dual-coding and auto-scroll.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants from spec:**
- INV-21: GET /api/events streams events via SSE → the event log renders these events
- No new invariants to test — this is a UI-only change consuming existing SSE events

**Files:**
- Modify: `mesh-server/src/mesh_server/static/index.html` (entire file — CSS, HTML structure, and JS)

**Depends on:** Independent

**Step 1: Update CSS variables and grid layout**

Replace the existing `:root` CSS variables (lines 10-23) with the new design system:

```css
:root {
  --bg-primary: #1a1a2e;
  --bg-panel: #16213e;
  --bg-hover: #1e2a4a;
  --border: #2a2a4a;
  --text-primary: #e0e0e0;
  --text-secondary: #a0a0b0;
  --text-muted: #707080;
  --accent: #00d4ff;
  --status-green: #4ade80;
  --status-red: #f87171;
  --status-yellow: #fbbf24;
  --status-gray: #6b7280;
  --font-ui: -apple-system, 'Inter', system-ui, sans-serif;
  --font-mono: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
}
```

Update the `#app` grid to use named grid areas with the split bottom:

```css
#app {
  display: grid;
  grid-template-areas:
    "header  header  sidebar"
    "graph   graph   sidebar"
    "evlog   detail  sidebar";
  grid-template-columns: 3fr 2fr 280px;
  grid-template-rows: auto 1fr 280px;
  height: 100vh;
  gap: 0;
}
```

Update all CSS color references from old variable names to new ones:
- `--bg-base` → `--bg-primary`
- `--bg-surface` → `--bg-panel`
- `--bg-elevated` → `--bg-hover`
- `--accent-green` → `--status-green`
- `--accent-red` → `--status-red`
- `--accent-blue` → `--accent`

Update element grid assignments:
```css
header { grid-area: header; }
#graph-container { grid-area: graph; }
#event-log { grid-area: evlog; }
#detail-panel { grid-area: detail; }
#sidebar { grid-area: sidebar; }
```

The body background uses `--bg-primary`. Header uses `--bg-panel`. Graph container uses `--bg-primary`. Panels use `--bg-panel`.

**Step 2: Add event log HTML**

Insert a new `<div id="event-log">` element in the HTML between `#graph-container` and `#detail-panel`:

```html
<div id="event-log">
  <div class="panel-header">Event Log</div>
  <div class="panel-body" id="event-log-body" role="log" aria-live="polite" aria-label="Event log"></div>
  <div class="scroll-indicator" id="scroll-indicator" style="display:none">Auto-scroll paused — new events below</div>
</div>
```

**Step 3: Add event log CSS**

```css
#event-log {
  grid-area: evlog;
  border-top: 1px solid var(--border);
  border-right: 1px solid var(--border);
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.event-row {
  padding: 2px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  line-height: 1.4;
  word-wrap: break-word;
}

.event-row .event-time {
  color: var(--text-muted);
  margin-right: 6px;
}

.event-row.event-register .event-icon { color: var(--status-green); }
.event-row.event-deregister .event-icon { color: var(--status-red); }
.event-row.event-message .event-icon { color: var(--accent); }
.event-row.event-drain .event-icon { color: var(--status-gray); }

.scroll-indicator {
  padding: 4px 12px;
  font-size: 10px;
  color: var(--status-yellow);
  background: var(--bg-hover);
  border-top: 1px solid var(--border);
  text-align: center;
  flex-shrink: 0;
  cursor: pointer;
}
```

Also rename the existing `.detail-header` class to `.panel-header` and `.detail-body` to `.panel-body` for consistency across both panels (update the HTML and CSS references for `#detail-panel` accordingly).

**Step 4: Implement event log JavaScript**

Add a new `allEvents` array to the state section:
```javascript
const allEvents = []; // all events for the event log
let autoScroll = true;
```

Add the `renderEvent` function that appends a single event row (append-only, no innerHTML replacement):

```javascript
function renderEvent(event) {
  allEvents.push(event);
  const body = document.getElementById('event-log-body');
  const row = document.createElement('div');
  row.className = 'event-row';

  let icon, text, typeClass;
  switch (event.type) {
    case 'AgentRegistered':
      icon = '\u25cf'; // ●
      text = `${shortId(nodeIdFor(event.uuid))} registered${event.pid ? ' (pid ' + event.pid + ')' : ''}`;
      typeClass = 'event-register';
      break;
    case 'AgentDeregistered':
      icon = '\u2715'; // ✕
      text = `${shortId(nodeIdFor(event.uuid))} shutdown (${event.reason || 'unknown'})`;
      typeClass = 'event-deregister';
      break;
    case 'MessageEnqueued':
      icon = '\u2192'; // →
      const from = shortId(nodeIdFor(event.from_uuid));
      const to = shortId(nodeIdFor(event.to_uuid));
      const preview = event.message || event.command || '';
      text = `${from} \u2192 ${to}: "${escapeHtml(preview)}"`;
      typeClass = 'event-message';
      break;
    case 'MessageDrained':
      icon = '\u2190'; // ←
      text = `${shortId(nodeIdFor(event.by_uuid))} drained msg ${event.message_id ? event.message_id.substring(0, 8) : ''}`;
      typeClass = 'event-drain';
      break;
    default:
      return;
  }

  row.classList.add(typeClass);
  const ts = event.timestamp ? formatTime(event.timestamp) : '';
  row.innerHTML = `<span class="event-time">[${ts}]</span><span class="event-icon">${icon}</span> ${text}`;
  body.appendChild(row);

  // Auto-scroll
  if (autoScroll) {
    body.scrollTop = body.scrollHeight;
  }
}
```

Add auto-scroll pause/resume logic:

```javascript
(function setupEventLogScroll() {
  const body = document.getElementById('event-log-body');
  const indicator = document.getElementById('scroll-indicator');

  body.addEventListener('scroll', () => {
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 20;
    autoScroll = atBottom;
    indicator.style.display = atBottom ? 'none' : 'block';
  });

  indicator.addEventListener('click', () => {
    body.scrollTop = body.scrollHeight;
    autoScroll = true;
    indicator.style.display = 'none';
  });
})();
```

**Step 5: Wire event log into handleEvent**

Update `handleEvent()` to call `renderEvent(event)` for every event type (including `MessageDrained`, which was previously ignored):

```javascript
function handleEvent(event) {
  renderEvent(event); // always log to event panel

  switch (event.type) {
    case 'AgentRegistered':
      addAgent(event.uuid, true, event.pid);
      updateGraph();
      break;
    case 'AgentDeregistered':
      killAgent(event.uuid);
      updateGraph();
      break;
    case 'MessageEnqueued':
      addMessage(event);
      break;
    case 'MessageDrained':
      break;
  }
}
```

**Step 6: Verify**

Run: `cd mesh-server && uv run pytest`
Expected: All 68 tests pass (no backend changes).

Open the UI in a browser and verify:
- Grid layout shows the split bottom (event log left, detail panel right)
- CSS variables produce the correct dark theme colors
- Event log renders events with icons and timestamps
- Auto-scroll works; scrolling up pauses auto-scroll and shows indicator
- Clicking the indicator resumes auto-scroll

**Step 7: Commit**

```bash
git add mesh-server/src/mesh_server/static/index.html
git commit -m "feat(ui): restructure layout with event log panel and updated design system"
```

---

### Task 2: Graph Visualization Polish

**Context:** The controller UI is a single HTML file at `mesh-server/src/mesh_server/static/index.html` with an embedded D3.js v7 force-directed graph. After Task 1, the file has an updated CSS grid layout with new CSS variables. The graph currently shows:
- Nodes: circles (blue for controller r=20, green for alive agents r=14, gray outline for dead)
- Edges: lines with arrow markers, `strokeWidth = Math.min(1 + count * 0.5, 4)`, pulse green on new message
- Node tooltip on hover showing UUID, PID, alive status

This task adds: logarithmic edge width with volume-based color interpolation, 30-second recency fade on edges and nodes, 3-state node visuals (active/idle/dead with pulse ring animation), and enhanced edge hover tooltips.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants:** No new invariants — this is visual enhancement only.

**Files:**
- Modify: `mesh-server/src/mesh_server/static/index.html` (CSS and JS sections)

**Depends on:** Task 1 (uses updated CSS variables)

**Step 1: Add CSS for pulse ring animation and recency**

Add these CSS rules after the existing `.link-line` styles:

```css
@keyframes pulse-ring {
  0% { r: 14; opacity: 0.6; }
  100% { r: 28; opacity: 0; }
}

.pulse-ring {
  fill: none;
  stroke: var(--status-green);
  stroke-width: 1.5;
  pointer-events: none;
}
```

**Step 2: Track lastActivityTime on nodes and links**

In the JavaScript state section, add tracking for recency:

```javascript
const FADE_DURATION = 30000; // 30 seconds
const ACTIVE_THRESHOLD = 5000; // 5 seconds for "active" state
```

When creating nodes in `addAgent()`, add `lastActivityTime: Date.now()` to the node object.

When creating links in `addMessage()`, add `lastActivityTime: Date.now()` to the link object. Also update existing link's `lastActivityTime` when a new message arrives on that link.

When a message arrives, update both the link's and the source/target nodes' `lastActivityTime`:

```javascript
// In addMessage(), after link.count++ and link.lastDir:
link.lastActivityTime = Date.now();
const fromNode = agentMap.get(fromId);
const toNode = agentMap.get(toId);
if (fromNode) fromNode.lastActivityTime = Date.now();
if (toNode) toNode.lastActivityTime = Date.now();
```

**Step 3: Update edge rendering for logarithmic width and volume color**

In `updateGraph()`, replace the existing edge stroke-width and add color interpolation:

```javascript
// Create a color interpolator for edge volume
const edgeColorScale = d3.interpolateRgb('#666666', '#00d4ff');

// In the linkSel.merge(linkEnter) chain:
linkSel.merge(linkEnter)
  .attr('stroke-width', d => Math.min(1 + Math.log2(d.count + 1) * 1.5, 6))
  .attr('stroke', d => {
    // Normalize count: use max count across all links
    const maxCount = Math.max(1, ...links.map(l => l.count));
    return edgeColorScale(d.count / maxCount);
  })
  .attr('marker-end', 'url(#arrow)');
```

Also update the arrow marker fill in the defs to use `currentColor` or `#666` (the base edge color).

**Step 4: Add recency fade timer**

Add a recurring animation loop that updates opacity based on `lastActivityTime`:

```javascript
function updateRecency() {
  const now = Date.now();

  // Fade edges
  linkGroup.selectAll('.link-line')
    .attr('opacity', d => {
      if (!d.lastActivityTime) return 0.3;
      return Math.max(0.3, 1.0 - (now - d.lastActivityTime) / FADE_DURATION);
    });

  // Fade and update node state
  nodeGroup.selectAll('.node-group')
    .each(function(d) {
      if (d.isController) return; // controller always full opacity
      if (!d.alive) return; // dead nodes handled separately

      const elapsed = d.lastActivityTime ? now - d.lastActivityTime : Infinity;
      const opacity = Math.max(0.3, 1.0 - elapsed / FADE_DURATION);
      d3.select(this).attr('opacity', opacity);

      // Active vs idle state
      const isActive = elapsed < ACTIVE_THRESHOLD;
      const pulseRing = d3.select(this).select('.pulse-ring');

      if (isActive && pulseRing.empty()) {
        // Add pulse ring
        d3.select(this).insert('circle', 'text')
          .attr('class', 'pulse-ring')
          .attr('r', 14);
        // Restart animation
        const el = d3.select(this).select('.pulse-ring').node();
        if (el) {
          el.style.animation = 'pulse-ring 2s ease-out infinite';
        }
      } else if (!isActive && !pulseRing.empty()) {
        pulseRing.remove();
      }
    });

  requestAnimationFrame(updateRecency);
}

// Start the recency loop
requestAnimationFrame(updateRecency);
```

Note: The pulse-ring CSS animation needs SVG `<animate>` instead of CSS `@keyframes` since SVG circle `r` attribute isn't animatable with CSS in all browsers. Use SVG `<animate>` element instead:

```javascript
if (isActive && pulseRing.empty()) {
  const ring = d3.select(this).insert('circle', 'text')
    .attr('class', 'pulse-ring')
    .attr('r', 14)
    .attr('cx', 0)
    .attr('cy', 0);
  ring.append('animate')
    .attr('attributeName', 'r')
    .attr('from', '14')
    .attr('to', '28')
    .attr('dur', '2s')
    .attr('repeatCount', 'indefinite');
  ring.append('animate')
    .attr('attributeName', 'opacity')
    .attr('from', '0.6')
    .attr('to', '0')
    .attr('dur', '2s')
    .attr('repeatCount', 'indefinite');
}
```

**Step 5: Update node visuals for 3 states**

In `updateGraph()`, update the `merged.select('circle')` chain to use the new status colors and handle the 3 states:

```javascript
merged.select('circle')
  .attr('fill', d => {
    if (d.isController) return 'var(--accent)';
    if (!d.alive) return 'none';
    return 'var(--status-green)';
  })
  .attr('stroke', d => {
    if (!d.isController && !d.alive) return 'var(--status-gray)';
    return 'none';
  })
  .attr('stroke-width', d => (!d.isController && !d.alive) ? 1.5 : 0)
  .attr('filter', d => {
    if (!d.alive || d.isController) return 'none';
    const elapsed = d.lastActivityTime ? Date.now() - d.lastActivityTime : Infinity;
    return elapsed < ACTIVE_THRESHOLD ? 'none' : 'url(#glow)';
  });
```

Active nodes get the pulse ring (from Step 4) instead of the glow filter. Idle nodes keep the glow. Dead nodes get neither.

**Step 6: Enhance edge hover tooltips**

Update the existing node `mouseenter` handler to also work for edges. Add mouseenter/mouseleave handlers to links in `updateGraph()`:

```javascript
// In linkEnter creation:
linkEnter
  .on('mouseenter', (e, d) => {
    const fromLabel = shortId(typeof d.source === 'object' ? d.source.id : d.source);
    const toLabel = shortId(typeof d.target === 'object' ? d.target.id : d.target);
    const lastMsg = d.messages.length > 0 ? d.messages[d.messages.length - 1] : null;
    const lastPreview = lastMsg ? (lastMsg.message || lastMsg.command || '').substring(0, 40) : '';
    const lines = [`${fromLabel} \u2194 ${toLabel}`, `${d.count} message${d.count !== 1 ? 's' : ''}`];
    if (lastPreview) lines.push(`Last: "${lastPreview}${(lastMsg.message || '').length > 40 ? '...' : ''}"`);
    tooltip.textContent = lines.join('\n');
    tooltip.style.display = 'block';
  })
  .on('mousemove', (e) => {
    tooltip.style.left = (e.pageX + 12) + 'px';
    tooltip.style.top = (e.pageY - 10) + 'px';
  })
  .on('mouseleave', () => {
    tooltip.style.display = 'none';
  });
```

**Step 7: Verify**

Run: `cd mesh-server && uv run pytest`
Expected: All 68 tests pass.

Open UI in browser and verify:
- Edges show logarithmic width scaling and color gradient from gray to cyan
- Edges fade to 30% opacity over 30 seconds
- Nodes show pulse ring animation when active (within 5s of message)
- Nodes show glow when idle, gray outline when dead
- Edge hover shows tooltip with message count and last message preview

**Step 8: Commit**

```bash
git add mesh-server/src/mesh_server/static/index.html
git commit -m "feat(ui): add graph polish — recency fade, volume edges, 3-state nodes, tooltips"
```

---

### Task 3: Node Detail Panel + Controller Inbox

**Context:** The controller UI is a single HTML file at `mesh-server/src/mesh_server/static/index.html`. After Tasks 1-2, the file has:
- A split bottom layout: event log (left) and detail panel (right)
- The detail panel currently shows messages filtered by selected node or edge (using `renderMessages()`, `selectNode()`, `selectLink()`, `clearSelection()`)
- The existing `#detail-panel` div has class `.panel-header` (title) and `.panel-body` (scrollable message list)
- All messages are stored in `allMessages[]` and links have a `.messages[]` array
- Nodes have `{id, uuid, label, alive, pid, isController, lastActivityTime}` properties
- The controller node has `id === '__controller__'` and `isController === true`

This task replaces the simple message list with a multi-mode detail panel: node detail (UUID/PID/uptime/messages/shutdown), edge messages, controller inbox with badge, and an empty state. It adds a shutdown button calling `POST /api/agents/{uuid}/shutdown` and inbox fetching from `GET /api/inbox`.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants from spec:**
- INV-25: POST /api/agents/{uuid}/shutdown deregisters agent → shutdown button must call this endpoint
- INV-26: GET /api/inbox returns controller's messages → inbox panel fetches from this endpoint

**Files:**
- Modify: `mesh-server/src/mesh_server/static/index.html` (CSS, HTML, and JS sections)

**Depends on:** Task 1 (layout structure), Task 2 (node state properties)

**Step 1: Add detail panel CSS**

Add CSS for the node detail view, inbox badge, and shutdown button:

```css
.node-detail {
  padding: 8px 12px;
}

.node-detail .node-field {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 0;
  font-variant-numeric: tabular-nums;
}

.node-detail .node-field .field-label {
  color: var(--text-secondary);
  display: inline-block;
  min-width: 60px;
}

.node-detail .node-field .field-value {
  color: var(--text-primary);
}

.node-detail .node-messages-header {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.btn-shutdown {
  margin-top: 8px;
  background: transparent;
  border: 1px solid var(--status-red);
  color: var(--status-red);
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 3px;
  cursor: pointer;
  width: auto;
}

.btn-shutdown:hover {
  background: rgba(248, 113, 113, 0.1);
}

.btn-shutdown:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.inbox-badge {
  fill: var(--status-red);
  font-size: 9px;
  font-family: var(--font-ui);
  font-weight: 700;
  pointer-events: none;
}

.inbox-badge-bg {
  fill: var(--status-red);
  pointer-events: none;
}

.detail-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.detail-tab {
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  background: none;
  border-top: none;
  border-left: none;
  border-right: none;
  width: auto;
}

.detail-tab:hover { color: var(--text-secondary); }
.detail-tab.active {
  color: var(--text-secondary);
  border-bottom-color: var(--accent);
}
```

**Step 2: Update detail panel HTML**

Replace the existing `#detail-panel` content with a tab-based structure:

```html
<div id="detail-panel">
  <div class="detail-tabs" role="tablist" aria-label="Detail panel">
    <button class="detail-tab active" role="tab" aria-selected="true" id="tab-detail" aria-controls="tabpanel-detail">Detail</button>
    <button class="detail-tab" role="tab" aria-selected="false" id="tab-inbox" aria-controls="tabpanel-inbox">Inbox</button>
  </div>
  <div class="panel-body" id="detail-body" role="tabpanel" aria-labelledby="tab-detail">
    <div class="detail-empty">Click a node or edge to inspect</div>
  </div>
</div>
```

**Step 3: Add inbox state tracking**

Add to JavaScript state:

```javascript
let inboxMessages = [];
let unreadCount = 0;
let activeTab = 'detail'; // 'detail' or 'inbox'
let uptimeInterval = null;
```

**Step 4: Implement node detail rendering**

Replace `selectNode()` to show full node detail instead of just filtered messages:

```javascript
function selectNode(d) {
  selectedNode = d;
  selectedLink = null;
  activeTab = 'detail';
  updateTabState();

  const body = document.getElementById('detail-body');

  if (d.isController) {
    // Controller node click → show inbox
    showInbox();
    return;
  }

  const state = getNodeState(d);
  const uptime = d.registeredAt ? formatUptime(Date.now() / 1000 - d.registeredAt) : 'unknown';

  // Node info section
  let html = '<div class="node-detail">';
  html += `<div class="node-field"><span class="field-label">UUID</span> <span class="field-value">${escapeHtml(d.uuid)}</span></div>`;
  html += `<div class="node-field"><span class="field-label">PID</span> <span class="field-value">${d.pid || 'unknown'}</span></div>`;
  html += `<div class="node-field"><span class="field-label">State</span> <span class="field-value">${state}</span></div>`;
  html += `<div class="node-field" id="uptime-field"><span class="field-label">Uptime</span> <span class="field-value">${uptime}</span></div>`;

  // Shutdown button
  html += `<button class="btn-shutdown" ${!d.alive ? 'disabled' : ''} aria-label="Shutdown agent ${shortId(d.id)}" onclick="confirmShutdown('${d.uuid}')">Shutdown Agent</button>`;

  html += '</div>';

  // Messages sub-transcript
  const msgs = allMessages.filter(m =>
    nodeIdFor(m.from_uuid) === d.id || nodeIdFor(m.to_uuid) === d.id
  ).sort((a, b) => a.timestamp - b.timestamp);

  html += `<div class="node-detail"><div class="node-messages-header">Messages (${msgs.length})</div></div>`;
  html += renderMessageList(msgs);

  body.innerHTML = html;

  // Live-updating uptime
  if (uptimeInterval) clearInterval(uptimeInterval);
  if (d.alive && d.registeredAt) {
    uptimeInterval = setInterval(() => {
      const el = document.getElementById('uptime-field');
      if (el) {
        const val = el.querySelector('.field-value');
        if (val) val.textContent = formatUptime(Date.now() / 1000 - d.registeredAt);
      }
    }, 1000);
  }
}
```

Add helper functions:

```javascript
function getNodeState(d) {
  if (!d.alive) return 'Dead';
  const elapsed = d.lastActivityTime ? Date.now() - d.lastActivityTime : Infinity;
  return elapsed < ACTIVE_THRESHOLD ? 'Active' : 'Idle';
}

function formatUptime(seconds) {
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${rem}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function renderMessageList(msgs) {
  if (msgs.length === 0) return '<div class="detail-empty">No messages</div>';
  return msgs.map(m => {
    const fromId = shortId(nodeIdFor(m.from_uuid));
    const toId = shortId(nodeIdFor(m.to_uuid));
    const isCtrl = isControllerUuid(m.from_uuid) || isControllerUuid(m.to_uuid);
    const text = m.message || m.command || '';
    return `<div class="msg-row${isCtrl ? ' controller-msg' : ''}">
      <span class="msg-dir">\u2192</span>
      <span class="msg-ids">${fromId} \u2192 ${toId}</span>
      <span class="msg-time">${formatTime(m.timestamp)}</span>
      <span class="msg-text">${escapeHtml(text)}</span>
    </div>`;
  }).join('');
}
```

The `.msg-text` CSS should be updated to `word-wrap: break-word; white-space: normal;` instead of the current `white-space: nowrap; overflow: hidden; text-overflow: ellipsis;` — messages should auto-wrap per the design.

**Step 5: Track registration time**

In `addAgent()`, record registration time so uptime can be computed:

```javascript
// When creating a new node in addAgent():
const node = {
  id: nid,
  uuid: uuid,
  label: shortId(nid),
  alive: alive,
  pid: pid,
  isController: nid === CONTROLLER_ID,
  lastActivityTime: Date.now(),
  registeredAt: Date.now() / 1000 // epoch seconds for consistency with server timestamps
};
```

**Step 6: Implement shutdown**

Add shutdown function (must be on `window` since it's called from onclick in innerHTML):

```javascript
window.confirmShutdown = async function(uuid) {
  const short = shortId(nodeIdFor(uuid));
  if (!confirm(`Shut down agent ${short} (${uuid})?`)) return;

  try {
    const res = await fetch(`/api/agents/${uuid}/shutdown`, { method: 'POST' });
    if (!res.ok) console.error('Shutdown failed:', res.status);
  } catch (err) {
    console.error('Shutdown failed:', err);
  }
};
```

**Step 7: Implement edge detail**

Update `selectLink()` to use the new message list renderer:

```javascript
function selectLink(d) {
  selectedLink = d;
  selectedNode = null;
  activeTab = 'detail';
  updateTabState();
  if (uptimeInterval) { clearInterval(uptimeInterval); uptimeInterval = null; }

  const sid = typeof d.source === 'object' ? d.source.id : d.source;
  const tid = typeof d.target === 'object' ? d.target.id : d.target;
  const a = shortId(sid);
  const b = shortId(tid);

  const msgs = allMessages.filter(m => {
    const f = nodeIdFor(m.from_uuid);
    const t = nodeIdFor(m.to_uuid);
    return (f === sid && t === tid) || (f === tid && t === sid);
  }).sort((a, b) => a.timestamp - b.timestamp);

  const body = document.getElementById('detail-body');
  body.innerHTML = `<div class="node-detail"><div class="node-messages-header">${a} \u2194 ${b} (${msgs.length} messages)</div></div>` + renderMessageList(msgs);
}
```

**Step 8: Implement controller inbox**

```javascript
async function showInbox() {
  activeTab = 'inbox';
  updateTabState();
  selectedNode = agentMap.get(CONTROLLER_ID);
  selectedLink = null;
  if (uptimeInterval) { clearInterval(uptimeInterval); uptimeInterval = null; }

  const body = document.getElementById('detail-body');
  body.innerHTML = '<div class="detail-empty">Loading inbox...</div>';

  try {
    const res = await fetch('/api/inbox');
    const json = await res.json();
    inboxMessages = json.data?.messages || [];
    unreadCount = 0;
    updateInboxBadge();

    if (inboxMessages.length === 0) {
      body.innerHTML = '<div class="detail-empty">No messages in inbox</div>';
      return;
    }

    // Show newest first
    const sorted = [...inboxMessages].sort((a, b) => b.timestamp - a.timestamp);
    body.innerHTML = renderMessageList(sorted);
  } catch (err) {
    body.innerHTML = '<div class="detail-empty">Failed to load inbox</div>';
    console.error('Inbox fetch failed:', err);
  }
}
```

**Step 9: Implement inbox badge on controller node**

Track unread messages and render a badge on the controller node:

```javascript
// In handleEvent(), for MessageEnqueued where to_uuid is controller:
case 'MessageEnqueued':
  addMessage(event);
  if (isControllerUuid(event.to_uuid) && activeTab !== 'inbox') {
    unreadCount++;
    updateInboxBadge();
  }
  break;
```

```javascript
function updateInboxBadge() {
  // Remove existing badge
  nodeGroup.selectAll('.inbox-badge-group').remove();

  if (unreadCount <= 0) return;

  const ctrlGroup = nodeGroup.selectAll('.node-group')
    .filter(d => d.isController);

  if (ctrlGroup.empty()) return;

  const badgeG = ctrlGroup.append('g').attr('class', 'inbox-badge-group');
  badgeG.append('circle')
    .attr('class', 'inbox-badge-bg')
    .attr('cx', 14)
    .attr('cy', -14)
    .attr('r', 8);
  badgeG.append('text')
    .attr('class', 'inbox-badge')
    .attr('x', 14)
    .attr('y', -11)
    .attr('text-anchor', 'middle')
    .text(unreadCount > 9 ? '9+' : unreadCount);
}
```

**Step 10: Implement tab switching**

```javascript
function updateTabState() {
  document.getElementById('tab-detail').classList.toggle('active', activeTab === 'detail');
  document.getElementById('tab-detail').setAttribute('aria-selected', activeTab === 'detail');
  document.getElementById('tab-inbox').classList.toggle('active', activeTab === 'inbox');
  document.getElementById('tab-inbox').setAttribute('aria-selected', activeTab === 'inbox');
}

document.getElementById('tab-detail').addEventListener('click', () => {
  activeTab = 'detail';
  updateTabState();
  if (selectedNode) selectNode(selectedNode);
  else if (selectedLink) selectLink(selectedLink);
  else clearSelection();
});

document.getElementById('tab-inbox').addEventListener('click', () => {
  showInbox();
});
```

**Step 11: Update clearSelection**

```javascript
function clearSelection() {
  selectedNode = null;
  selectedLink = null;
  if (uptimeInterval) { clearInterval(uptimeInterval); uptimeInterval = null; }
  activeTab = 'detail';
  updateTabState();
  document.getElementById('detail-body').innerHTML =
    '<div class="detail-empty">Click a node or edge to inspect</div>';
}
```

**Step 12: Update renderMessages calls**

The old `renderMessages()` function is replaced by `selectNode()` and `selectLink()`. The call in `addMessage()` at the end (`if (selectedNode || selectedLink) renderMessages();`) should be updated to re-render the current selection:

```javascript
// In addMessage(), replace the renderMessages() call:
if (selectedNode) selectNode(selectedNode);
else if (selectedLink) selectLink(selectedLink);
```

The old `renderMessages()` function can be removed.

**Step 13: Verify**

Run: `cd mesh-server && uv run pytest`
Expected: All 68 tests pass.

Open UI and verify:
- Clicking a node shows full detail (UUID, PID, state, uptime, messages, shutdown button)
- Uptime updates live every second
- Shutdown button triggers confirm dialog, then calls API
- Clicking an edge shows filtered messages
- Inbox tab shows messages addressed to controller
- Badge appears on controller node when unread messages exist
- Badge clears when inbox is opened
- Tab switching between Detail and Inbox works

**Step 14: Commit**

```bash
git add mesh-server/src/mesh_server/static/index.html
git commit -m "feat(ui): add node detail panel, controller inbox with badge, and shutdown button"
```

---

### Task 4: WCAG Accessibility + Documentation Updates

**Context:** The controller UI is a single HTML file at `mesh-server/src/mesh_server/static/index.html`. After Tasks 1-3, the file has the full feature set: event log, graph polish, node detail panel, and controller inbox. This task adds WCAG AA accessibility features and updates the project documentation.

The documentation updates are specified in the design doc at `docs/plans/2026-03-16-controller-ui-v03-design.md` under the "Documentation Updates" section.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants:** No new invariants — accessibility and documentation.

**Files:**
- Modify: `mesh-server/src/mesh_server/static/index.html` (CSS and HTML)
- Modify: `docs/ARCHITECTURE.md` (line 18: bump controller-ui version; add new section after REST/SSE API section ending around line 139)
- Modify: `docs/DESIGN.md` (lines 276-282: replace Controller Interface section)

**Depends on:** Task 1, Task 2, Task 3

**Step 1: Add skip link**

At the very start of `<body>`, before `<div id="app">`, add:

```html
<a href="#event-log-body" class="skip-link" tabindex="0">Skip to event log</a>
```

Add CSS:

```css
.skip-link {
  position: absolute;
  top: -40px;
  left: 0;
  background: var(--accent);
  color: var(--bg-primary);
  padding: 8px 16px;
  z-index: 1000;
  font-size: 13px;
  text-decoration: none;
  border-radius: 0 0 4px 0;
}

.skip-link:focus {
  top: 0;
}
```

**Step 2: Add focus-visible outlines**

Add global `:focus-visible` styling:

```css
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

**Step 3: Add aria-labels to existing buttons**

Update the HTML:
- Spawn button: `<button id="btn-spawn" aria-label="Spawn new agent">spawn</button>`
- Send button: `<button id="btn-send" aria-label="Send message to selected agent">send</button>`

**Step 4: Add ARIA live region for connection status**

Update the SSE status span:
```html
<span id="sse-status" class="status disconnected" role="status" aria-live="polite">disconnected</span>
```

**Step 5: Audit and fix contrast ratios**

Check all CSS variables against `--bg-primary` (#1a1a2e):
- `--text-primary` (#e0e0e0): 9.5:1 ✓ (AA passes)
- `--text-secondary` (#a0a0b0): 5.2:1 ✓ (AA passes)
- `--text-muted` (#707080): 3.6:1 — only use for decorative/non-essential text

Verify that no readable text uses `--text-muted`. The event log timestamps use `--text-muted` which is acceptable as supplementary information alongside the more prominent event text. Section titles using `--text-muted` should be changed to `--text-secondary` for WCAG compliance since they are functional labels.

Update CSS:
```css
.section-title {
  color: var(--text-secondary); /* was --text-muted */
}
```

**Step 6: Ensure tabindex on panels**

Add `tabindex="0"` to the event log body and detail panel body so they can receive keyboard focus for scrolling:

```html
<div class="panel-body" id="event-log-body" role="log" aria-live="polite" aria-label="Event log" tabindex="0"></div>
```

The detail panel body should also have `tabindex="0"`.

**Step 7: Verify accessibility**

Run: `cd mesh-server && uv run pytest`
Expected: All 68 tests pass.

Manual checks:
- Tab through the page: skip link → header → sidebar controls → event log → detail panel tabs → detail panel body
- Skip link appears on focus and jumps to event log
- All buttons and inputs have visible focus rings
- Screen reader announces connection status changes
- Event log announces new events via aria-live
- All visible text has sufficient contrast

**Step 8: Commit UI changes**

```bash
git add mesh-server/src/mesh_server/static/index.html
git commit -m "feat(ui): add WCAG AA accessibility — skip link, focus outlines, ARIA, contrast"
```

**Step 9: Update docs/ARCHITECTURE.md**

In `docs/ARCHITECTURE.md`, update the subsystem map table (line 18) — change `v0.2` to `v0.3`:

```markdown
| [controller-ui](../mesh-server/src/mesh_server/static/) | Web UI for human controller | v0.3 | — |
```

Add a new section after the "REST/SSE API" section (after line 139, before "Hook Architecture"):

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

**Step 10: Update docs/DESIGN.md**

In `docs/DESIGN.md`, replace the Controller Interface section (lines 276-295 — from `### Controller Interface` through the REST API table):

Replace the text at lines 276-282 with:

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

Keep the REST API table (lines 283-295) unchanged.

**Step 11: Commit documentation**

```bash
git add docs/ARCHITECTURE.md docs/DESIGN.md
git commit -m "docs: update ARCHITECTURE.md and DESIGN.md for controller UI v0.3"
```

**Step 12: Final verification**

Run: `cd mesh-server && uv run pytest`
Expected: All 68 tests pass.

Verify all acceptance criteria:
- [ ] Bottom area splits into event log (left) and detail panel (right)
- [ ] Event log shows all 4 event types with icon + color dual-coding
- [ ] Event log auto-scrolls with pause indicator
- [ ] Graph edges use logarithmic width and volume-based color
- [ ] Edges and nodes fade over 30 seconds
- [ ] 3-state node visuals (active/idle/dead)
- [ ] Edge hover tooltips
- [ ] Node detail panel with shutdown button
- [ ] Edge detail shows filtered messages
- [ ] Controller inbox badge and panel
- [ ] WCAG AA accessibility features
- [ ] Documentation updated
