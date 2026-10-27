import type { Point, Imagery } from './types';
export const NAIP='https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer';
export async function fetchJson(url:string,timeout=20000){const r=await fetch(url,{signal:AbortSignal.timeout(timeout)});if(!r.ok)throw new Error('The public data service is unavailable. Try again or continue with photos.');const data=await r.json() as any;if(data.error)throw new Error('The imagery service could not return this view.');return data;}
export function validatePoint(point:Point){if(!point||!Number.isFinite(point.lat)||!Number.isFinite(point.lng)||point.lat<35.1||point.lat>36.2||point.lng< -106.6||point.lng> -105.5)throw new Error('Choose a location in the Santa Fe pilot area.');}
export async function geocode(address:string){const params=new URLSearchParams({address,benchmark:'Public_AR_Current',format:'json'});const data=await fetchJson('https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?'+params);return (data.result?.addressMatches??[]).map((m:any)=>({address:m.matchedAddress,point:{lat:m.coordinates.y,lng:m.coordinates.x}})).filter((m:any)=>m.point.lat>=35.1&&m.point.lat<=36.2&&m.point.lng>=-106.6&&m.point.lng<=-105.5).slice(0,5);}
function unproject(x:number,y:number):[number,number]{return [180/Math.PI*(2*Math.atan(Math.exp(y/6378137))-Math.PI/2),x/6378137*180/Math.PI];}
export async function aerial(point:Point,kind:'property'|'neighborhood'){
  validatePoint(point);const radius=kind==='property'?150:500;const dy=radius/111320,dx=dy/Math.cos(point.lat*Math.PI/180);const box=[point.lng-dx,point.lat-dy,point.lng+dx,point.lat+dy];
  const q=new URLSearchParams({f:'json',geometry:box.join(','),geometryType:'esriGeometryEnvelope',inSR:'4326',spatialRel:'esriSpatialRelIntersects',where:'Category=1',outFields:'OBJECTID,Year,acquisition_date,resolution_value,resolution_units',returnGeometry:'false',orderByFields:'acquisition_date DESC'});
  const catalog=await fetchJson(NAIP+'/query?'+q);const items=(catalog.features??[]).slice(0,30).map((f:any)=>({id:f.attributes.OBJECTID,date:f.attributes.acquisition_date??null,year:f.attributes.Year??null,resolution:f.attributes.resolution_value??null,units:f.attributes.resolution_units??null}));
  if(!items.length)throw new Error('No aerial coverage was found here. You can continue with ground photos.');
  const params=new URLSearchParams({f:'json',bbox:box.join(','),bboxSR:'4326',imageSR:'3857',size:'1024,1024',format:'jpg',adjustAspectRatio:'true',bandIds:'0,1,2',mosaicRule:JSON.stringify({mosaicMethod:'esriMosaicAttribute',sortField:'acquisition_date',sortValue:'2100/01/01',ascending:true})});
  const exported=await fetchJson(NAIP+'/exportImage?'+params);const url=new URL(exported.href);if(url.protocol!=='https:'||url.hostname!=='imagery.nationalmap.gov')throw new Error('Unexpected imagery source.');
  const r=await fetch(url,{signal:AbortSignal.timeout(20000)});if(!r.ok||!r.headers.get('content-type')?.startsWith('image/'))throw new Error('The aerial image could not be loaded.');const bytes=await r.arrayBuffer();if(bytes.byteLength>6_000_000)throw new Error('Imagery response too large.');
  const e=exported.extent;const bounds:[ [number,number],[number,number] ]=[unproject(e.xmin,e.ymin),unproject(e.xmax,e.ymax)];
  // Catalog coverage may include multiple dates; do not mislabel a mosaic as a
  // single capture. These are candidate source dates, not a guaranteed pixel date.
  return {bytes,meta:{id:crypto.randomUUID(),kind,key:'',bounds,items,fetchedAt:new Date().toISOString()} satisfies Imagery};
}
