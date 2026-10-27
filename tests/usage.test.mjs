import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {reserveAnalysis} from '../lib/usage.ts';
function setup(){
 const sql=new DatabaseSync(':memory:');
 sql.exec(readFileSync(new URL('../drizzle/0000_striped_terrax.sql',import.meta.url),'utf8'));
 const db={
  prepare(query){
   const s=sql.prepare(query);
   return {bind(...args){return {run:()=>({meta:{changes:s.run(...args).changes}})};}};
  },
  async batch(statements){
   sql.exec('BEGIN');
   try{const r=statements.map(s=>s.run());sql.exec('COMMIT');return r;}
   catch(e){sql.exec('ROLLBACK');throw e;}
  }
 };
 return {sql,db};
}
const input=(id='1',more={})=>({id,owner:'u',propertyId:'p',assessmentId:'a',hash:id,month:'2026-10',reserve:1000000,cap:10000000,...more});
test('reserve before spend, reject parallel active analysis',async()=>{const {db,sql}=setup();assert.equal(await reserveAnalysis(db,input()),true);assert.equal(await reserveAnalysis(db,input('2')),false);assert.equal(sql.prepare('select used_micros from budgets').get().used_micros,1000000);});
test('site budget cannot oversubscribe across properties',async()=>{const {db,sql}=setup();assert.equal(await reserveAnalysis(db,input('1',{cap:1000000})),true);assert.equal(await reserveAnalysis(db,input('2',{propertyId:'other',assessmentId:'other',cap:1000000})),false);assert.equal(sql.prepare('select count(*) n from ai_runs').get().n,1);});
test('three attempts per property per month, failures retained',async()=>{const {db,sql}=setup();for(let i=0;i<3;i++){assert.equal(await reserveAnalysis(db,input(String(i))),true);sql.exec("update ai_runs set status='failed'");}assert.equal(await reserveAnalysis(db,input('4')),false);assert.equal(await reserveAnalysis(db,input('5',{month:'2026-11'})),true);});
test('duplicate inputs roll back budget charge',async()=>{const {db,sql}=setup();await reserveAnalysis(db,input());sql.exec("update ai_runs set status='complete'");await assert.rejects(()=>reserveAnalysis(db,input('2',{hash:'1'})));assert.equal(sql.prepare('select used_micros from budgets').get().used_micros,1000000);});
