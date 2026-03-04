# Odoo Field Audit — x_guitar & x_models

Generated: 2026-03-04

## Summary

| Model    | Total records | Empty fields to drop | Abandoned fields to drop | Duplicate fields to drop |
|----------|---------------|----------------------|--------------------------|--------------------------|
| x_guitar | 4,052         | 3                    | 9                        | 2                        |
| x_models | 314           | 3                    | 6                        | 0                        |

---

## x_guitar

### Safe to delete — 0 records with data

| Field                                  | Label                                         | Type      |
|----------------------------------------|-----------------------------------------------|-----------|
| `x_studio_boolean_field_8v3_1ifti9b9a` | "Nouveau Case à cocher" (auto-generated name) | boolean   |
| `x_studio_tax_rates`                   | Tax Rates                                     | many2many |
| `x_guitar_line_ids_65c70`              | "Nouvelles lignes" (auto-generated name)      | one2many  |

### Likely abandoned — very low fill rate (<1%)

| Field                                 | Fill    | Label              | Type      |
|---------------------------------------|---------|--------------------|-----------|
| `x_studio_custom_build_1`             | 13/4052 | Custom Build       | boolean   |
| `x_studio_custom_build_ht_1`          | 14/4052 | Custom Build HT    | monetary  |
| `x_studio_custom_build_price`         | 14/4052 | Custom Build Price | monetary  |
| `x_studio_custom_build_price_score_1` | 13/4052 | Custom Build Score | float     |
| `x_studio_is_a_good_candidate_1`      | 18/4052 | Candidate          | boolean   |
| `x_studio_my_cad_ht_1`                | 22/4052 | My CAD HT          | monetary  |
| `x_studio_target_price_taxes`         | 21/4052 | Target Taxes       | monetary  |
| `x_studio_parts`                      | 14/4052 | Parts              | many2many |
| `x_studio_needs_forwarding_1`         | 33/4052 | Forwarding         | boolean   |

### Duplicate one2many — same 37 records as `x_studio_expense_ids`

| Field                                   | Fill    | Label                                | Type     |
|-----------------------------------------|---------|--------------------------------------|----------|
| `x_studio_one2many_field_7pe_1ihen66n7` | 37/4052 | "expense_ids" (auto-named duplicate) | one2many |
| `x_studio_one2many_field_8ir_1igs22g9p` | 37/4052 | "New One2Many" (auto-named)          | one2many |

### GUITAR_FIELDS — read by sync code but never written, non-stored computeds

These can be removed from `GUITAR_FIELDS` in `odoo_connector.py` if the values are
not displayed or compared anywhere:

| Field                    | Fill                | Label      |
|--------------------------|---------------------|------------|
| `x_studio_best_price_ht` | non-stored computed | HT         |
| `x_studio_average`       | non-stored computed | Average    |
| `x_studio_my_cad_ttc`    | non-stored computed | My CAD TTC |

### Fields populated by Odoo but not used by sync code — keep

These appear to be computed/related fields maintained by Odoo Studio formulas or
displayed in views. Do not delete.

| Field                                    | Fill      | Notes                                |
|------------------------------------------|-----------|--------------------------------------|
| `x_studio_final_score`                   | 4049/4052 | computed score                       |
| `x_studio_model_familly_ids`             | 3894/4052 | related from x_models                |
| `x_studio_model_id_reverb_category_id`   | 4052/4052 | related from x_models                |
| `x_studio_model_sequence_score`          | 4052/4052 | related/computed                     |
| `x_studio_model_tax_rate_id`             | 4052/4052 | related from x_models                |
| `x_studio_models_score`                  | 1667/4052 | related/computed                     |
| `x_studio_score_1`                       | 4052/4052 | computed score (selection)           |
| `x_studio_selection_field_7tf_1igs0n52h` | 4052/4052 | status bar                           |
| `x_studio_sequence`                      | 4052/4052 | record ordering                      |
| `x_studio_summary_price_score`           | 4052/4052 | computed                             |
| `x_studio_weighted_final_score`          | 4049/4052 | computed                             |
| `x_studio_float_field_1r5_1ifr9edfj`     | 4051/4052 | Weight (investigate before deleting) |
| `x_studio_model`                         | 4043/4052 | old integer model ref (investigate)  |
| `x_studio_tax_rate`                      | 839/4052  | item tax rate (in use)               |
| `x_studio_expense_ids`                   | 37/4052   | expense tracking (in use)            |
| `x_studio_notes`                         | 192/4052  | user notes                           |
| `x_studio_best_price`                    | 4051/4052 | computed TTC price                   |
| `x_studio_score`                         | 4051/4052 | item score                           |
| `x_studio_target_price_ttc`              | 3790/4052 | target price TTC                     |

