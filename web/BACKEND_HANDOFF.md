# Stream A — Backend handoff notes

## Active routes (all return 200, no auth gate)

- `/start` — NL input, marketplace marquee
- `/search` (+ `?hunt=lebron|couch`) — hunt hub with async discovery feed
- `/compare` (+ `?hunt=...`) — best options grid (currently standing-desk only)
- `/approve` (+ `?hunt=...`) — approvals queue (currently standing-desk only)
- `/deal/[id]` — deal room (only `j-uplift` and `j-flexispot` exist)
- `/playbook` (+ `?hunt=...`) — case files

For `lebron` and `couch` hunts, downstream pages render a "Preview build" empty state until backend wires per-hunt data.

## Current mock-only data sources

| Page | Mock file | API endpoint waiting |
|---|---|---|
| `/search` (standing-desk) | `mocks/listings.json` + `mocks/discovery-stages.json` | `/api/goals/{goalId}/listings`, `/api/goals/{goalId}/discovery-stages` |
| `/search` (lebron/couch) | inline TS arrays in `app/(app)/search/page.tsx` | needs `goalId`-keyed endpoints |
| `/compare` | `mocks/listings.json` direct import | `/api/goals/{goalId}/listings` |
| `/approve` | `mocks/approvals.json` direct import | `/api/approvals?goalId=...` |
| `/deal/[id]` | `mocks/deal-rooms/j-*.json` | `/api/jobs/{id}` (route exists but is unused) |
| `/playbook` | `mocks/playbook.json` direct import | `/api/playbook` (route exists but is unused) |
| sidebar `OutboxBar` | `mocks/outbox.json` | `/api/outbox` (global across hunts) |
| topnav `ActivityBell` | inline NOTIFICATIONS array | needs notifications endpoint |

`lib/api.ts` wrappers exist for all of the above but are NOT called by any page. See note in `lib/api.ts`.

## Components backend should wire (in priority order)

1. **HuntSidebar** (`components/sidebar/hunt-sidebar.tsx`) — currently 3 hardcoded hunts. Needs `getHunts()` returning `Hunt[]` keyed by `huntId`.
2. **ActivityBell** (`components/topnav/activity-bell.tsx`) — 4 hardcoded notifications. Needs `getNotifications()` returning `Notification[]` with `targetHref` per item.
3. **DiscoveryFeed** (`components/search/discovery-feed.tsx`) — wall-clock setTimeout staged reveal. Needs SSE/WebSocket seam — drop a `stream` prop that subscribes to `EventSource("/api/goals/{goalId}/discovery/stream")`.
4. **ProductResultCard** (`components/compare/product-result-card.tsx`) — selection state is in-memory `useState`. Needs server-backed selection (or document as client-only).
5. **NextMovesPanel** (`components/nextmoves/next-moves-panel.tsx`) — items hardcoded per page. Needs `getNextMoves(goalId)`.
6. **ApprovalTicket** (`components/approve/approval-ticket.tsx`) — currently derives deal room id via `ticket.id.replace(/^ap-/, "j-")`. Add `listing_id`, `goal_id`, `conversation_id` to `ApprovalTicket` type so backend isn't relying on string-replace magic.
7. **DealRoom** (`components/deal/deal-room-layout.tsx` + children) — full shape consumed; backend mirrors `DealRoom` type as-is.
8. **PriceLadder** + **SavingsReceipt** — pure presentational, consume `PriceLadder` and `SavingsReceipt` types directly.
9. **Playbook / case files** — `Case` and `LearningNote` types consumed directly. Decide: per-hunt or global?

## Required IDs for backend contracts

Add these to `web/types.ts` before wiring:

- `huntId` (string) — primary key for a product hunt
- `listingId` (string) — already on `Listing.id`
- `sellerId` (string) — add to `Seller`
- `conversationId` (string) — add to `DealRoom`; currently keyed by URL `id` param
- `approvalId` (string) — already on `ApprovalTicket.id`; ADD `goal_id` and `listing_id` foreign keys
- `notificationId` (string) — needs new `Notification` type
- `targetHref: string` (or `targetRoute`) on every Notification AND NextMoveItem so the click target lives in the data

## Hard rule for the agent layer

**Every notification AND every NextMoveItem with an action MUST carry an explicit `targetHref` field.** The frontend must NEVER hardcode the target route — that pattern caused the LeBron/Couch leaks fixed in this patch.

## Contract divergence from SPEC.md to resolve

- `ApprovalCard` (SPEC) ↔ `ApprovalTicket` (types.ts)
- `IntegrationAccount` (SPEC) ↔ `MarketplaceChannel` (types.ts)
- `/api/memory/cases|skills` (SPEC) ↔ `/api/playbook` (types.ts)
- `provider ∈ {fb, nextdoor}` (SPEC) ↔ `{facebook, nextdoor, offerup, craigslist}` (types.ts)
- Clarifying-question flow in SPEC has zero frontend implementation
- `/api/listings/{id}/negotiate` in SPEC has zero frontend callers

**Recommendation**: `types.ts` is canonical. Update SPEC.md to match.
