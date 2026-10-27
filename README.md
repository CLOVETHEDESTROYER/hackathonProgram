# EmberReady

Private, homeowner-confirmed wildfire preparedness assessments for the Santa Fe pilot. React/TypeScript on the Sites Vinext starter; Sites ChatGPT identity; D1 records; R2 private images; Leaflet aerial map.

## Run locally

Use Node 24 (minimum 22.13). Install locked dependencies with `npm ci`, then `npm run db:generate` only when changing the schema. Build with `npm run build`. Apply each pending SQL migration to local D1 using the starter's README commands and `dist/server/wrangler.json`; the initial migration is `drizzle/0000_striped_terrax.sql`. Run `npm run dev` and open the printed loopback URL. The starter simulates ChatGPT sign-in **only for local development**. Hosted identity is platform-owned.

`npm test` tests scoring, material guidance, metadata stripping, transactional spend reservations, duplicate inputs, and monthly quotas. `npm run typecheck` checks TypeScript. `npm run test:integration` targets the disposable local preview at 127.0.0.1:5173, refuses non-test property data, and tests local authentication, revisions, uploads, quotas, source deletion, and history. A foreign-owner fixture is needed to verify denial against an existing record; use the QA setup described in `tests/integration.mjs` and never seed production.

## Runtime configuration

Configure `OPENAI_API_KEY` securely through the OpenAI Developers plugin and Sites runtime secrets, never browser code, Git, or chat. This key is not configured in the initial deployment. Without it, uploads, maps, checklist, reports, and saved progress work; analysis clearly reports setup pending and produces no invented results.

Optional runtime values: `OPENAI_MODEL` (default `gpt-5.6-terra`), `AI_MONTHLY_BUDGET_USD` (10), `AI_INPUT_USD_PER_M` (10), `AI_OUTPUT_USD_PER_M` (40). Conservative accounting rates must not be lower than the deployed model's current token prices. Validate model access and actual usage before enabling a larger pilot. Each request reserves $1 transactionally before dispatch; charges reconcile against measured token usage and configured rates. Failed or timed-out requests retain the reservation because provider charges may have occurred. Application reservations are a request-budget guard, not a guarantee of provider billing. Configure provider project controls too. Maximum three attempted analyses/property/UTC calendar month, twelve photos/assessment, no automatic paid retry, and successful unchanged-input caching.

## Assessment behavior

Ten equally weighted checklist controls. Unknowns earn no points; confirmed non-applicable controls require a reason and leave the denominator. Display completeness separately. All non-applicable gives no numeric score. AI findings and task completion cannot award points. New assessment versions start unassessed rather than inheriting safety claims.

AI gets normalized home pin/outline context instead of the postal address. Sources include up to 12 resized homeowner photos plus property and neighborhood aerials. Vision only proposes observations; curated rules determine guidance. Confidence is qualitative and uncalibrated. The app does not establish compliance, wood treatment, exact clearances, live fire risk, or survival probability. API response storage is disabled; OpenAI abuse-monitoring retention may still apply.

USGS/USDA NAIP is aerial imagery, not a live satellite feed. Image catalog capture dates and item resolutions are retained; mosaic source dates can vary. Dates are not inferred from the service's advertised pixel size. The live public request at the Santa Fe city center returned May 2022 imagery at 0.6 meters. Ground photos and homeowner confirmation establish current conditions. No Google Maps or Zillow images are analyzed.

Community context is from the verified Santa Fe city and Santa Fe County records in the April 15, 2026 Wildfire Risk to Communities download. `lib/community-data.json` retains the source, sheet, row, geographic identifier, and extracted fields. Both are explicitly reference geographies; neither classifies the selected parcel.

## Privacy and operations

Every private API lookup is owner-scoped, including source images. Files remain in R2 behind authenticated routes. Uploads are re-encoded to JPEG in the browser and JPEG metadata is stripped independently server-side. A revision check prevents silent concurrent overwrites. Cross-origin changes are denied. Deletion removes R2 files and associated assessment records. Minimal AI accounting records remain to enforce quotas; they contain no street address or image bytes. Stuck runs expire to failed after five minutes while retaining their reservation. Errors omit keys, photos, and full addresses.

New Sites remain owner-private. Adding volunteers is a separate access change, not part of deployment. Before expansion: configure live AI, validate findings against labeled consenting homeowner photos, measure actual costs/latency, and test on physical iPhone Safari and Android Chrome. Browser viewport checks do not establish physical camera/device compatibility.
