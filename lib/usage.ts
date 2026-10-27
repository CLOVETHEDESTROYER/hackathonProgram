export async function reserveAnalysis(db:D1Database,input:{id:string;owner:string;propertyId:string;assessmentId:string;hash:string;month:string;reserve:number;cap:number}){
 const {id,owner,propertyId,assessmentId,hash,month,reserve,cap}=input;
 const results=await db.batch([
  db.prepare('INSERT INTO budgets(month,used_micros) VALUES (?,0) ON CONFLICT(month) DO NOTHING').bind(month),
  db.prepare("INSERT INTO ai_runs(id,owner,property_id,assessment_id,hash,month,status,reserved_micros,created_at) SELECT ?,?,?,?,?,?,'running',?,? WHERE (SELECT used_micros FROM budgets WHERE month=?)<=? AND (SELECT COUNT(*) FROM ai_runs WHERE property_id=? AND month=?)<3 AND NOT EXISTS(SELECT 1 FROM ai_runs WHERE assessment_id=? AND status='running')").bind(id,owner,propertyId,assessmentId,hash,month,reserve,new Date().toISOString(),month,cap-reserve,propertyId,month,assessmentId),
  db.prepare('UPDATE budgets SET used_micros=used_micros+? WHERE month=? AND EXISTS(SELECT 1 FROM ai_runs WHERE id=?)').bind(reserve,month,id),
 ]);
 return !!results[1].meta.changes;
}
