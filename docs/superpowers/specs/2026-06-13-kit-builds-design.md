# Kit Builds — Design Spec

**Date**: 2026-06-13  
**Status**: approved

## Context

Guitar kit builds (DIY guitars assembled from a body kit, neck, hardware, pickups, and finish
materials) need proper tracking in Odoo. Today, build plans live as unstructured HTML/Markdown
in `x_gear.x_studio_notes` and `x_listing.x_studio_notes`, making them unsearchable and
impossible to aggregate.

The goal is to model the full kit lifecycle — from a vague idea through parts sourcing, active
build, and completion — while staying consistent with the existing `x_models → x_listing → x_gear`
pattern.

## Design

### Principle

A kit build follows the same pattern as a marketplace listing:

```
x_models  →  x_listing  →  x_gear                         (marketplace path)
x_models  →  x_listing  ←  x_kit_part  →  x_kit  →  x_gear  (kit build path)
```

Parts are first-class catalog entries in `x_models` (type=`parts`). Individual supplier offers
are `x_listing` rows (platform = supplier slug). `x_kit_part` joins a listing to a kit (adding
quantity and status). When done, the kit links to the `x_gear` record of the finished guitar.

---

### Extensions to existing models

#### `x_models.x_studio_model_type`

Add selection value: **`parts`**

A parts model represents a specific part — e.g. "Gotoh SD91 Vintage Tuners" or
"Sprague Orange Drop 0.022µF Capacitor". Brand (`x_studio_partner_id`) is the manufacturer
(Gotoh, Graph Tech, CTS, …).

#### `x_listing.x_platform`

Add supplier slugs as new selection values:

| slug | Supplier |
|---|---|
| `amazon` | Amazon.ca |
| `solomusicgear` | Solo Music Gear |
| `pegcitypickups` | Pegcity Pickups |
| `precisionguitarkits` | Precision Guitar Kits |
| `oxfordguitarsupply` | Oxford Guitar Supply |
| `nextgenguitars` | Next Gen Guitars |
| `graphtech` | Graph Tech |

Additional suppliers are added as needed. A parts listing links to a parts model and captures
the URL, price, currency, and notes for a specific supplier's offer. The same part can have
multiple listings (one per supplier), enabling informal price comparison.

---

### New models

#### `x_kit` — Build project

| Field | Type | Notes |
|---|---|---|
| `x_name` | char | e.g. "TV Yellow Korina Explorer" |
| `x_status` | selection | `idea`, `planning`, `sourcing`, `building`, `done` |
| `x_studio_notes` | html | Vision, spec decisions, build log |
| `x_gear_id` | many2one → `x_gear` | Set when status reaches `done` |
| `x_kit_part_ids` | one2many → `x_kit_part` | Parts list |

**Status lifecycle:**

```
idea → planning → sourcing → building → done
```

- **idea**: rough concept, no parts committed
- **planning**: parts identified, shopping list being built
- **sourcing**: parts being ordered
- **building**: all parts received, active assembly
- **done**: guitar complete; `x_gear_id` is set

#### `x_kit_part` — Part line item

| Field | Type | Notes |
|---|---|---|
| `x_kit_id` | many2one → `x_kit` | Parent build |
| `x_listing_id` | many2one → `x_listing` | The part offer (supplier + price + URL) |
| `x_quantity` | integer | Default 1 |
| `x_studio_status` | selection | `wanted`, `ordered`, `received` |

**Part status lifecycle:**

```
wanted → ordered → received
```

Parts group naturally by supplier via `x_listing.x_platform`, matching the vendor-grouped
shopping lists currently kept in notes (see gear #13 as the reference build).

---

### Field naming conventions

Follows project CLAUDE.md rules:

- Many2one: `x_<model>_id` → `x_gear_id`, `x_kit_id`, `x_listing_id`
- One2many: `x_<model>_ids` → `x_kit_part_ids`
- Boolean flags: `x_is_*` / `x_has_*` — none needed here
- Selection with lifecycle semantics: plain `x_status` or `x_studio_status`

---

### Pydantic models (models.py)

Two new classes follow the `OdooRecord` base pattern:

**`KitRecord`** — fields: `x_name`, `x_status`, `x_studio_notes`, `x_gear_id` (OdooM2O),
`x_kit_part_ids` (OdooIds)

**`KitPartRecord`** — fields: `x_kit_id` (OdooM2O), `x_listing_id` (OdooM2O), `x_quantity`
(OdooInt), `x_studio_status` (OdooStr)

---

### Schema drift test

`tests/test_models.py` must be extended to include `KitRecord` and `KitPartRecord` in the
live-field verification, as is done for all other OdooRecord subclasses.

---

## Out of scope

- Build step checklist (free-form tasks within a build) — captured in `x_studio_notes` for now
- Cost roll-up (total kit cost computed from part prices × quantities) — deferred; doable in Studio with a computed field later
- MCP tools for kits — deferred until the schema is stable in Odoo

## Reference build

Gear #13 (TV Yellow Xplo P90) is the canonical example. Its parts map cleanly onto this schema:
- Kit body → x_listing (platform=`precisionguitarkits`, model_type=`parts`)
- Tuners, bridge, pots, switch, jack → x_listing rows (platform=`solomusicgear`)
- Pickups → x_listing (platform=`pegcitypickups`)
- Finish kit, grain filler → x_listing rows (platform=`oxfordguitarsupply`)
- Wire → x_listing (platform=`amazon`)
