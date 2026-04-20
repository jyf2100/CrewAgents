# Hermes Admin Panel — Neon Cyberpunk Frontend Redesign

> **Status:** Approved with review corrections incorporated

## Goal

Redesign the Hermes Agent Admin Panel from generic white-background Tailwind UI to a Neon Cyberpunk dark theme, while maintaining all existing functionality, i18n, and API integration.

## Design Direction

**Visual identity:** Neon Cyberpunk — dark purple backgrounds, neon pink + cyan accents. But applied with restraint: cyberpunk as flavor, not the entire meal. Data-dense components (tables, forms, logs) use clean, high-contrast dark UI patterns without glow effects. Neon effects are reserved for brand areas (sidebar header, login) and status indicators.

**Tech stack (unchanged):** React 19 + Tailwind CSS v4 + Vite 7 + TypeScript. No UI component library. All custom components.

---

## Design Tokens

### Colors

| Token | Value | Usage | WCAG contrast on bg |
|-------|-------|-------|---------------------|
| `--color-background` | `#0d0221` | Page background | — |
| `--color-surface` | `#1a0a3e` | Cards, panels | — |
| `--color-surface-elevated` | `#2d1b69` | Floating cards, modals | — |
| `--color-border` | `rgba(123,45,142,0.3)` | Borders (subtle purple) | — |
| `--color-accent-pink` | `#ff2a6d` | Primary accent (buttons, highlights, destructive) | 5.5:1 on bg |
| `--color-accent-cyan` | `#05d9e8` | Secondary accent (links, info, focus rings) | 8.5:1 on bg |
| `--color-accent-glow` | `#7b2d8e` | Box-shadow glow color | — |
| `--color-text-primary` | `#d1f7ff` | Primary text | 13:1 on bg |
| `--color-text-secondary` | `#a8a8c0` | Secondary text (CORRECTED from #8b8baa for 5:1+ contrast on surface) | 5:1 on surface |
| `--color-success` | `#00ff41` | Running/success | 7.8:1 on surface |
| `--color-warning` | `#f5a623` | Warning | — |
| `--color-destructive` | `#ff2a6d` | Error/delete (same as accent-pink) | — |

### Typography

| Role | Font | Weight | Min size | Notes |
|------|------|--------|----------|-------|
| Brand | Orbitron | 700 | 20px | Only for "HERMES" brand in sidebar, login title |
| Section titles | Exo 2 | 600 | 16px | All page/section headings |
| Body / UI | Exo 2 | 400 | 14px | Minimum 14px for readability (no text-xs with Exo 2) |
| Code / logs | JetBrains Mono | 400 | 13px | Lazy-loaded, only in log viewer and config editors |

**Orbitron letter-spacing:** `0.15em` (max). Not 0.3em — the font already has wide built-in spacing.

**Font loading:** Subset all three families. Preload Orbitron + Exo 2 in `<link>`. Lazy-load JetBrains Mono — inject `<link>` only when LogViewer or config editor mounts.

### Background Layers

```css
/* Applied to body or layout wrapper */
background-color: #0d0221;
background-image:
  radial-gradient(ellipse at 20% 50%, rgba(123,45,142,0.15), transparent 70%),
  radial-gradient(ellipse at 80% 20%, rgba(5,217,232,0.08), transparent 50%),
  radial-gradient(ellipse at 50% 80%, rgba(255,42,109,0.06), transparent 60%);
```

### Motion Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--duration-fast` | 150ms | Hover, focus |
| `--duration-normal` | 300ms | Page transitions, modal |
| `--duration-stagger` | 80ms | List stagger delay |
| `--ease-out-expo` | `cubic-bezier(0.16, 1, 0.3, 1)` | All animations |

---

## Layout: Sidebar + Topbar

```
┌──────────────────────────────────────────────────┐
│  [Logo] HERMES            [Lang] [Logout]        │  ← Topbar h-14, glass effect
├─────────┬────────────────────────────────────────┤
│ ◉ 面板  │                                        │
│ ◉ 设置  │         Main content area              │  ← Multi-layer gradient bg
│         │         (max-w-7xl, centered)           │
│ ────── │                                        │
│ Cluster │                                        │
│ ● 3/4   │                                        │
│ CPU 45% │                                        │
└─────────┴────────────────────────────────────────┘
     ↑ Sidebar w-56, bg #120838, left 1px pink border
```

### Sidebar

- Background: `#120838`
- Left edge: 1px `rgba(255,42,109,0.3)` vertical line
- Navigation items: text-secondary, hover → left 3px pink bar + text-primary
- Active item: left 3px pink bar + text-primary + subtle pink text-shadow (large text only)
- Bottom section: Mini cluster status card (CPU/memory micro-bars, agent count)
- **Mobile (< 768px):** Hidden by default, hamburger icon in topbar opens as slide-in drawer. Overlay backdrop `bg-black/50`.

### Topbar

- Background: `rgba(26,10,62,0.8)` + `backdrop-blur(12px)`
- Left: Hexagon SVG logo (static, no animation) + "HERMES" in Orbitron 700
- Right: Language toggle (pill button with cyan border), Logout (ghost button)
- Border-bottom: 1px `rgba(123,45,142,0.2)`

### Content Area

- Multi-layer radial gradient background (defined above)
- Content wrapper: `max-w-7xl mx-auto p-6`
- Page enter animation: `opacity 0→1, translateY(12px→0)` 400ms ease-out-expo

---

## Pages

### Dashboard

**Stats row (new):** Three compact stat cards — Running (cyan left border), Stopped (gray), Failed (pink left border). Numbers in Exo 2 text-3xl weight 600. Stagger reveal: each card delayed 80ms.

**Agent card grid:** 1 col (mobile) / 2 col (md) / 3 col (lg).

**Agent card design:**
- Background: `var(--color-surface)` + `border: 1px solid rgba(123,45,142,0.2)`
- Status: Small colored circle (not hexagon — circles are instantly readable). Running = cyan with subtle glow. Stopped = gray. Failed = pink.
- Card name: Exo 2 weight 600, text-primary
- Kebab menu: Replaced with outlined gear icon, cyan on hover
- CPU/Memory bars: `bg: rgba(123,45,142,0.2)` track, gradient fill with accent color. Bar end has subtle box-shadow glow. Values in JetBrains Mono.
- Footer: Age in text-secondary, "View" link in cyan
- Running cards: left edge 3px cyan bar
- Hover: `translateY(-1px)` + border → `rgba(5,217,232,0.3)` + subtle shadow

**80/20 color rule:** On each card, one accent dominates. Status and progress bars = cyan. Action buttons and delete = pink. Never both at equal visual weight.

**New Agent card:** Dashed border `rgba(123,45,142,0.4)`, center `+` icon in cyan. Hover: border solidifies + cyan glow.

**Auto-refresh:** 10s interval, data updates via opacity transitions on values only. No DOM rebuild flicker.

### Agent Detail

**Header bar:** Glass effect, back arrow in cyan, agent name in Exo 2 weight 600, status dot + label. Action buttons: Restart (secondary/cyan), Stop (ghost with warning color), Delete (danger/pink). Meta info (IP, node, age) in text-secondary + JetBrains Mono.

**Tab navigation:**
- Active tab: 3px pink bottom border. NO text-shadow glow on tabs (readability > style).
- Inactive: text-secondary, hover → text-primary
- Tab switch: content fade-in 200ms
- Mobile (< 768px): horizontal scroll with overflow-x-auto

**Overview tab:**
- Status cards grid (2x3): `bg-surface` + top 1px cyan line. Clean, no glow.
- Resource gauges: SVG circle arcs (NOT conic-gradient — better cross-browser, easier to animate). CPU arc = cyan gradient, Memory arc = pink gradient. Center text: "1.2 / 4 cores" in JetBrains Mono.

**Config tab:**
- Input fields: `bg-background` + `border: 1px solid rgba(123,45,142,0.3)`. Focus: cyan border + subtle cyan ring. Error state: pink border + pink error text. Disabled: `opacity: 0.5, cursor-not-allowed`. Placeholder: text-secondary.
- YAML/SOUL.md editors: `bg-background`, JetBrains Mono, line numbers in text-secondary. Save button = primary (pink fill).

**Logs tab:**
- Full dark terminal: `#080815` background
- Toolbar: Filter input (cyan focus), Pause/Resume toggle, Clear button
- Log lines: ERROR = `#ff2a6d` text + left 2px pink bar. WARN = `#f5a623` + amber bar. DEBUG = text-secondary. INFO = text-primary.
- Timestamps: JetBrains Mono, text-secondary
- New lines: fade-in at bottom
- Custom scrollbar: track `#1a0a3e`, thumb `rgba(5,217,232,0.3)`

**Events tab:**
- Table styling: `bg-surface` header row, `bg-background` body rows. Borders: `rgba(123,45,142,0.15)`. Hover row: `rgba(5,217,232,0.05)`. Type badges: Normal=cyan, Warning=amber, Error=pink. Minimal, no glow.

**Health tab:**
- Status cards: Clean surface cards with top accent line. Gateway JSON in code block. Refresh button = secondary.

### Create Agent

**Step indicator:** Horizontal line segments. Completed = cyan fill. Current = pulsing (subtle opacity animation, not glow). Future = gray `rgba(123,45,142,0.3)`. Step numbers in Orbitron, max letter-spacing 0.15em.

**Forms:** Same input styling as Config tab. LLM test connection button = standard loading spinner (NOT scan line animation — removed for usability).

**Deploy progress:** 5 sub-steps vertical list. Completed: cyan checkmark. Current: pulsing dot. Future: gray dot. Success state: cyan checkmark scales in (`scale(0)→1`, 300ms).

### Settings

**Collapsible sections:** Each section has header bar with `bg-surface` + left 3px cyan accent + chevron icon. Expanded: content slides down 200ms. Collapsed: content hidden.

**Cluster status table:** Same table styling as Events tab.

**Input fields:** Same as Config tab styling.

### Login

**Background:** Static multi-layer radial gradients (NO rotating animation — user spends 5 seconds here, continuous animation wastes GPU).

**Brand area:** "HERMES" in Orbitron 700, letter-spacing 0.15em, `text-shadow: 0 0 30px rgba(255,42,109,0.4)` (justified for large brand text). Subtitle "Control Center" in Exo 2 weight 300, text-secondary.

**Decorative elements:** Static hexagonal shapes via CSS clip-path. NO rotation animation.

**Card:** `backdrop-blur(20px)` + `bg-surface/40` + border `rgba(123,45,142,0.2)`.

**Input:** `bg-background` + cyan focus ring + lock icon inside.

**Login button:** Primary (pink fill) + hover box-shadow glow (justified for single CTA).

**Error:** Pink text + static red highlight (NO shake animation — vestibular disorder risk).

---

## Component System

### Buttons (4 variants)

| Variant | Style | Use case |
|---------|-------|----------|
| `primary` | `bg-accent-pink` + `text-primary` + hover glow | Deploy, Save, Login |
| `secondary` | `border-accent-cyan` + `text-accent-cyan` + hover fill | Restart, Edit, Test |
| `ghost` | transparent + `text-secondary` + hover `bg-surface` | Cancel, Back, Logout |
| `danger` | `border-accent-pink` + `text-accent-pink` + hover pink fill | Delete, Stop |

Common: `font-family: Exo 2`, `font-weight: 500`, `letter-spacing: 0.02em`, `transition: all 200ms`, `rounded-lg`.

Disabled state for all: `opacity: 0.5, cursor-not-allowed, no hover effects`.

### Cards

- Default: `bg-surface` + `border: 1px solid rgba(123,45,142,0.2)` + `rounded-lg`
- Hover: `translateY(-1px)` + `border-color: rgba(5,217,232,0.3)` + `box-shadow: 0 4px 20px rgba(123,45,142,0.15)`
- With status: `border-left: 3px solid var(--status-color)`

### ConfirmDialog

- Backdrop: `bg-black/60` + `backdrop-blur(4px)`
- Dialog: `bg-surface-elevated` + subtle border glow
- Destructive variant: top 2px pink line + danger confirm button
- Enter animation: `scale(0.95→1)` + `opacity(0→1)`, 200ms. Respects prefers-reduced-motion.

### LoadingSpinner

- Cyan spinning ring + outer faint pink pulse
- Sizes: sm (16px), md (24px), lg (40px)
- Respects prefers-reduced-motion (static dot instead)

### Toast

- **MUST migrate from imperative DOM to React Portal.**
- Success: left 3px green bar + `bg-surface` + green text
- Error: left 3px pink bar + `bg-surface` + pink text
- Enter: `translateX(100%→0)` 300ms. Exit: `translateX(0→100%)` + fade. Respects prefers-reduced-motion.
- Position: top-right, aligned with sidebar

### Tables

- Header: `bg-surface` + `text-secondary` + uppercase + `tracking-wider` + Exo 2 weight 600
- Body rows: `bg-background`
- Row borders: `border-b rgba(123,45,142,0.15)`
- Hover: `bg-surface/50` (subtle, no glow)
- Type/status badges: Small pills with accent colors

### Tabs / Segmented Control (UNIFIED)

Single reusable component used everywhere:
- AgentDetailPage (5 tabs): underline style (pink bottom border)
- Config tab (3 sub-tabs): underline style
- Settings templates (4 sub-tabs): underline style
- All use the same component with consistent styling

### Empty States

- Centered layout, icon in cyan + text-secondary message + ghost action button
- No decorative animations

### Dropdown / Popover (for kebab menus)

- `bg-surface-elevated` + `border: 1px solid rgba(123,45,142,0.3)` + `shadow-lg`
- Items: hover `bg-surface` + cyan text
- Destructive items: pink text
- Enter: fade-in 150ms

---

## Animation System

### Keyframes

```css
/* Page enter */
@keyframes page-enter {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* List stagger */
@keyframes stagger-item {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Status pulse (running indicator) */
@keyframes status-pulse {
  0%, 100% { opacity: 0.6; }
  50%      { opacity: 1; }
}

/* Toast slide */
@keyframes toast-in {
  from { transform: translateX(100%); opacity: 0; }
  to   { transform: translateX(0); opacity: 1; }
}

/* Modal enter */
@keyframes modal-enter {
  from { transform: scale(0.95); opacity: 0; }
  to   { transform: scale(1); opacity: 1; }
}

/* Checkmark pop */
@keyframes check-pop {
  from { transform: scale(0); }
  to   { transform: scale(1); }
}
```

### prefers-reduced-motion

ALL animations must respect this media query:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### Stagger limits

- Max 12 items with stagger delay. Items 13+ appear instantly.
- Running status pulse: only the FIRST running agent pulses. Others show static glow.

---

## Files Modified

| File | Change Level | Notes |
|------|-------------|-------|
| `index.css` | **Full rewrite** | All design tokens, keyframes, Tailwind @theme |
| `index.html` | **Minor** | Add Google Fonts preconnect + preload links |
| `AdminLayout.tsx` | **Full rewrite** | Sidebar + topbar + mobile drawer |
| `AgentCard.tsx` | **Full rewrite** | Cyberpunk card styling |
| `ClusterStatusBar.tsx` | **Full rewrite** | Mini sidebar version |
| `ConfirmDialog.tsx` | **Style rewrite** | Dark modal styling |
| `LoadingSpinner.tsx` | **Style rewrite** | Cyan spinner |
| `ErrorDisplay.tsx` | **Style rewrite** | Dark error display |
| `LoginPage.tsx` | **Full rewrite** | Atmospheric login |
| `DashboardPage.tsx` | **Full rewrite** | Stats row + stagger grid |
| `AgentDetailPage.tsx` | **Style + structure** | Tabs, SVG gauges, dark terminal logs |
| `CreateAgentPage.tsx` | **Style rewrite** | Step indicator, form styling |
| `SettingsPage.tsx` | **Style rewrite** | Collapsible sections |
| `toast.ts` | **Full rewrite** | React Portal, slide animation |
| `utils.ts` | **Update** | Color mappings for new palette |
| New: `src/components/Tabs.tsx` | **New** | Unified tab component |
| New: `src/components/GaugeChart.tsx` | **New** | SVG arc gauge for resource display |

**NOT modified:** `admin-api.ts`, `i18n/*`, `hooks/*`, `App.tsx` (routes unchanged), `main.tsx`.

---

## Scope Exclusions

- No new features or API endpoints
- No i18n key changes
- No backend changes
- No routing changes
- Theme toggle (classic dark / cyberpunk) is NOT in scope — single theme only
