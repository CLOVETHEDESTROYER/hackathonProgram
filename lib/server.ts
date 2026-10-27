import { env } from 'cloudflare:workers';
import { getChatGPTUser } from '@/app/chatgpt-auth';
import type { Assessment, Property } from './types';
import { emptyControls, RULE_VERSION } from './rules';
export class HttpError extends Error{constructor(public status:number,message:string){super(message);}}
export function bindings(){if(!env.DB||!env.BUCKET)throw new HttpError(503,'Private storage is not configured yet.');return {db:env.DB,bucket:env.BUCKET};}
export async function userId(){const user=await getChatGPTUser();if(!user)throw new HttpError(401,'Sign in to access your private assessment.');return user.userId;}
export function json(data:unknown,status=200){return Response.json(data,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});}
export function guardOrigin(req:Request){if(req.method==='GET')return;const origin=req.headers.get('origin');if(origin&&origin!==new URL(req.url).origin)throw new HttpError(403,'Cross-origin changes are not allowed.');}
export async function readBody(req:Request,max=100000){const txt=await req.text();if(txt.length>max)throw new HttpError(413,'Request is too large.');try{return JSON.parse(txt);}catch{throw new HttpError(400,'Invalid request.');}}
export async function ownProperty(owner:string,id?:string):Promise<Property|null>{const {db}=bindings();const row=await db.prepare(id?'SELECT data FROM properties WHERE owner=? AND id=?':'SELECT data FROM properties WHERE owner=?').bind(...(id?[owner,id]:[owner])).first<{data:string}>();return row?JSON.parse(row.data):null;}
export async function ownAssessment(owner:string,id:string){
 const {db}=bindings();const row=await db.prepare('SELECT data FROM assessments WHERE owner=? AND id=?').bind(owner,id).first<{data:string}>();if(!row)throw new HttpError(404,'Assessment not found.');const a=JSON.parse(row.data) as Assessment;
 const cutoff=new Date(Date.now()-300000).toISOString();
 const expired=await db.prepare("SELECT id FROM ai_runs WHERE owner=? AND assessment_id=? AND status='running' AND created_at<?").bind(owner,id,cutoff).all<{id:string}>();
 if(expired.results.length){await db.prepare("UPDATE ai_runs SET status='failed' WHERE owner=? AND assessment_id=? AND status='running' AND created_at<?").bind(owner,id,cutoff).run();if(a.analysis.status==='running'){a.analysis={...a.analysis,status:'failed',message:'The previous analysis timed out. No points were awarded. Add or replace a source before another attempt.'};return saveAssessment(owner,a,a.revision);}}
 return a;
}
export async function saveAssessment(owner:string,a:Assessment,expected:number){a.updatedAt=new Date().toISOString();a.revision=expected+1;const result=await bindings().db.prepare('UPDATE assessments SET data=?,revision=? WHERE id=? AND owner=? AND revision=?').bind(JSON.stringify(a),a.revision,a.id,owner,expected).run();if(!result.meta.changes)throw new HttpError(409,'This assessment changed in another window. Reload before trying again.');return a;}
export async function listAssessments(owner:string){const r=await bindings().db.prepare('SELECT data FROM assessments WHERE owner=? ORDER BY version DESC').bind(owner).all<{data:string}>();return r.results.map(r=>JSON.parse(r.data) as Assessment);}
export function freshAssessment(propertyId:string,version:number):Assessment{return {id:crypto.randomUUID(),propertyId,version,ruleVersion:RULE_VERSION,createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),revision:0,controls:emptyControls(),photos:[],skipped:[],findings:[],actions:{},imagery:[],analysis:{status:'idle'}};}
export async function removeFiles(prefix:string){const {bucket}=bindings();let cursor:string|undefined;do{const page=await bucket.list({prefix,cursor});if(page.objects.length)await bucket.delete(page.objects.map(o=>o.key));cursor=page.truncated?page.cursor:undefined;}while(cursor);}
export function runtime(){return env as typeof env & {OPENAI_API_KEY?:string;OPENAI_MODEL?:string;AI_MONTHLY_BUDGET_USD?:string;AI_INPUT_USD_PER_M?:string;AI_OUTPUT_USD_PER_M?:string};}