---

## x_models

### Safe to delete — 0 records with data

| Field                                | Label                                       | Type     |
|--------------------------------------|---------------------------------------------|----------|
| `x_studio_delete_me`                 | "delete_me" (explicitly named for deletion) | many2one |
| `x_studio_float_field_227_1jhf8ppva` | "New Decimal" (auto-generated name)         | float    |
| `x_studio_guitars`                   | Guitars                                     | many2one |

### Likely abandoned — very low fill rate (<12%)

| Field                                   | Fill   | Label                        | Type      |
|-----------------------------------------|--------|------------------------------|-----------|
| `x_studio_bridge`                       | 2/314  | Bridge                       | many2one  |
| `x_studio_ebay_1`                       | 1/314  | Ebay                         | char      |
| `x_studio_kijiji`                       | 4/314  | Kijiji                       | char      |
| `x_studio_facebook_1`                   | 5/314  | Facebook                     | char      |
| `x_studio_custom_part_ids`              | 10/314 | Custom Parts                 | many2many |
| `x_studio_many2many_field_44_1iheqo8t2` | 33/314 | "New Many2Many" (auto-named) | many2many |

### Fields used in codebase — keep

| Field                          | Used by        |
|--------------------------------|----------------|
| `x_name`                       | all commands   |
| `x_studio_brand`               | gpt-files      |
| `x_studio_model_type`          | gpt-files      |
| `x_studio_construction_ids`    | gpt-files      |
| `x_studio_guitar_neck_feel_id` | gpt-files      |
| `x_studio_scale`               | gpt-files      |
| `x_studio_finish`              | gpt-files      |
| `x_studio_fretboard_1`         | gpt-files      |
| `x_studio_web_page_1`          | gpt-files      |
| `x_studio_reverb_category_id`  | sync, validate |
| `x_studio_wanna`               | sync --wanna   |

### Fields with significant data, not in codebase — keep (used in Odoo views)

| Field                            | Fill    | Notes                     |
|----------------------------------|---------|---------------------------|
| `x_studio_coiling`               | 268/314 | pickup coiling type       |
| `x_studio_potted`                | 259/314 | pickups potted?           |
| `x_studio_guitar_familly_ids`    | 295/314 | guitar families           |
| `x_studio_brand_tax_rate`        | 306/314 | tax rate by brand         |
| `x_studio_score_1`               | 314/314 | sequence score            |
| `x_studio_sequence`              | 313/314 | record ordering           |
| `x_studio_tax_rate_id`           | 314/314 | tax rate                  |
| `x_studio_partner_id`            | 314/314 | brand (partner link)      |
| `x_studio_rating_1`              | 127/314 | model rating              |
| `x_studio_reverb_1`              | 187/314 | Reverb page URL           |
| `x_studio_image`                 | 266/314 | model image               |
| `x_studio_notes`                 | 162/314 | user notes                |
| `x_studio_magnet_id`             | 42/314  | pickup magnet type        |
| `x_studio_pickup_configurations` | 45/314  | pickup configs            |
| `x_studio_got`                   | 42/314  | owned? flag               |
| `x_studio_rarity`                | 44/314  | rarity score              |
| `x_studio_reverb_high_bracket`   | 66/314  | Reverb high price bracket |
| `x_studio_reverb_low_bracket_1`  | 66/314  | Reverb low price bracket  |

---

## Action plan

1. Delete from **x_guitar** via Odoo Studio Settings → Custom Models:
    - The 3 empty fields
    - The 9 abandoned fields (after confirming no Odoo views reference them)
    - The 2 duplicate one2many fields

2. Delete from **x_models** via Odoo Studio:
    - The 3 empty fields (start with `x_studio_delete_me`)
    - The 6 abandoned fields

3. Optionally remove from `GUITAR_FIELDS` in `odoo_connector.py`:
    - `x_studio_best_price_ht`, `x_studio_average`, `x_studio_my_cad_ttc`
      (non-stored computeds that can't be searched and are never written)
