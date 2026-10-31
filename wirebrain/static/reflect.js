'use strict';
let reflectData=null,reflectTab='overview',reflectBusy=false,reflectPending=false,reflectSignature='',reflectPayload='',reflectStudy=null,reflectStudyRevision=0;

function reflectScope(){
  const period=$('#reflect-period').value,end=asDate(selectedDay),start=asDate(selectedDay);
  if(period!=='all')start.setDate(start.getDate()-(period==='month'?29:period==='week'?6:0));
  return {date_from:period==='all'?'':localDay(start),date_to:period==='all'?'':localDay(end),provider:$('#reflect-provider').value,project:$('#reflect-project').value,offset:-end.getTimezoneOffset()};
}
function updateReflectCollections(projects){
  const select=$('#reflect-project'),value=select.value;select.replaceChildren(node('option','','All collections'));select.firstChild.value='';
  for(const project of projects){const option=node('option','',project.name);option.value=project.name;select.append(option);}select.value=value;
}
function reflectShowTab(tab){
  reflectTab=tab;for(const button of document.querySelectorAll('[data-reflect-tab]')){const active=button.dataset.reflectTab===tab;button.setAttribute('aria-pressed',String(active));$('#reflect-panel-'+button.dataset.reflectTab).hidden=!active;}
}
async function reflectOpenSource(ident){
  try{const rows=await api('/api/thread?exchange='+encodeURIComponent(ident)),source=rows.find(row=>row.id===ident);if(source)openMemory(source);else toast('That source is no longer available.');}catch(error){showError(error);}
}
function reflectOverview(){
  const target=$('#reflect-overview');target.replaceChildren();
  const cards=[['study','Study guide',reflectData.topics.length,'Topics you asked to explain or troubleshoot more than once.'],['use','AI-use map',reflectData.analyzed,'See the kinds of help you requested, with original evidence.'],['macros','Macro library',reflectData.macros.length,'Reusable prompts, email drafts and workflows saved from your chats.'],['suggestions','Memory suggestions',reflectData.suggestions.length,'Review possible personal facts before they join memory.']];
  for(const [tab,title,count,description] of cards){const card=node('article','reflect-card');card.append(node('span','reflect-count',count),node('h3','',title),node('p','muted',description));const open=node('button','text-button','Open ↗');open.onclick=()=>reflectShowTab(tab);card.append(open);target.append(card);}
}
async function reflectStudyGuide(topic,button){
  const version=++reflectStudyRevision,chosen=JSON.stringify(reflectScope());button.disabled=true;$('#reflect-status').textContent='Preparing a small study guide…';
  try{const result=await post('/api/reflect/study',{...reflectScope(),topic,generate:$('#reflect-study-ai').checked});if(version!==reflectStudyRevision||chosen!==JSON.stringify(reflectScope()))return;reflectStudy=result;$('#reflect-study-output').replaceChildren(renderText(result.body));$('#reflect-study-actions').hidden=false;$('#reflect-status').textContent=result.generated?'AI draft ready. Check its source explanations.':'Practice guide ready from original sources; no model was used.';}
  catch(error){$('#reflect-status').textContent=error.message;}finally{button.disabled=false;}
}
function reflectTopics(){
  const target=$('#reflect-topics');target.replaceChildren();
  if(!reflectData.topics.length){empty(target,'No repeated explanation topics yet.','A topic appears when it is revisited in at least two captured explanation or troubleshooting prompts.');return;}
  for(const topic of reflectData.topics){const card=node('article','reflect-card');card.append(node('h3','',topic.topic),node('p','muted',`${topic.count} prompts · ${topic.days.length} day${topic.days.length===1?'':'s'}`),node('p','',topic.suggestion));const actions=node('div','reflect-actions'),guide=node('button','quiet-button','Make study guide'),source=node('button','text-button','See original ↗');guide.onclick=()=>reflectStudyGuide(topic.topic,guide);source.onclick=()=>reflectOpenSource(topic.sources[0]);actions.append(guide,source);card.append(actions);target.append(card);}
}
function reflectUseMap(){
  const target=$('#reflect-use-map');target.replaceChildren();
  if(!reflectData.analyzed){empty(target,'No request patterns to show yet.','Useful captured prompts will appear here. Greetings and labeled tests are excluded.');return;}
  for(const bucket of reflectData.use_map){if(!bucket.count)continue;const card=node('article','reflect-use-row'),label=node('div','reflect-use-label');label.append(node('strong','',bucket.title),node('span','',`${bucket.count} · ${bucket.percent}%`));const track=node('div','reflect-use-track'),bar=node('span');track.setAttribute('role','img');track.setAttribute('aria-label',`${bucket.title}: ${bucket.count} of ${reflectData.analyzed} prompts`);bar.style.width=bucket.percent+'%';track.append(bar);card.append(label,track,node('p','muted',bucket.checkin));const evidence=node('details');evidence.append(node('summary','','Check source prompts'));for(const row of bucket.sources){const open=node('button','source-card',row.prompt);open.onclick=()=>reflectOpenSource(row.id);evidence.append(open);}card.append(evidence);target.append(card);}
}
function reflectMacros(){
  const target=$('#reflect-macros');target.replaceChildren();const query=$('#reflect-macro-query').value.toLowerCase(),items=(reflectData?.macros||[]).filter(item=>(item.title+' '+item.content).toLowerCase().includes(query));
  if(!items.length){empty(target,query?'No matching templates.':'Your reusable work will appear here.','Structured prompts, email drafts and step-by-step workflows are saved automatically from completed chats.');return;}
  for(const item of items){const card=node('article','reflect-card');card.append(node('span','muted',`${item.kind} · ${names[item.source.provider]||item.source.provider}`),node('h3','',item.title));const details=node('details');details.append(node('summary','','Read template'),node('pre','',item.content));card.append(details);const actions=node('div','reflect-actions'),copy=node('button','quiet-button','Copy'),downloadButton=node('button','quiet-button','Download'),source=node('button','text-button','Source ↗'),remove=node('button','text-button danger','Remove');copy.onclick=()=>workflowCopy(item.content);downloadButton.onclick=()=>download(item.content,'wirebrain-'+item.kind+'-'+item.id.slice(0,8)+'.md');source.onclick=()=>reflectOpenSource(item.exchange_id);remove.onclick=async()=>{if(!confirm('Remove this template from your library? It will not be automatically added again. The original conversation stays in your diary.'))return;remove.disabled=true;try{await post('/api/reflect/remove-macro',{id:item.id});await loadReflectTools(true);}catch(error){showError(error);}finally{remove.disabled=false;}};actions.append(copy,downloadButton,source,remove);card.append(actions);target.append(card);}
}
function reflectSuggestions(){
  const target=$('#reflect-suggestions');target.replaceChildren();if(!reflectData.suggestions.length)empty(target,'Nothing waiting for review.','Possible personal facts from your conversations will appear here.');else target.append(...reflectData.suggestions.map(personalMemoryCard));
}
async function loadReflectTools(force=false){
  if(view!=='review')return;
  const chosen=reflectScope(),signature=JSON.stringify([chosen,stats.exchanges,diary.entries.map(row=>[row.id,row.status,row.response.length])]);
  if(!force&&signature===reflectSignature)return;if(reflectBusy){reflectPending=true;return;}reflectBusy=true;reflectSignature=signature;
  try{const data=await post('/api/reflect/analyze',chosen);if(JSON.stringify(reflectScope())!==JSON.stringify(chosen)){reflectPending=true;return;}reflectData=data;$('#reflect-status').textContent=`${data.total} captured moments · ${data.analyzed} prompts analyzed. ${data.note}`;const payload=JSON.stringify(data);if(payload!==reflectPayload){reflectPayload=payload;reflectOverview();reflectTopics();reflectUseMap();reflectMacros();reflectSuggestions();}}
  catch(error){reflectSignature='';$('#reflect-status').textContent=error.message;}
  finally{reflectBusy=false;if(reflectPending){reflectPending=false;queueMicrotask(()=>loadReflectTools(true));}}
}
function reflectInvalidate(){reflectStudyRevision++;reflectSignature='';reflectStudy=null;$('#reflect-study-output').replaceChildren();$('#reflect-study-actions').hidden=true;renderReview();}
for(const button of document.querySelectorAll('[data-reflect-tab]'))button.onclick=()=>reflectShowTab(button.dataset.reflectTab);
for(const id of ['reflect-period','reflect-provider','reflect-project'])$('#'+id).onchange=reflectInvalidate;
$('#refresh-reflect').onclick=reflectInvalidate;$('#reflect-macro-query').oninput=reflectMacros;
$('#reflect-copy-study').onclick=()=>{if(reflectStudy)workflowCopy(reflectStudy.body);};
$('#reflect-download-study').onclick=()=>{if(reflectStudy)download(reflectStudy.body,'wirebrain-study-guide.md');};
setInterval(()=>{if(!document.hidden&&view==='review')loadReflectTools(true);},20000);
