import { bindings, userId, json, HttpError, guardOrigin, readBody, ownProperty, ownAssessment, listAssessments, freshAssessment, saveAssessment, removeFiles, runtime } from '@/lib/server';
import { analyze, budgetMicros } from '@/lib/analysis';
import { aerial, geocode, validatePoint } from '@/lib/geo';
import { sanitizeJpeg } from '@/lib/images';
import { PHOTO_STEPS, RULES } from '@/lib/rules';
import type { Property, Point } from '@/lib/types';
export const dynamic='force-dynamic';
async function handle(req:Request){
  try{
    guardOrigin(req);const owner=await userId();const {db,bucket}=bindings();const path=new URL(req.url).pathname.replace(/^\/api\//,'').split('/');const [resource,id,operation]=path;
    if(resource==='bootstrap'&&req.method==='GET')return json({property:await ownProperty(owner),assessments:await listAssessments(owner),aiConfigured:!!runtime().OPENAI_API_KEY,monthlyBudget:budgetMicros()/1_000_000});
    if(resource==='geocode'&&req.method==='POST'){const body=await readBody(req);if(typeof body.address!=='string'||body.address.length<5||body.address.length>300)throw new HttpError(400,'Enter a street address.');return json(await geocode(body.address));}
    if(resource==='properties'&&!id&&req.method==='POST'){
      const body=await readBody(req);validatePoint(body.point);if(!body.confirmed)throw new HttpError(400,'Confirm the correct home on the map.');
      if(await ownProperty(owner))throw new HttpError(409,'The pilot supports one property per account.');
      const p:Property={id:crypto.randomUUID(),address:String(body.address||'Manually selected Santa Fe property').slice(0,300),point:body.point,confirmed:true,outline:validOutline(body.outline),createdAt:new Date().toISOString()};
      const a=freshAssessment(p.id,1);await db.batch([db.prepare('INSERT INTO properties(id,owner,data) VALUES (?,?,?)').bind(p.id,owner,JSON.stringify(p)),db.prepare('INSERT INTO assessments(id,property_id,owner,version,revision,data) VALUES (?,?,?,?,0,?)').bind(a.id,p.id,owner,1,JSON.stringify(a))]);return json({property:p,assessment:a},201);
    }
    if(resource==='properties'&&id){
      const p=await ownProperty(owner,id);if(!p)throw new HttpError(404,'Property not found.');
      if(req.method==='DELETE'){await removeFiles(p.id+'/');await db.batch([db.prepare('DELETE FROM assessments WHERE owner=? AND property_id=?').bind(owner,p.id),db.prepare('DELETE FROM properties WHERE owner=? AND id=?').bind(owner,p.id)]);return json({deleted:true});}
      if(operation==='assessments'&&req.method==='POST'){const old=await listAssessments(owner);if(old.some(a=>a.analysis.status==='running'))throw new HttpError(409,'Wait for the active analysis to finish.');const a=freshAssessment(p.id,Math.max(0,...old.map(a=>a.version))+1);await db.prepare('INSERT INTO assessments(id,property_id,owner,version,revision,data) VALUES (?,?,?,?,0,?)').bind(a.id,p.id,owner,a.version,JSON.stringify(a)).run();return json(a,201);}
      if(req.method==='GET')return json(p);
    }
    if(resource==='imagery'&&req.method==='POST'){
      const body=await readBody(req);const result=await aerial(body.point,body.kind==='neighborhood'?'neighborhood':'property');return json({image:'data:image/jpeg;base64,'+toBase64(new Uint8Array(result.bytes)),meta:result.meta});
    }
    if(resource==='assessments'&&id){
      const a=await ownAssessment(owner,id);
      if(operation==='file'&&req.method==='GET'){
        const fileId=new URL(req.url).searchParams.get('id');const f=[...a.photos,...a.imagery].find(p=>p.id===fileId);if(!f)throw new HttpError(404,'Image not found.');const obj=await bucket.get(f.key);if(!obj)throw new HttpError(404,'Image no longer available.');return new Response(obj.body,{headers:{'Content-Type':'image/jpeg','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'"}});
      }
      if(operation==='analyze'&&req.method==='POST')return json(await analyze(owner,a));
      if(operation==='imagery'&&req.method==='POST'){
        const body=await readBody(req);if(body.revision!==a.revision)throw new HttpError(409,'Reload the updated assessment.');const p=await ownProperty(owner,a.propertyId);if(!p)throw new HttpError(404,'Property not found.');
        const result=await aerial(p.point,body.kind==='neighborhood'?'neighborhood':'property');const old=a.imagery.find(i=>i.kind===result.meta.kind);result.meta.key=`${a.propertyId}/${a.id}/${result.meta.id}.jpg`;await bucket.put(result.meta.key,result.bytes,{httpMetadata:{contentType:'image/jpeg'}});a.imagery=a.imagery.filter(i=>i.kind!==result.meta.kind).concat(result.meta);a.analysis={status:'idle'};
        try{const saved=await saveAssessment(owner,a,a.revision);if(old)await bucket.delete(old.key);return json(saved);}catch(e){await bucket.delete(result.meta.key);throw e;}
      }
      if(operation==='photos'&&req.method==='POST'){
        if(Number(req.headers.get('content-length')??0)>1_500_000)throw new HttpError(413,'Photo too large.');if(a.photos.length>=12)throw new HttpError(400,'The pilot allows 12 photos per assessment.');
        const form=await req.formData();if(Number(form.get('revision'))!==a.revision)throw new HttpError(409,'Reload the updated assessment before uploading.');const file=form.get('file');const category=String(form.get('category'));if(!(PHOTO_STEPS as readonly string[]).includes(category)||!file||typeof file==='string')throw new HttpError(400,'Choose a photo and category.');if(file.size>1_200_000)throw new HttpError(413,'Photo too large.');const bytes=sanitizeJpeg(new Uint8Array(await file.arrayBuffer()));const photo={id:crypto.randomUUID(),category,key:'',createdAt:new Date().toISOString()};photo.key=`${a.propertyId}/${a.id}/${photo.id}.jpg`;await bucket.put(photo.key,bytes,{httpMetadata:{contentType:'image/jpeg'}});a.photos.push(photo);a.skipped=a.skipped.filter(c=>c!==category);a.analysis={status:'idle'};
        try{return json(await saveAssessment(owner,a,a.revision));}catch(e){await bucket.delete(photo.key);throw e;}
      }
      if(operation==='photos'&&path[3]&&req.method==='DELETE'){
        if(a.analysis.status==='running')throw new HttpError(409,'Wait for analysis before removing a source photo.');const photo=a.photos.find(p=>p.id===path[3]);if(!photo)throw new HttpError(404,'Photo not found.');a.photos=a.photos.filter(p=>p.id!==photo.id);a.findings=a.findings.filter(f=>f.photoId!==photo.id);a.analysis={status:'idle'};const saved=await saveAssessment(owner,a,a.revision);await bucket.delete(photo.key);return json(saved);
      }
      if(req.method==='GET')return json(a);
      if(req.method==='DELETE'){if(a.analysis.status==='running')throw new HttpError(409,'Wait for analysis to finish before deleting this assessment.');await removeFiles(`${a.propertyId}/${a.id}/`);await db.prepare('DELETE FROM assessments WHERE owner=? AND id=?').bind(owner,a.id).run();return json({deleted:true});}
      if(req.method==='PATCH'){
        const body=await readBody(req);if(body.revision!==a.revision)throw new HttpError(409,'This assessment changed. Reload before saving.');
        if(body.control){const {id,status,note}=body.control;if(!RULES.some(r=>r.id===id)||!['unknown','met','needs_improvement','not_applicable'].includes(status))throw new HttpError(400,'Invalid checklist response.');if(status==='not_applicable'&&!String(note??'').trim())throw new HttpError(400,'Explain why this control does not apply.');a.controls[id as keyof typeof a.controls]={status,note:String(note??'').slice(0,1500),updatedAt:new Date().toISOString()};}
        if(body.finding){const f=a.findings.find(f=>f.id===body.finding.id);if(!f||!['unresolved','confirmed','corrected','dismissed'].includes(body.finding.status))throw new HttpError(400,'Invalid finding update.');f.status=body.finding.status;f.note=String(body.finding.note??'').slice(0,1500);if(['corrected','dismissed'].includes(f.status)&&!f.note.trim())throw new HttpError(400,'Add a reason for your correction or dismissal.');}
        if(body.skip){if(!(PHOTO_STEPS as readonly string[]).includes(body.skip))throw new HttpError(400,'Invalid photo category.');a.skipped=Array.from(new Set([...a.skipped,body.skip]));}
        if(body.action){if(!RULES.some(r=>r.id===body.action.id)||typeof body.action.done!=='boolean')throw new HttpError(400,'Invalid task.');a.actions[body.action.id]=body.action.done;}
        return json(await saveAssessment(owner,a,a.revision));
      }
    }
    throw new HttpError(404,'Not found.');
  }catch(e){if(e instanceof HttpError)return json({error:e.message},e.status);return json({error:e instanceof Error&&/Santa Fe|image|JPEG|aerial|public data/.test(e.message)?e.message:'The request could not be completed. Your saved assessment is unchanged. Please try again.'},400);}
}
function validOutline(value:unknown):Point[]{if(!Array.isArray(value)||value.length>40||(value.length>0&&value.length<3))throw new HttpError(400,'Use no outline, or 3–40 outline points.');return value.map(p=>{validatePoint(p);return {lat:p.lat,lng:p.lng};});}
function toBase64(bytes:Uint8Array){let s='';for(let i=0;i<bytes.length;i+=8192)s+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(s);}
export const GET=handle;export const POST=handle;export const PATCH=handle;export const DELETE=handle;
