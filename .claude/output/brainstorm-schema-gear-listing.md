# Brainstorm: Schema — gear vs listing data model

**Date**: 2026-04-04
**Challenge**: How might we model gear and marketplace data without forcing a record-per-record duplication when the relationship is almost always 1-to-1?

## Context
- 4000+ gear entries tracked (market watching)
- ~20 actually acquired/owned
- Main use case: market surveillance, not inventory management
- x_guitar → x_gear + x_listing split produced nearly 1:1 records, defeating the purpose
- Database will be wiped clean — no migration from current x_gear/x_listing needed

## Root Cause
The original schema created x_gear **eagerly** (on every sync). It should be created **lazily** (only on acquisition). The two models were always semantically correct — the trigger was wrong.

## Final Approach: Listing-first, gear-on-acquisition

### Guiding principle
- `x_listing` = "I saw this on the market" (inbound from sync, or outbound when selling)
- `x_gear` = "I own this physical object" (created only on acquisition)

### Schema

```
x_listing
  x_model_id        → x_models
  x_url
  x_platform        → reverb | marketplace | kijiji | other
  x_price           → final price (sale price when sold, purchase price when acquired)
  x_condition
  x_status          → watching | acquired | passed | closed | for_sale | sold
  x_gear_id         → x_gear (null while watching, set on acquisition or when selling)
  x_published_at

x_gear
  x_model_id        → x_models
  x_intent          → flip | keeper | unknown
  x_condition       → condition at time of purchase
  x_acquisition_price
  x_status          → owned | sold
  x_serial_number
  x_neck_dimensions
  [other physical specs]
  x_listing_ids     → O2M back to x_listing
```

### Status lifecycle

**Buy side** (inbound — from Reverb sync):
`watching` → `acquired` | `passed` | `closed`

**Sell side** (outbound — created manually per platform):
`for_sale` → `sold` | `closed`

### Flows

**Watching (sync)**
- Reverb sync creates/updates x_listing records only
- x_gear is never created here

**Acquiring**
- Mark x_listing as `acquired`
- Create x_gear with physical details (serial, neck dims, specs)
- Link x_listing.x_gear_id = x_gear.id

**Selling**
- Create one x_listing per platform (Reverb, Marketplace, Kijiji…)
- All linked to same x_gear from the start
- x_listing.x_status = `for_sale`

**Sold**
- Winning listing → `sold`, record final x_price
- Other platform listings → `closed`
- x_gear.x_status → `sold`

### Key queries

| Question | Filter |
|----------|--------|
| Where is this gear listed? | x_gear_id = X AND x_status = for_sale |
| What did I buy it for? | x_gear_id = X AND x_status = acquired |
| What did I sell it for? | x_gear_id = X AND x_status = sold |
| P&L on a flip | sold.x_price − acquired.x_price |

### Design decisions
- `x_price` = final price only (no asking price — what you wanted is irrelevant)
- No price history table (YAGNI — main use case is market surveillance, not analytics)
- `x_model_id` lives on both x_listing and x_gear for query convenience

## Recommended Next Steps
- Run `/quick-spec` to define all fields and the Odoo Studio setup plan
