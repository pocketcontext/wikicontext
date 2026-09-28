// This module is called only inside the caller's write transaction.
function rotate(app){
 const state=app.findRecordById('search_state','pagesindexstate');
 state.set('generation',$security.randomString(32));app.save(state);
 return state.getString('generation');
}
function publish(app,revisions){
 for(const r of revisions){
  if(r.getBool('archived'))continue;
  app.db().newQuery(`INSERT INTO published_pages_fts(record_id,title,summary,body)
   VALUES ({:id},{:title},{:summary},{:body})`).bind({id:r.id,title:r.getString('title'),summary:r.getString('summary'),body:r.getString('body')}).execute();
 }
 rotate(app);
}
function rebuild(e){
 let generation='';
 e.app.runInTransaction(app=>{
  const invalid=new DynamicModel({n:0});
  app.db().newQuery(`SELECT count(*) n FROM publications p
    WHERE json_type(p.manifest) IS NOT 'object'
      OR (SELECT count(*) FROM json_each(p.manifest))>10000
      OR (SELECT count(*)-count(DISTINCT key) FROM json_each(p.manifest))!=0
      OR EXISTS (
        SELECT 1 FROM json_each(p.manifest) m
        LEFT JOIN page_revisions r ON r.id=m.value AND r.page=m.key
        LEFT JOIN pages ON pages.id=m.key
        WHERE m.type!='text' OR length(m.key)!=15 OR m.key GLOB '*[^a-z0-9]*'
          OR length(m.value)!=15 OR m.value GLOB '*[^a-z0-9]*'
          OR r.id IS NULL OR pages.id IS NULL)`).one(invalid);
  if(invalid.n)throw new Error('Invalid publication manifest; search rebuild aborted');
  app.db().newQuery('DELETE FROM published_pages_fts').execute();
  app.db().newQuery(`INSERT INTO published_pages_fts(record_id,title,summary,body)
   SELECT DISTINCT r.id,r.title,r.summary,r.body FROM publications p, json_each(p.manifest) m
   JOIN page_revisions r ON r.id=m.value AND r.page=m.key WHERE r.archived=false`).execute();
  generation=rotate(app);
 });
 e.response.header().set('Cache-Control','no-store');
 return e.json(200,{stateGeneration:generation});
}
module.exports={publish,rebuild};
