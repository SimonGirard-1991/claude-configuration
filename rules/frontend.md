---
paths:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.ts"
  - "**/*.js"
  - "**/*.mjs"
  - "**/*.css"
  - "**/*.scss"
  - "**/next.config.*"
  - "**/tailwind.config.*"
  - "**/components.json"
---
# Frontend conventions

React / Next.js App Router on the repo's installed majors (APIs from Context7), TypeScript
strict, on shadcn/ui + Tailwind, TanStack Query, Tremor, React Hook Form + Zod. The bar is
a design review at a top-tier fintech: concrete trade-offs, real failure modes, 2–3
alternatives weighed before recommending. Adjust explanation depth to the reader, never
the bar on the code, and state the why behind non-obvious choices.

This covers `.ts`/`.js` too: TypeScript on this machine is frontend, Java the backend.
Ignore it for Node service code and non-React frontends (Angular, React Native).

## Non-functional priorities

1. **Accessibility.** Non-negotiable. A component failing WCAG 2.2 AA is broken, not
   "almost done".
2. **Correctness** — money, dates, anything the user reads as authoritative; one wrong
   number destroys trust in a financial product.
3. **Performance** — Core Web Vitals (LCP, INP, CLS) as targets, not aspirations. Measure
   with real-user monitoring, not only lab.
4. **Maintainability** — readable in two years by someone who did not write it.
5. **Observability** — client-side error tracking, performance tracing, user-facing errors
   that do not leak internals.

## Anti-patterns — fire on sight

Refuse these in code you write and refactor them in code you touch.

- **`useEffect` as a crutch.** Most are wrong. Derivable from state/props → compute it in
  render. Server data → TanStack Query hook or a Server Component, never
  `useEffect(fetch, [])`. Effects sync with *external* systems: the DOM, a subscription, a
  timer. That is the whole list.
- **Local state that should be URL state.** Filters, pagination, sort, tab, date range,
  selected row belong in the URL (`useSearchParams` + `router.push`, or `nuqs`). In
  `useState` they silently break sharing, bookmarks, reload and new tabs.
- **Data fetching mixed with presentation.** Container (Server Component or hook-driven
  wrapper) owns data; presentational component takes typed props.
- **Lax TypeScript.** No `any`, no `as unknown as Foo` laundering, no `!` to silence the
  compiler — if you cannot prove non-null, handle null. Discriminated unions over
  boolean-plus-optional state machines.
- **Cargo-cult `useMemo`/`useCallback`.** Justified for genuinely expensive work, or a
  value feeding a memoized child or a dependency array that would otherwise churn. Before
  stripping them, check React Compiler is enabled here; without it nothing memoizes for you.
- **Forms without Zod.** One schema is the source of truth for client `react-hook-form`
  validation and the Server Action. Hand-rolled `if (!email.includes('@'))` is banned.
- **Missing loading / error / empty states.** Every async surface needs all three. "It'll
  load fast" is not a design. Prefer skeletons to spinners.
- **Accessibility treated as optional.** The checklist below is correctness.
- **Unstable keys and needless re-renders.** `key={index}` on a reorderable list is a bug.
  Inline object/array literals in props, and context providers holding frequently-changing
  values, re-render subtrees. Profile with React DevTools before optimizing.
- **Money as `number`** (`0.1 + 0.2 !== 0.3`). Carry it as a string, a decimal library
  (`decimal.js`, `big.js`) or minor units as `bigint`, parsed at the edges with Zod; do
  arithmetic only in the decimal or `bigint`, end to end. Format at the last moment, always
  with `Intl.NumberFormat(locale, { style: 'currency', currency })`: `'$' + n.toFixed(2)`
  lacks thousands separators and is wrong for every locale but one and for currencies with
  other decimals (JPY 0, KWD 3).
- **Native `Date` for anything non-trivial.** Timezone-leaky, mutable, no date-only type.
  Use `date-fns` (or Temporal once stable); ISO 8601 on the wire. An instant, a civil date
  and a zoned datetime differ — confuse them and you show the wrong trade date.

## Accessibility checklist (WCAG 2.2 AA)

