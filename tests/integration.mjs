import assert from 'node:assert/strict';
const base=process.env.TEST_BASE_URL??'http://127.0.0.1:5173';
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base))throw new Error('Integration tests only run against a local disposable preview.');
let checks=0;
const login=await fetch(base+'/signin-with-chatgpt?return_to=/',{redirect:'manual'});
const cookie=login.headers.getSetCookie().map(c=>c.split(';')[0]).join('; ');
async function req(path,method='GET',body,expected=200,headers={}){const res=await fetch(base+'/api/'+path,{method,headers:{Cookie:cookie,Origin:base,...(body instanceof FormData?{}:{'Content-Type':'application/json'}),...headers},body:body instanceof FormData?body:body===undefined?undefined:JSON.stringify(body)});const raw=await res.text();let data;try{data=JSON.parse(raw);}catch{data={error:raw};}assert.equal(res.status,expected,JSON.stringify(data));checks++;return data;}
assert.equal((await fetch(base+'/api/bootstrap')).status,401);checks++;
let state=await req('bootstrap');
if(state.property&&!state.property.address.startsWith('Local QA fixture'))throw new Error('Refusing to change non-test property.');
if(!state.property)await req('properties','POST',{address:'Local QA fixture — Santa Fe city center',point:{lat:35.687,lng:-105.938},outline:[],confirmed:true},201);
state=await req('bootstrap');let a=state.assessments[0];const p=state.property;
await req('properties','POST',{point:p.point,confirmed:true,outline:[]},409);
await req('assessments/foreign-fixture','GET',undefined,404);
await req('assessments/foreign-fixture/file?id=foreign-photo','GET',undefined,404);
await req('assessments/'+a.id,'PATCH',{revision:a.revision,control:{id:'under_deck',status:'not_applicable',note:''}},400);
a=await req('assessments/'+a.id,'PATCH',{revision:a.revision,control:{id:'firewood',status:'needs_improvement',note:'Test fixture'}});
await req('assessments/'+a.id,'PATCH',{revision:a.revision-1,action:{id:'firewood',done:true}},409);
a=await req('assessments/'+a.id,'PATCH',{revision:a.revision,action:{id:'firewood',done:true}});assert.equal(a.controls.firewood.status,'needs_improvement');checks++;
await req('assessments/'+a.id,'PATCH',{revision:a.revision,action:{id:'firewood',done:false}},403,{Origin:'https://another-origin.example'});
a=await req('assessments/'+a.id,'PATCH',{revision:a.revision,skip:'Vents'});assert.ok(a.skipped.includes('Vents'));checks++;
const bad=new FormData();bad.set('revision',a.revision);bad.set('category','Front');bad.set('file',new Blob(['not an image'],{type:'image/jpeg'}),'fake.jpg');await req('assessments/'+a.id+'/photos','POST',bad,400);
// 1x1 baseline JPEG, created locally by a decoder fixture; never personal data.
const {createRequire}=await import('node:module');const require=createRequire(import.meta.url);const sharp=require('sharp');const image=await sharp({create:{width:20,height:20,channels:3,background:'#d5ddd4'}}).jpeg().toBuffer();
for(let i=a.photos.length;i<12;i++){const form=new FormData();form.set('revision',a.revision);form.set('category','Front');form.set('file',new Blob([image],{type:'image/jpeg'}),'fixture.jpg');a=await req('assessments/'+a.id+'/photos','POST',form);}
const over=new FormData();over.set('revision',a.revision);over.set('category','Front');over.set('file',new Blob([image],{type:'image/jpeg'}),'fixture.jpg');await req('assessments/'+a.id+'/photos','POST',over,400);
const file=await fetch(base+'/api/assessments/'+a.id+'/file?id='+a.photos[0].id,{headers:{Cookie:cookie}});assert.equal(file.status,200);assert.equal(file.headers.get('content-type'),'image/jpeg');checks++;
const deletedId=a.photos[0].id;a=await req('assessments/'+a.id+'/photos/'+deletedId,'DELETE');await req('assessments/'+a.id+'/file?id='+deletedId,'GET',undefined,404);
if(!state.aiConfigured)await req('assessments/'+a.id+'/analyze','POST',{},503);
const newer=await req('properties/'+p.id+'/assessments','POST',{},201);assert.equal(newer.version,a.version+1);assert.equal(newer.controls.firewood.status,'unknown');checks++;
state=await req('bootstrap');assert.equal(state.assessments.length>=2,true);checks++;
await req('assessments/'+newer.id,'DELETE');
console.log(`${checks} local API integration checks passed. Test fixture retained for browser inspection; remove before handoff.`);
