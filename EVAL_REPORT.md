# Golden Seed Live Evaluation — Run 1

**When**: 2026-06-04 · **Cost**: $1.7711 in real Gemini calls · **Run-id**: golden-eval tenant `99999999-…-9999`

## Headline

| Pack | Observed | Target | Cost | Verdict |
|---|---:|---:|---:|---|
| business_documents_base | 75.0% | 90% | $0.0098 | FAIL |
| cloud_finance | 46.7% | 90% | $0.1157 | FAIL |
| healthcare_claims | 66.7% | 90% | $0.2570 | FAIL |
| legal_hr | 33.3% | 90% | $0.3560 | FAIL |
| manufacturing | 31.2% | 90% | $0.4593 | FAIL |
| telecom_billing | 64.3% | 90% | $0.5732 | FAIL |
| **Total** | **~52%** | 90% | **$1.7711** | 0 of 6 pass |

**Pre-mortem**: this number sounds catastrophic. It is not. ~60% of the misses are not extraction failures — the pipeline extracted the *value* but emitted it under a different *name*. Real extraction failures concentrate in legal_hr and Azure/GCP. Three separate issues, three separate fixes.

## Category A — Naming gap (~60% of misses, not a bug, fix goldens)

The pipeline's `_canonical_fields.normalize_extraction()` correctly collapses domain-specific names into canonicals. The goldens then assert the *pre*-canonical names — so they fail by construction. Examples observed across this run:

| Pack | Golden expected | Pipeline emitted | Same value? |
|---|---|---|---|
| telecom_billing | `carrier` | `vendor` | yes |
| telecom_billing | `invoice_number` | `document_number` | yes |
| cloud_finance | `provider` | `vendor` | yes |
| cloud_finance | `invoice_number` | `document_number` | yes |
| healthcare_claims | `claim_number` | `document_number` | yes |
| healthcare_claims | `total_charge` | `total` | yes |
| manufacturing | `buyer` / `supplier` | `customer` / `vendor` | yes |
| manufacturing | `po_number` | `document_number` | yes |
| legal_hr | `agreement_number` | `document_number` | yes (when extracted) |
| legal_hr | `effective_date` | `document_date` | yes |

**Recommended fix**: update each `golden.yaml` so `expected:` uses the canonical names that `_canonical_fields.ALIASES` produces. Cost to fix: ~30 min of YAML edits. Expected lift: telecom_billing → 100%, manufacturing → 70-90%, cloud_finance → 80%+.

## Category B — Missing aliases (real bug, fix `_canonical_fields.ALIASES`)

Two raw names the LLM emits in practice are NOT in the canonical map, so they leak through as raw:

| Raw emission | Should map to | Documents affected |
|---|---|---|
| `invoice_id` | `document_number` | AT&T invoice, AWS invoice |
| `total_amount_due` | `total` | Verizon invoice |

**Recommended fix**: 2-line PR to `src/mdi/brain/_canonical_fields.py` — add both lines to `ALIASES`. Expected lift: catches another 4-6 fields across telecom + cloud_finance.

There is also a quirk where `governing_law` appears twice in the actual extraction output (twice the same key). Worth a closer look — likely a list-of-strings field being serialised oddly.

## Category C — Genuinely not extracted (~30% of misses, prompt work)

These are fields the LLM never emitted under any name. They're real misses that need prompt or schema work:

| Pack | Field | Documents |
|---|---|---|
| cloud_finance | `account_number` | Azure, GCP (AWS had it correctly) |
| healthcare_claims | `provider_name` | claim_837 (extracted as something else, not a vendor alias) |
| healthcare_claims | `total_charge` | remit_835 |
| legal_hr | `expiration_date`, `total_contract_value`, `auto_renew`, `auto_renew_notice_days` | MSA |
| legal_hr | `confidentiality_term_years` | NDA |
| manufacturing | `actual_delivery_date` | BOL |
| business_documents_base | `document_number` | sample invoice |
| telecom_billing | `carrier` | CenturyLink CSR — no vendor field on a customer service record |

**Recommended fix**: pack-by-pack prompt tuning. Likely the legal_hr pack's prompts don't enumerate clause-level fields tightly enough; cloud_finance's prompts may not list `account_number` as an expected field for non-AWS providers. Expected work: 1-2 days of prompt iteration + re-eval.

## Side findings (worth a separate look)

- **Anthropic key in `.env` is invalid** — Claude returns `401 invalid x-api-key`. The provider-fallback live test fails for this reason, not a code bug. Refresh the key when convenient; Gemini-only operation is fine for now.
- **One narrator call hit `finish_reason: 2`** (Gemini safety filter) on `manufacturing/po_001.txt` and `telecom_billing/att_invoice_001.txt`. Pipeline degraded gracefully and continued. Worth understanding why — likely a Gemini safety category being triggered by random data that looks like contact info.
- **Manufacturing PO emits nested keys** (`supplier.name`, `supplier.address`) instead of flat. The Hands prompt or schema may need to force flat shape.

## Suggested next actions, in order of ROI

1. **(5 min, free)** Add 2 aliases (`invoice_id`, `total_amount_due`) to `_canonical_fields.ALIASES` — Category B fix.
2. **(30 min, free)** Rewrite the 6 `golden.yaml` files to use canonical names — Category A fix. Re-running after these two should put 3-4 packs above 90%.
3. **(2-4 hours, ~$5 in reruns)** Iterate prompts for legal_hr's clause-level fields and cloud_finance's account_number — Category C fix. Re-eval until ≥90% across the board.
4. **(non-urgent)** Investigate Gemini `finish_reason: 2` cases and the `governing_law` double-emission.

Full per-case JSON in `eval_report.json`.
