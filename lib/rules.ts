export const RULE_VERSION = '2026.1';
const IBHS = 'https://wildfireprepared.org/wp-content/uploads/WFPH-Technical-Standard-12-25.pdf';
export const RULES = [
  { id:'roof_debris', title:'Roof clear of debris', check:'Confirm the roof is free of accumulated leaves, needles, and other vegetation. Check from the ground; do not climb onto a roof.', action:'Arrange safe removal of roof debris.', priority:'first', effort:'Small task or professional help', source:IBHS },
  { id:'roof_covering', title:'Documented roof covering', check:'Confirm a Class A roof assembly from manufacturer or installation records. Appearance alone cannot establish a fire rating.', action:'Find roof documentation or ask a qualified roofer to assess the assembly.', priority:'next', effort:'Records review / professional assessment', source:IBHS },
  { id:'gutters', title:'Gutters clear of debris', check:'Confirm gutters are free of leaves and needles. Note combustible gutter materials separately for professional review.', action:'Arrange safe gutter cleaning and review combustible gutters.', priority:'first', effort:'Small task or professional help', source:IBHS },
  { id:'vents', title:'Verified vent protection', check:'Verify wildfire-resistant vent specifications or qualifying metal mesh against current guidance. A photo cannot verify a test rating; special vent types may need professional review.', action:'Check vent specifications with a qualified installer.', priority:'next', effort:'Professional assessment', source:IBHS },
  { id:'immediate_zone', title:'First five feet reviewed', check:'Confirm a continuous noncombustible area within five feet of the home and attached structures, free of combustible groundcover, stored items, and vegetation.', action:'Remove or relocate combustibles from the first five feet; consider gravel, pavers, or bare mineral soil.', priority:'first', effort:'Small task to landscaping project', source:IBHS },
  { id:'under_deck', title:'Under-deck area clear', check:'Confirm no stored items, vegetation, or combustible groundcover beneath the deck. Deck enclosure requirements need a separate professional check. Mark not applicable only if there is no deck.', action:'Clear stored items and vegetation beneath the deck; review enclosure needs.', priority:'first', effort:'Small task / professional review', source:IBHS },
  { id:'fences', title:'Fence connection reviewed', check:'Confirm there are no combustible fence or gate components within five feet of the home. Confirm ownership before altering shared fences.', action:'Plan a noncombustible fence connection with the owner or qualified contractor.', priority:'next', effort:'Materials / contractor', source:IBHS },
  { id:'firewood', title:'Firewood stored away', check:'Confirm firewood and wood piles are at least 30 feet from the home. An accessory-structure exception needs verification against current guidance.', action:'Relocate firewood at least 30 feet from the home or seek review of a qualifying storage structure.', priority:'first', effort:'Small task', source:IBHS },
  { id:'vegetation', title:'Vegetation separation reviewed', check:'Confirm dead vegetation has been removed and horizontal and vertical separation has been reviewed using local guidance. Suitable spacing depends on slope and vegetation.', action:'Remove dead vegetation and ask local wildfire staff about appropriate spacing.', priority:'next', effort:'Yard work / professional advice', source:IBHS },
  { id:'branches', title:'Branch proximity reviewed', check:'Review branches overhanging the immediate zone and clearance around chimneys and stovepipes. Work near roofs, utilities, or large limbs needs a qualified professional.', action:'Arrange professional review of overhanging branches and chimney clearance.', priority:'next', effort:'Professional assessment', source:IBHS },
] as const;
export type RuleId = typeof RULES[number]['id'];
export type ControlStatus = 'unknown'|'met'|'needs_improvement'|'not_applicable';
export type Control = { status:ControlStatus; note:string; updatedAt?:string };
export type Controls = Record<RuleId,Control>;
export function emptyControls():Controls { return Object.fromEntries(RULES.map(r=>[r.id,{status:'unknown',note:''}])) as Controls; }
export function scoreControls(controls:Controls) {
  const entries=RULES.map(r=>controls[r.id]??{status:'unknown'});
  const applicable=entries.filter(c=>c.status!=='not_applicable');
  const met=applicable.filter(c=>c.status==='met').length;
  const reviewed=entries.filter(c=>c.status!=='unknown').length;
  return {score:applicable.length?Math.round(met/applicable.length*100):null, completeness:Math.round(reviewed/entries.length*100), met, applicable:applicable.length, unknown:entries.filter(c=>c.status==='unknown').length, unresolved:entries.filter(c=>c.status==='needs_improvement').length};
}
export const PHOTO_STEPS=['Front','Back','Left side','Right side','Roof and gutters','Vents','Deck and fences','Vegetation','Material storage'] as const;
export function materialAdvice(kind:string,clean:boolean,untreated:boolean) {
  if(kind==='wood' && clean && untreated) return 'Potential personal firewood: confirm suitability for your appliance and local use restrictions. Store at least 30 feet from the home; do not burn to dispose of debris.';
  if(kind==='wood') return 'Do not recommend for burning. Painted, treated, contaminated, or unidentified wood needs appropriate disposal guidance.';
  if(kind==='yard') return 'Consider approved green-waste collection or processing. Relocate combustible debris away from the home; avoid creating a new nearby pile.';
  return 'Identify the material before reuse or disposal. Keep potentially combustible items out of the immediate zone.';
}
