// Operators can rebuild derived data; no standard record API can mutate it.
routerAdd('POST','/api/wiki/search/rebuild',e=>require(`${__hooks}/search.js`).rebuild(e),$apis.requireSuperuserAuth());
onRecordCreateRequest(e=>{throw new ForbiddenError('Server managed');},'search_state');
onRecordUpdateRequest(e=>{throw new ForbiddenError('Server managed');},'search_state');
onRecordDeleteRequest(e=>{throw new ForbiddenError('Server managed');},'search_state');
