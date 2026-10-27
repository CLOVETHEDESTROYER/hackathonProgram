# EmberReady — Home Wildfire Preparedness
**One-Page Business Brief | Santa Fe, New Mexico**

## Business Concept
EmberReady is a mobile-friendly web app that helps homeowners understand and reduce wildfire vulnerabilities around their homes. It combines public aerial imagery, homeowner photographs, AI-assisted visual analysis, and a guided preparedness checklist to produce a private, evidence-based assessment and prioritized action plan.

**Value proposition:** Turn confusing wildfire-preparedness guidance into clear, actionable steps homeowners can take to protect their properties.

## Product & MVP
The initial release will serve Santa Fe homeowners, starting with the founder’s home and expanding through a small volunteer pilot.

- **Assess:** Locate and outline a home on USGS aerial imagery; guide homeowners through a photo walk covering roofs, vents, decks, vegetation, fences, and combustible materials.
- **Understand:** Use AI vision to propose potential hazards, with supporting images, confidence levels, and homeowner confirmation or correction.
- **Prioritize:** Generate a versioned, experimental checklist score and group recommended actions into “Address First,” “Plan Next,” and “Maintain.”
- **Track:** Save assessments and progress across devices; provide completion controls and printable reports.

The product will use curated NFPA/IBHS-based guidance. Unknown conditions remain unresolved rather than being treated as safe. Community wildfire-risk information will be displayed separately from property-level findings.

**MVP exclusions:** Public rankings, insurance certification, fire predictions, evacuation routing, and professional-review dashboards.

## Technology & Delivery
Build with Sites’ Vinext/React/TypeScript starter, ChatGPT sign-in, D1 database, R2 private image storage, Leaflet mapping, USGS NAIP imagery, and the OpenAI Responses API with structured outputs.

Four milestones: (1) Authentication, property location, and imagery; (2) Photo uploads and AI analysis; (3) Scoring, action plans, and reports; (4) Pilot validation and volunteer testing.

Privacy and reliability are core requirements: owner-level access controls, protected images, metadata stripping, deletion of stored data, server-side API keys, explicit AI-processing disclosures, and enforced usage limits.

## Profit Model
**Recommended model: Freemium-to-paid subscription**, with optional professional referrals introduced only after the assessment workflow is validated.

- **Free:** One property, basic assessment, prioritized checklist, and limited reassessments to drive adoption.
- **Homeowner Plus — test at $49/year:** Saved assessment history, seasonal reassessments, progress tracking, updated action plans, and printable reports.
- **Optional one-time assessment — test at $19:** A paid entry point for homeowners who prefer not to subscribe.
- **Future partnerships:** Qualified referrals to local defensible-space specialists, arborists, and other relevant contractors, with transparent disclosure of referral compensation.

**Illustrative unit economics:** At $49/year, assume $8 per subscriber annually for AI, storage, and infrastructure, plus $10 for payment processing, support, and other variable costs. Estimated contribution is **$31 per subscriber per year (63%)**, before development, marketing, taxes, and other fixed costs. These are planning assumptions to validate, not measured costs.

At 1,000 annual subscribers, that implies $49,000 revenue and approximately $31,000 contribution before fixed costs. Break-even subscriber count equals annual fixed costs divided by $31.

## Launch Strategy & Success Metrics
Begin with a founder-led assessment, manually validate findings, correct false alarms and missed hazards, and recruit Santa Fe homeowners for a volunteer pilot. Measure assessment completion, useful actions identified, improvements completed, repeat usage, AI accuracy, cost per assessment, and willingness to pay.

**Initial operating limits:** One property per pilot user, 12 photos per assessment, three full analysis runs per property monthly, cached unchanged results, and a configurable $10 monthly AI budget.

**First success milestone:** A homeowner completes an assessment, identifies a useful improvement, completes it, and verifies the change in a traceable reassessment.

**Business objective:** Validate safety usefulness, homeowner demand, and sustainable per-property economics before expanding geographically or investing in larger-scale customer acquisition.