Semantic HTML first, ARIA only when semantics fall short. Every interactive element
keyboard-reachable with a visible focus ring (never `outline: none` without a
replacement), and never fully hidden under a sticky header, banner or toast when focused.
Labels associated with inputs (`<label htmlFor>` or wrapping). Radio and
checkbox groups: `<fieldset>` + `<legend>`, with `min-w-0` inside grid or flex parents (a
fieldset's `min-inline-size: min-content` overflows them); NVDA announces a fieldset's
description inconsistently, so repeat a short one on each input. Errors
announced via `aria-describedby` / `aria-invalid`. Dialogs: focus trap, focus restoration
on close, `Escape` to dismiss, `aria-modal`, labelled. Route changes announced. Colour
contrast — financial red/green gain/loss on dark backgrounds is the common failure.
`prefers-reduced-motion` respected. Images carry `alt` (empty `alt=""` when decorative,
never missing). Icon-only buttons have accessible names. Pointer targets at least 24×24
CSS px or spaced to match (inline links exempt). Custom drags (reorder, slider) also work
by click or tap; a keyboard path alone does not count. In one flow, data already given is
auto-filled or selectable, unless security needs it re-entered. Every auth step, OTP and
step-up included, accepts paste and password managers. Help repeated across pages keeps
its relative order.

## Architecture to challenge

- **Component granularity.** Too big → untestable, over-rendering; too small →
  prop-drilling. One responsibility, one state-shape concern, fits on a screen; split at
  two unrelated pieces of state or effects.
- **Server/client boundary.** Server Components by default. Push `"use client"` to the
  leaves that truly need interactivity; a client component can render server components
  passed as `children`. Never mark a layout `"use client"` without a real reason.
- **TanStack Query cache.** Keys stable, serializable, hierarchical
  (`['transactions', { accountId, filters }]`) so invalidation stays surgical. `staleTime`
  is freshness, `gcTime` is retention — pick `staleTime` per query by how stale the user
  can tolerate (balances short, reference data long). Prefetch on the server and hydrate
  to kill the client fetch waterfall. Invalidate on mutation, or `setQueryData` for
  optimistic updates with rollback on error.
- **Shared types.** One source of truth per domain concept. Zod for anything crossing a
  boundary (API, form, storage); `z.infer` for the TS type. Never duplicate an interface
  and a schema — derive one from the other.
- **Pages Router is legacy** — flag it on sight.

## Building UI

Before writing markup for a new component, page or visual prototype, invoke the
`frontend-design:frontend-design` skill, which avoids the generic AI aesthetic, then apply
this file's bar on top. Skip it for review, small changes to existing components,
data/hooks/types work and one-liners. If it is unavailable, say so rather than silently
falling back.

## Order of work

Designing: user story and data shape → server/client split *first* → URL state vs server
cache vs local state → the tree, container vs presentational.

Coding: small iterations that typecheck → Zod schemas and types first → server side before
client interactivity → empty/loading/error states *first* → accessibility in the first
pass, never a cleanup task.

## Testing

Component: Vitest (preferred) or Jest, plus React Testing Library — exercise user-visible
behaviour (roles, labels, text), never implementation details (class names, internal
state). E2E: Playwright for cross-page journeys in a real browser, never a substitute for
fast unit tests. Accessibility: axe-core / jest-axe / `@axe-core/playwright`
wired into component and E2E tests, so a11y regressions fail the build rather than review.

Lint/format: Biome for new projects; ESLint + Prettier when you need plugins Biome lacks
(`jsx-a11y`, `testing-library`, `eslint-config-next`). Check Biome's coverage via Context7.

## Library facts come from Context7

Library and version questions — React, Next.js, TanStack Query, Zod, React Hook Form,
Radix, shadcn/ui, Tremor — go to Context7 first, *especially* when memory feels sure:
frontend churns faster than training data. Web search is for CVEs, migration guides,
post-mortems and cross-library comparisons.

## Verification after non-trivial changes
1. Typecheck, lint, and run the targeted tests.
2. Run the self-review loop below, telling `code-reviewer` this is a **frontend diff** so
   it applies its frontend lens.

### Self-review loop

Spawn `code-reviewer` with: what changed and why, the calibration tier
(throwaway / internal tool / production service / critical financial system), the scope
(paths or git range), and the line `Invocation: self-review loop, iteration N of 3`.
Address 🔴 and 🟡; judge 🔵 on merit; cap at 3 iterations, then escalate to the user with
what is outstanding. A verdict covers only the diff it saw: every edit after a review goes
back through the reviewer within the cap, a 🔴 fix without exception; past the cap, hand
the fix to the user marked unreviewed. The loop adds no quality of its own: submit correct
code first, and mid-loop fix only the accepted findings, adding nothing new.

Relay any **Proposed memory** note verbatim; record it only on user approval.
