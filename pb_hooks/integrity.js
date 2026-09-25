function invalid(s){throw new BadRequestError(s);}
function rows(app,t,f,p={}){return app.findRecordsByFilter(t,f,'',0,0,p);}
function draft(app,id){const r=app.findRecordById('ingestion_runs',id);if(r.getString('status')!=='staging')invalid('Run is closed');return r;}
function publish(app,run){
 const prior=app.findRecordsByFilter('publications','sequence > 0','-sequence',1,0);
 const manifest=prior.length?JSON.parse(prior[0].getString('manifest')):{};
 const revisions=rows(app,'page_revisions','run = {:id}',{id:run.id});
 if(!revisions.length)invalid('Cannot publish an empty run');
 for(const r of revisions){
  const page=r.getString('page');
  if((manifest[page]||'')!==r.getString('base_revision'))throw new ApiError(409,'Page changed since synthesis; reassess in a new run',{});
  manifest[page]=r.id;
 }
 for(const r of revisions){
  const body=r.getString('body');
  if(/^\[\^\d+\]:/m.test(body))invalid('Footnote definitions are rendered from citations');
  const citations=rows(app,'citations','page_revision = {:id}',{id:r.id});
  const markers=new Set([...body.matchAll(/\[\^(\d+)\]/g)].map(m=>m[1]));
  for(const marker of markers)if(!citations.some(c=>c.getString('marker')===marker))invalid('Missing citation marker '+marker);
  for(const c of citations)if(!markers.has(c.getString('marker')))invalid('Unused citation');
  if(!citations.length&&!body.includes('[needs verification]'))invalid('Uncited content must include [needs verification]');
  const links=rows(app,'page_links','page_revision = {:id}',{id:r.id});
  const linked=new Set(links.map(l=>app.findRecordById('pages',l.getString('target')).getString('slug')));
  for(const match of body.matchAll(/\[\[([^\]]+)\]\]/g)){
   const slug=match[1].split('|')[0].split('#')[0];
   if(!linked.has(slug))invalid('Wiki-link needs a page_links record: '+slug);
  }
  for(const link of links){
   const target=manifest[link.getString('target')];
   if(!target||app.findRecordById('page_revisions',target).getBool('archived'))invalid('Link target is not published');
  }
 }
 // Archiving cannot leave links from unchanged published pages dangling.
 for(const page in manifest){const r=app.findRecordById('page_revisions',manifest[page]);if(r.getBool('archived'))continue;
  for(const l of rows(app,'page_links','page_revision = {:id}',{id:r.id})){
   const target=manifest[l.getString('target')];
   if(!target||app.findRecordById('page_revisions',target).getBool('archived'))invalid('Publication would leave a broken link');
  }
 }
 if(Object.keys(manifest).length>10000)invalid('Publication page budget exceeded');
 const p=new Record(app.findCollectionByNameOrId('publications'));p.set('run',run.id);p.set('sequence',prior.length?prior[0].getInt('sequence')+1:1);p.set('manifest',manifest);app.save(p);
}
function validate(app,r){
 const t=r.collection().name;
 if(t==='sources'&&r.getString('supersedes'))app.findRecordById('sources',r.getString('supersedes'));
 if(t==='ingestion_runs'){
  if(r.isNew()&&r.getString('status')!=='staging')invalid('New runs start in staging');
  if(!r.isNew()){
   if(r.original().getString('status')!=='staging')invalid('Closed runs are immutable');
   if(r.getString('key')!==r.original().getString('key'))invalid('Run key is immutable');
  }
 }
 if(t==='pages'&&['index','log'].includes(r.getString('slug')))invalid('Reserved page slug');
 if(t==='page_revisions'){
  draft(app,r.getString('run'));
  const base=r.getString('base_revision');
  if(base&&app.findRecordById('page_revisions',base).getString('page')!==r.getString('page'))invalid('Base revision belongs to another page');
 }
 if(t==='citations'||t==='page_links')draft(app,app.findRecordById('page_revisions',r.getString('page_revision')).getString('run'));
}
function write(e){
 const original=e.app,r=e.record,t=r.collection().name,fresh=r.isNew(),body=e.requestInfo().body;
 original.runInTransaction(app=>{e.app=app;try{
  if(!fresh){
   if(t!=='ingestion_runs')invalid('Immutable record; create a new version');
   const current=app.findRecordById(t,r.id);
   if(!Number.isInteger(body.expected_revision))invalid('expected_revision required');
   if(current.getInt('revision')!==body.expected_revision||current.getInt('revision')!==r.original().getInt('revision'))throw new ApiError(409,'Revision conflict',{});
  }
  for(const k of ['revision','created_by','updated_by','created','updated','sha256'])if(Object.prototype.hasOwnProperty.call(body,k))invalid(k+' is server managed');
  const actor=e.auth&&e.auth.collection().name==='users'?e.auth.id:'';
  r.set('_audit_actor',actor?'user:'+actor:'superuser:'+e.auth.id);
  r.set('created_by',fresh?actor:r.original().getString('created_by'));r.set('updated_by',actor);r.set('revision',fresh?1:r.original().getInt('revision')+1);
  validate(app,r);
  if(t==='ingestion_runs'&&!fresh&&r.getString('status')==='published')publish(app,r);
  e.next();
 }finally{e.app=original;}});
}
function audit(e,action){
 const actor=e.record.getString('_audit_actor');if(!actor)return e.next();e.record.set('_audit_actor','');
 e.next();
 if(e.record.collection().name==='sources'&&action==='create'){
  const path=e.app.dataDir()+'/storage/'+e.record.collection().id+'/'+e.record.id+'/'+e.record.getString('original');
  const hash=toString($os.cmd('sha256sum',path).output()).split(' ')[0];if(!/^[a-f0-9]{64}$/.test(hash))invalid('Cannot hash original');
  e.record.set('sha256',hash);e.app.saveNoValidate(e.record);
 }
 const row=new Record(e.app.findCollectionByNameOrId('audit_log'));row.set('action',action);row.set('collection',e.record.collection().name);row.set('record',e.record.id);row.set('actor',actor.split(':')[1]);row.set('actor_type',actor.split(':')[0]);row.set('changes',{revision:e.record.getInt('revision'),status:e.record.getString('status')});e.app.save(row);
}
module.exports={write,audit};
