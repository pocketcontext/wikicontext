// Derived search data only: immutable business records remain unchanged.
migrate(app => {
  const access = "@request.auth.id != '' && @request.auth.collectionName = 'users' && @request.auth.disabled = false";
  app.save(new Collection({name:'search_state',type:'base',listRule:access,viewRule:access,
    createRule:null,updateRule:null,deleteRule:null,
    fields:[{name:'generation',type:'text',required:true,max:64}]}));
  app.db().newQuery(`CREATE VIRTUAL TABLE "published_pages_fts" USING fts5("record_id" UNINDEXED, "title", "summary", "body", tokenize='unicode61')`).execute();
  // Fail rather than silently omit malformed historical manifest members.
  const bad=new DynamicModel({n:0});
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
          OR r.id IS NULL OR pages.id IS NULL)`).one(bad);
  if(bad.n)throw new Error('Invalid publication manifest; search backfill aborted');
  app.db().newQuery(`INSERT INTO published_pages_fts(record_id,title,summary,body)
    SELECT DISTINCT r.id,r.title,r.summary,r.body FROM publications p, json_each(p.manifest) m
    JOIN page_revisions r ON r.id=m.value AND r.page=m.key WHERE r.archived=false`).execute();
  const state=new Record(app.findCollectionByNameOrId('search_state'));
  state.id='pagesindexstate';state.set('generation',$security.randomString(32));app.save(state);
},()=>{throw new Error('Restore a verified complete backup for rollback');});
