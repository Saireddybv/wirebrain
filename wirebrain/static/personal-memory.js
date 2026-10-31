'use strict';
let personalMemoryBusy=false, personalMemoryEditing=null, personalMemoryListSignature='';

function renderMemoryRollup(data){
  const box=$('#memory-rollup');box.hidden=memoryPageTab!=='all'||Boolean(query);
  if(box.hidden)return;
  const signature=JSON.stringify([data.title,data.scope,data.summary,data.total,data.included,data.sources,data.preview,data.error,data.summary?'':data.building]);
  if(box.dataset.signature===signature)return;
  box.dataset.signature=signature;box.replaceChildren();
  box.append(node('h2','',data.title));
  const scope=data.scope?data.scope:'Personal memory';
  const count=data.included<data.total?`${data.included} of ${data.total} reusable memories`:`${data.total} reusable memor${data.total===1?'y':'ies'}`;
  box.append(node('p','muted',`${scope} · ${count}`));
  if(data.summary)box.append(renderText(data.summary));
  else if(data.total){
    const list=node('ul');for(const item of data.preview)list.append(node('li','',item.text));box.append(list);
    if(data.error)box.append(node('p','muted','The AI overview could not be updated. Original memories are available below.'));
    else if(data.building)box.append(node('p','muted','Putting this memory together…'));
  }else box.append(node('p','muted','No reusable memories from these chats yet. They will appear as useful topics and preferences are captured.'));
  if(data.sources.length){const evidence=node('details');evidence.append(node('summary','',`Based on ${data.sources.length} source memor${data.sources.length===1?'y':'ies'}`));for(const memory of data.sources){evidence.append(node('p','muted',`[${memory.citation}] ${memory.text}`));for(const source of memory.sources){const open=node('button','text-button',`${names[source.provider]||source.provider} conversation ↗`);open.onclick=()=>openMemory({id:source.exchange_id,provider:source.provider,project:source.project});evidence.append(open);}}box.append(evidence);}
}

function editPersonalMemory(memory=null){
  personalMemoryEditing=memory;
  $('#personal-memory-editor-title').textContent=memory?'Edit memory':'Remember something';
  $('#personal-memory-text').value=memory?.text||'';
  $('#personal-memory-kind').value=memory?.kind||'fact';
  $('#personal-memory-scope').value=memory?.scope??collectionFilter;
  $('#personal-memory-edit-error').textContent='';
  $('#personal-memory-editor').showModal();$('#personal-memory-text').focus();
}

async function changePersonalMemory(memory,action,button){
  if(action==='forget'&&!confirm('Forget this memory? Its saved text and edit history will be removed. Supporting messages will stop contributing new suggestions. Original conversations remain in your diary.'))return;
  button.disabled=true;
  try{await post('/api/personal-memory/action',{id:memory.id,action});if(view==='review')await loadReflectTools(true);else await loadPersonalMemory();toast(action==='approve'?'Memory approved.':'Memory forgotten.');}
  catch(error){showError(error);}finally{button.disabled=false;}
}

function personalMemoryCard(memory){
  const card=node('article','personal-memory-card');
  const meta=node('div','personal-memory-meta');meta.append(node('span','',memory.kind),node('span','',memory.scope||'Personal'),node('span','',memory.status==='suggested'?'Needs review':memory.status==='automatic'?'From your conversations':'Reviewed'),node('time','',new Date(memory.updated).toLocaleDateString()));card.append(meta,node('p','personal-memory-text',memory.text));
  const sources=node('details');sources.append(node('summary','',memory.sources.length?`${memory.sources.length} source${memory.sources.length===1?'':'s'}`:'Added by you'));
  for(const source of memory.sources){const quote=node('blockquote','',source.quote),open=node('button','text-button',`${names[source.provider]||source.provider} · ${new Date(source.created).toLocaleDateString()} ↗`);open.onclick=()=>openMemory({id:source.exchange_id,provider:source.provider,project:source.project});sources.append(quote,open);}
  if(memory.history?.length){const history=node('details');history.append(node('summary','',`Previous edits (${memory.history.length})`));for(const version of memory.history)history.append(node('p','muted',`${new Date(version.updated).toLocaleDateString()} · ${version.scope||'Personal'}: ${version.text}`));sources.append(history);}
  card.append(sources);
  const actions=node('div','personal-memory-card-actions');
  if(memory.status==='suggested'){const approve=node('button','quiet-button','Approve');approve.onclick=()=>changePersonalMemory(memory,'approve',approve);actions.append(approve);}
  const edit=node('button','quiet-button','Edit'),forget=node('button','text-button danger',memory.status==='suggested'?'Dismiss':'Forget');edit.onclick=()=>editPersonalMemory(memory);forget.onclick=()=>changePersonalMemory(memory,'forget',forget);actions.append(edit,forget);card.append(actions);return card;
}

