// Properties belong to immutable revisions, so historical publications retain their assessments.
migrate(app => {
  const collection=app.findCollectionByNameOrId('page_revisions');
  collection.fields.add(new JSONField({name:'properties',maxSize:65536}));
  collection.fields.add(new JSONField({name:'property_evidence',maxSize:16384}));
  app.save(collection);
},()=>{throw new Error('Restore a verified complete backup for rollback');});
