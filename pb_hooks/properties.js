// Flat, bounded metadata; the Markdown body remains the place for explanations.
const relationships=['deployment_profiles','applications','resources','credentials','consumers','replaces','replaced_by','members','accountable_owners','backup_owners'];
const targetCatalogs={members:'person',accountable_owners:'group',backup_owners:'group'};
const reserved=['wikicontext_page','wikicontext_revision','id','page','page_id','revision','revision_id','publication','publication_id','kind','title','summary','body','archived','run','base_revision','created','updated','created_by','updated_by','properties','property_evidence','constructor','prototype','__proto__'];
function invalid(message){throw new BadRequestError(message);}
function object(record,field){
 const raw=record.getString(field);
 const value=raw?JSON.parse(raw):null;
 if(value===null)return {};
 if(typeof value!=='object'||Array.isArray(value))invalid(field+' must be an object');
 return value;
}
function validate(record){
 const properties=object(record,'properties'),evidence=object(record,'property_evidence');
 if(Object.keys(properties).length>64)invalid('Too many properties');
 for(const key of Object.keys(properties)){
  if(!/^[a-z][a-z0-9_]{0,63}$/.test(key)||reserved.includes(key))invalid('Invalid or reserved property key: '+key);
  const value=properties[key];
  if(Array.isArray(value)){
   if(value.length>100||value.some(v=>typeof v!=='string'||v.length>2048)||new Set(value).size!==value.length)invalid('Property lists must contain up to 100 unique bounded strings');
  }else if(value!==null&&typeof value!=='boolean'&&!(typeof value==='string'&&value.length<=2048)&&!(typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=Number.MAX_SAFE_INTEGER))invalid('Property values must be bounded scalars or string lists');
  if(key==='catalog_type'&&!['resource','credential','deployment','person','group'].includes(value))invalid('Invalid catalog_type');
  if(relationships.includes(key)&&(!Array.isArray(value)||value.some(v=>! /^[a-z0-9]{15}$/.test(v))))invalid('Relationship properties require page ID lists');
 }
 if(Object.prototype.hasOwnProperty.call(properties,'members')&&properties.catalog_type!=='group')invalid('Only group pages can declare members');
 for(const key of Object.keys(evidence)){
  if(!Object.prototype.hasOwnProperty.call(properties,key))invalid('Evidence requires a property: '+key);
  const markers=evidence[key];
  if(!Array.isArray(markers)||markers.length>32||markers.some(v=>typeof v!=='string'||! /^[1-9][0-9]{0,5}$/.test(v))||new Set(markers).size!==markers.length)invalid('Property evidence requires up to 32 unique citation markers');
 }
 return {properties,evidence};
}
module.exports={validate,relationships,targetCatalogs};
