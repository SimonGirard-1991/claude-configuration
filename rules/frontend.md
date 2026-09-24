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

React 19 / Next.js 15 App Router / TypeScript strict, on shadcn/ui + Tailwind, TanStack
Query, Tremor, React Hook Form + Zod. The bar is one you would defend in a design review
at a top-tier fintech: justify with concrete trade-offs and real failure modes, and weigh
2–3 alternatives before recommending. Adjust *explanation depth* to the reader, never the
bar on the code — and state the why behind non-obvious choices rather than assuming
pushback will catch a bad suggestion.

`.ts`/`.js` are in scope above because this machine's TypeScript is frontend; Java is the
backend. Ignore this file for Node service code and for non-React frontends (Angular,
React Native).

## Non-functional priorities

1. **Accessibility.** Non-negotiable. A component failing WCAG 2.1 AA is broken, not
   "almost done".
2. **Correctness** — money, dates, anything the user reads as authoritative. Wrong numbers
   destroy trust instantly in a financial product.
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
  selected row belong in the URL (`useSearchParams` + `router.push`, or `nuqs`). Critical
  in a financial app: users share URLs, bookmark views, reload, open new tabs. `useState`
  for these silently breaks all of it.
- **Data fetching mixed with presentation.** Container (Server Component or hook-driven
  wrapper) owns data; presentational component takes typed props.
- **Lax TypeScript.** No `any`, no `as unknown as Foo` laundering, no `!` to silence the
  compiler — if you cannot prove non-null, handle null. Discriminated unions over
  boolean-plus-optional state machines.
- **Cargo-cult `useMemo`/`useCallback`.** They cost bookkeeping and GC pressure. Justified
  when the computation is genuinely expensive, or the value feeds a memoized child or a
  dependency array that would otherwise churn. Before stripping them, verify via Context7
  whether React Compiler is stable in this React version *and* enabled here — do not
  assume memoization is free.
- **Forms without Zod.** One schema is the source of truth for client `react-hook-form`
  validation and the Server Action. Hand-rolled `if (!email.includes('@'))` is banned.
- **Missing loading / error / empty states.** Every async surface needs all three. "It'll
  load fast" is not a design. Skeletons beat spinners for perceived performance.
- **Accessibility treated as optional.** See the checklist below; it is correctness.
- **Unstable keys and needless re-renders.** `key={index}` on a reorderable list is a bug.
  Inline object/array literals in props, and context providers holding frequently-changing
  values, re-render subtrees. Profile with React DevTools before optimizing.
- **Money — representation, arithmetic, formatting.**
  - *Representation*: never `number` (`0.1 + 0.2 !== 0.3`). String, a decimal library
    (`decimal.js`, `big.js`), or minor units as `bigint`. Parse at the edges with Zod.
  - *Arithmetic*: never on floats. Decimal library or minor-unit integers end to end;
    format only at the very last moment.
  - *Formatting*: always `Intl.NumberFormat(locale, { style: 'currency', currency })`.
    Never `'$' + amount.toFixed(2)` — wrong for every locale but one, no thousands
    separators, and wrong for currencies with other decimal places (JPY 0, KWD 3).
- **Native `Date` for anything non-trivial.** Timezone-leaky, mutable, no date-only type.
  Use `date-fns` (or Temporal once stable); ISO 8601 on the wire. Know the difference
  between an instant, a civil date and a zoned datetime — get it wrong and you show the
  wrong trade date.

## Accessibility checklist (WCAG 2.1 AA)

Semantic HTML first, ARIA only when semantics fall short. Every interactive element
keyboard-reachable with a visible focus ring (never `outline: none` without a
replacement). Labels associated with inputs (`<label htmlFor>` or wrapping). Errors
announced via `aria-describedby` / `aria-invalid`. Dialogs: focus trap, focus restoration
on close, `Escape` to dismiss, `aria-modal`, labelled. Route changes announced. Colour
contrast — financial red/green gain/loss on dark backgrounds is the common failure.
`prefers-reduced-motion` respected. Images carry `alt` (empty `alt=""` when decorative,
never missing). Icon-only buttons have accessible names.

## Architecture to challenge

- **Component granularity.** Too big → untestable and re-renders too much; too small →
  prop-drilling and over-abstraction. Right size: one responsibility, one state-shape
  concern, fits on a screen. Split when a component holds two unrelated pieces of state or
  two unrelated effects.
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

Before writing markup for a new component, page, screen or visual prototype, invoke the
`frontend-design:frontend-design` skill — it avoids the generic AI aesthetic. Treat its
output as a starting point, then apply this file's bar on top (a11y, money/date
correctness, server/client boundary, state placement). Skip it for review, small targeted
changes to existing components, data-layer/hooks/types work, and one-line changes. If it
is unavailable, say so explicitly rather than silently falling back.

## Order of work

Designing: understand the user story and data shape → decide the server/client split
*first*, it shapes everything → decide what is URL state vs server cache vs local state,
three stores with three purposes → sketch the tree, container vs presentational → 2–3
approaches with trade-offs.

Coding: small iterations that typecheck → Zod schema and types first, they anchor the rest
→ server side before client interactivity → empty/loading/error states written *first* →
accessibility in the first pass, never a cleanup task.

## Testing

Component: Vitest (preferred) or Jest, plus React Testing Library — exercise user-visible
behaviour (roles, labels, text), never implementation details (class names, internal
state). E2E: Playwright, for cross-page journeys and real-browser integration, not as a
substitute for fast unit tests. Accessibility: axe-core / jest-axe / `@axe-core/playwright`
wired into component and E2E tests, so a11y regressions fail the build rather than review.

Lint/format: Biome vs ESLint + Prettier is a live trade-off — Biome for new projects
wanting speed and one binary, ESLint + Prettier when you need plugins it does not yet
cover (`eslint-plugin-jsx-a11y`, `eslint-plugin-testing-library`, `eslint-config-next`).
Verify current Biome coverage via Context7 before choosing; the gap closes fast.

## Library facts come from Context7

Frontend churns faster than training data. Any question about a specific library or
version-specific API — React, Next.js, TanStack Query, Zod, React Hook Form, Radix,
shadcn/ui, Tremor — goes to Context7 first, *especially* when you are tempted to answer
from memory. Use web search for CVEs, migration guides, post-mortems and cross-library
comparisons, where independent sources add value.

## Verification after non-trivial changes
1. Typecheck, lint, and run the targeted tests.
2. Spawn `code-reviewer` with: what changed and why, the calibration tier
   (throwaway / internal tool / production service / critical financial system), the scope
   (paths or git range), the note that this is a **frontend diff** so it applies its
   frontend lens, and the line `Invocation: self-review loop, iteration N of 3`.
   Address 🔴 and 🟡; judge 🔵 on merit; cap at 3 iterations, then escalate with what is
   outstanding.
Relay any **Proposed memory** note verbatim; record it only on user approval.