async function loadPersonalMemory(){
  if(personalMemoryBusy||view!=='memories'||memoryPageTab==='conversations')return;
  personalMemoryBusy=true;const version=revision;
  try{
    const params=new URLSearchParams({q:query,provider,status:'approved',mode:searchMode});if(collectionFilter)params.set('scope',collectionFilter);
    const data=await api('/api/personal-memory?'+params);if(version!==revision)return;
    if(memoryPageTab==='all'&&!query){
      const summary=await post('/api/personal-memory/summary-refresh',{provider,scope:collectionFilter});
      if(version!==revision)return;renderMemoryRollup(summary);
    }else $('#memory-rollup').hidden=true;
    $('#auto-personal-memory').checked=data.state.enabled;
    $('#extract-personal-memory').disabled=data.state.running||!data.model;
    $('#setup-personal-memory').hidden=Boolean(data.model);
    const backend=data.writing_provider==='chatgpt'?'ChatGPT sign-in (testing)':'local AI';
    $('#personal-memory-status').textContent=data.state.error||(!data.model?'Connect a writing backend in Local setup to build memory automatically.':data.state.running?`Building memories with ${backend}…`:`Memories are built from your conversations with ${backend}. Automatic processing ${data.state.enabled?'on':'off'}.`);
    if(query&&searchMode==='semantic')$('#search-status').textContent=data.embedding_model?'Meaning search uses indexed approved facts. New and edited facts are indexed in the background.':'Meaning search is not configured; showing word matches. Enable an embedding model in Local setup.';
    const target=$('#personal-memory-list'),rows=sortOrder==='oldest'?[...data.memories].reverse():data.memories;
    const signature=JSON.stringify([memoryPageTab,provider,collectionFilter,query,sortOrder,rows]);
    if(signature!==personalMemoryListSignature){personalMemoryListSignature=signature;target.replaceChildren();
      if(!rows.length)empty(target,memoryPageTab==='suggested'?'No personal facts waiting for review.':'Your memory is taking shape.',query?'Try another phrase or app filter.':'Useful topics and preferences from your recorded chats will appear here automatically. Greetings and test messages are skipped.');
      else target.append(...rows.map(personalMemoryCard));
    }
    const list=$('#personal-memory-collections');list.replaceChildren();for(const option of $('#collection-filter').options){if(option.value){const item=node('option');item.value=option.value;list.append(item);}}
  }catch(error){showError(error);}finally{personalMemoryBusy=false;if(version!==revision&&view==='memories'&&memoryPageTab!=='conversations')queueMicrotask(loadPersonalMemory);}
}

document.querySelectorAll('[data-memory-tab]').forEach(button=>button.onclick=()=>{memoryPageTab=button.dataset.memoryTab;document.querySelectorAll('[data-memory-tab]').forEach(tab=>tab.setAttribute('aria-pressed',String(tab===button)));revision++;lastRender='';heading();refresh();});
$('#close-personal-memory').onclick=()=>$('#personal-memory-editor').close();
$('#personal-memory-form').onsubmit=async event=>{event.preventDefault();const button=$('#save-personal-memory');button.disabled=true;try{await post('/api/personal-memory/save',{...(personalMemoryEditing?{id:personalMemoryEditing.id}:{}),text:$('#personal-memory-text').value,kind:$('#personal-memory-kind').value,scope:$('#personal-memory-scope').value});$('#personal-memory-editor').close();await updateOverview();if(view==='review')await loadReflectTools(true);else await loadPersonalMemory();toast('Memory saved.');}catch(error){$('#personal-memory-edit-error').textContent=error.message;}finally{button.disabled=false;}};
$('#setup-personal-memory').onclick=()=>$('#local-setup').click();
$('#extract-personal-memory').onclick=async()=>{const button=$('#extract-personal-memory');button.disabled=true;try{await post('/api/personal-memory/process',{});await loadPersonalMemory();}catch(error){showError(error);}finally{button.disabled=false;}};
$('#auto-personal-memory').onchange=async()=>{const control=$('#auto-personal-memory');control.disabled=true;try{await post('/api/personal-memory/settings',{enabled:control.checked});await loadPersonalMemory();}catch(error){control.checked=!control.checked;showError(error);}finally{control.disabled=false;}};
setInterval(()=>{if(!document.hidden)loadPersonalMemory();},5000);
