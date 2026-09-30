// Home is publication metadata; existing manifests and history stay unchanged.
migrate(app => {
  const pages=app.findCollectionByNameOrId('pages');
  for(const name of ['ingestion_runs','publications']){
    const collection=app.findCollectionByNameOrId(name);
    collection.fields.add(new RelationField({name:'home',collectionId:pages.id,maxSelect:1,cascadeDelete:false}));
    if(name==='ingestion_runs'){
      collection.fields.add(new TextField({name:'home_base',max:15,pattern:'^([a-z0-9]{15})?$'}));
      collection.fields.add(new BoolField({name:'clear_home'}));
    }
    app.save(collection);
  }
},()=>{throw new Error('Restore a verified complete backup for rollback');});
