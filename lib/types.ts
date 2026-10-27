import type { Controls, RuleId } from './rules';
export type Point={lat:number;lng:number};
export type Imagery={id:string;kind:'property'|'neighborhood';key:string;bounds:[[number,number],[number,number]];items:{id:number;date:number|null;year:number|null;resolution:number|null;units:string|null}[];fetchedAt:string};
export type Photo={id:string;category:string;key:string;createdAt:string};
export type Finding={id:string;ruleId:RuleId;photoId:string;observation:string;confidence:'low'|'medium'|'high';missing:string;box:{x:number;y:number;width:number;height:number}|null;status:'unresolved'|'confirmed'|'corrected'|'dismissed';note:string;observedAt:string;historical:boolean};
export type Assessment={id:string;propertyId:string;version:number;ruleVersion:string;createdAt:string;updatedAt:string;revision:number;controls:Controls;photos:Photo[];skipped:string[];findings:Finding[];actions:Record<string,boolean>;imagery:Imagery[];analysis:{status:'idle'|'running'|'complete'|'failed';runId?:string;hash?:string;message?:string}};
export type Property={id:string;address:string;point:Point;confirmed:boolean;outline:Point[];createdAt:string};
export type Bootstrap={property:Property|null;assessments:Assessment[];aiConfigured:boolean;monthlyBudget:number};
