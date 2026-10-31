'use strict';
const $ = selector => document.querySelector(selector);
const names = {chatgpt:'ChatGPT',claude:'Claude',openai:'ChatGPT',anthropic:'Claude',groq:'Groq',gemini:'Gemini',grok:'Grok',meta:'Meta AI'};
const icons = {chatgpt:'◎',claude:'✳',openai:'◎',anthropic:'✳',gemini:'✦',grok:'𝕏',meta:'∞'};
const localDay = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const asDate = day => new Date(day+'T12:00:00');
const today = () => localDay(new Date());
let selectedDay=today(), month=asDate(selectedDay), view='diary', provider='', query='', active=null;
let diary={entries:[],days:[],note:''}, visibleRows=[], stats={}, noteDay='', noteDirty=false;
let searchMode='keyword', collectionFilter='', sortOrder='latest';
let memoryPageTab='all';
let busy=false, pending=false, revision=0, lastRender='', startingAt=0;
function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;}
function showError(error){$('#error').hidden=false;$('#error').textContent=error.message||String(error);}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,2800);}
async function api(path,options){const response=await fetch(path,options);const data=await response.json();if(!response.ok)throw new Error(data.error||'Your diary could not connect. Please try again.');return data;}
const post=(path,body)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function shortText(text,length=220){return String(text||'').replace(/^user:\s*/,'').replace(/<Cite\b[^>]*\/>/g,'').replace(/<Link\b[^>]*title="([^"]*)"[^>]*\/>/g,'$1').replace(/[*#`]/g,'').trim().slice(0,length);}
function groupKey(row){return row.thread_id||'unidentified:'+row.id;}
function prettyDay(day){return asDate(day).toLocaleDateString([],{weekday:'long',day:'numeric',month:'long'});}
function download(text,filename){const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));const link=node('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function heading(){
  const titles={diary:['Your conversations','My diary'],memories:['Memory','Memory'],saved:['Favorites','Favorites'],tools:['Tools','Tools'],review:['Reflect','Reflect']};
  const [title,crumb]=titles[view];$('#title').textContent=title;$('#breadcrumb').textContent=crumb;
  $('#timeline-view').hidden=view==='review'||view==='tools';$('#review-view').hidden=view!=='review';$('#workbench').hidden=view!=='tools';
  $('#memory-page-tabs').hidden=view!=='memories';
  $('#personal-memory-panel').hidden=view!=='memories'||memoryPageTab==='conversations';
  $('#timeline').hidden=view==='memories'&&memoryPageTab!=='conversations';
  $('.filter[data-provider=""]').textContent=view==='memories'&&memoryPageTab!=='conversations'?'Wirebrain':'All';
  document.querySelectorAll('[data-memory-tab]').forEach(tab=>tab.setAttribute('aria-pressed',String(tab.dataset.memoryTab===memoryPageTab)));
  document.querySelectorAll('.nav').forEach(el=>{el.classList.toggle('active',el.dataset.view===view);el.setAttribute('aria-current',el.dataset.view===view?'page':'false');});
}
function renderCalendar(){
  $('#month-label').textContent=month.toLocaleDateString([],{month:'long',year:'numeric'});const target=$('#calendar-days');target.replaceChildren();
  const first=new Date(month.getFullYear(),month.getMonth(),1,12), count=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
  for(let i=0;i<(first.getDay()+6)%7;i++)target.append(node('span'));
  const dates=new Map(diary.days.map(day=>[day.day,day]));
  for(let d=1;d<=count;d++){const date=new Date(month.getFullYear(),month.getMonth(),d,12),key=localDay(date),el=node('button','',d);el.type='button';el.classList.toggle('today',key===today());el.classList.toggle('selected',key===selectedDay);el.classList.toggle('has-memory',dates.has(key));el.setAttribute('aria-label',`${prettyDay(key)}${dates.has(key)?', '+dates.get(key).count+' remembered moments':''}`);el.setAttribute('aria-pressed',String(key===selectedDay));el.onclick=()=>chooseDay(key);target.append(el);}
}
function empty(target,title,description){target.replaceChildren();const box=node('div','empty');box.append(node('span','','❧'),node('h3','',title),node('p','',description));target.append(box);}
async function toggleSaved(row,button){
  button.disabled=true;
  try{const next=!row.favorite;await post('/api/entries/'+row.id+'/favorite',{favorite:next});row.favorite=next?1:0;lastRender='';toast(next?'Added to Favorites.':'Removed from Favorites.');await refresh();}catch(error){showError(error);}finally{button.disabled=false;}
}
function memoryCard(items){
  const first=items[0],row=items.at(-1),article=node('article','memory'),top=node('div','memory-top');
  article.classList.toggle('memory--long',(row.response||'').length>300);
  article.classList.toggle('memory--soft',row.provider==='chatgpt'||row.provider==='openai');
  top.append(node('span','memory-time',new Date(row.created).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})));
  const save=node('button','star-button'+(row.favorite?' is-saved':''),row.favorite?'★':'☆');save.type='button';save.setAttribute('aria-label',(row.favorite?'Remove from favorites: ':'Add to favorites: ')+shortText(row.prompt,70));save.setAttribute('aria-pressed',String(Boolean(row.favorite)));save.onclick=()=>toggleSaved(row,save);top.append(save);
  const open=node('button','memory-open');open.type='button';open.append(node('h3','',shortText(row.thread_title||first.prompt,150)||'A conversation to remember'),node('p','',shortText(row.response,260)||(row.status==='streaming'?'The conversation is still unfolding…':'Open this memory to read your question.')));
  open.setAttribute('aria-label',`Open conversation: ${shortText(row.thread_title||first.prompt,150)}. ${items.length} remembered moment${items.length===1?'':'s'}${row.status==='complete'?'':'. '+(row.status==='streaming'?'Still recording':'Partial capture')}`);
  const bottom=node('div','memory-bottom');bottom.append(node('span','app-label',names[row.provider]||'AI conversation'),node('span','turn-count',`${items.length} moment${items.length===1?'':'s'}`));
  if(row.demo)bottom.append(node('span','status-badge','Sample'));
  if(row.status==='streaming')bottom.append(node('span','status-badge','Still writing'));
  else if(row.status!=='complete')bottom.append(node('span','status-badge','Partial capture'));
  bottom.append(node('span','read-link','↗'));open.append(bottom);open.onclick=()=>openMemory(row);article.append(top,open);return article;
}
function masonryColumns(){return $('.main-column').getBoundingClientRect().width>=920?3:2;}
function appendConversationGrid(target,rows){
  const byTime=(a,b)=>new Date(a.created)-new Date(b.created)||a.id-b.id;
  const groups=new Map();
  for(const row of [...rows].sort(byTime)){const key=groupKey(row);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
  const conversations=[...groups.values()].sort((a,b)=>(sortOrder==='oldest'?1:-1)*byTime(a.at(-1),b.at(-1)));
  const grid=node('div','memory-grid'),count=masonryColumns(),columns=Array.from({length:count},()=>node('div','memory-column'));
  grid.classList.toggle('three-columns',count===3);grid.append(...columns);
  conversations.forEach((items,index)=>columns[index%count].append(memoryCard(items)));
  target.append(grid);
}
function renderTimeline(rows){
  const target=$('#timeline');if(!rows.length){empty(target,query?'Nothing here just yet.':view==='saved'?'A place for your favorites.':'A fresh page, waiting for you.',query?'Try a different word or choose another app.':view==='saved'?'Tap the star on a memory you would like to keep close.':selectedDay===today()?'Have a conversation in a supported AI app. When recording is on, your moments will appear here.':'There are no captured conversations for this day. You can still leave a note to yourself.');return;}
  if(query){
    target.replaceChildren();appendConversationGrid(target,rows);return;
  }
  target.replaceChildren();const days=new Map();
  for(const row of rows){const day=localDay(new Date(row.created));if(!days.has(day))days.set(day,[]);days.get(day).push(row);}
  for(const [day,entries] of [...days].sort((a,b)=>(sortOrder==='oldest'?1:-1)*a[0].localeCompare(b[0]))){
    if(view==='memories'||view==='saved')target.append(node('h3','timeline-day',prettyDay(day)));
    appendConversationGrid(target,entries);
  }
}
function renderReview(){
  if(typeof loadReflectTools==='function')loadReflectTools();
  const target=$('#review');target.replaceChildren();
  const app=$('#reflect-provider').value,project=$('#reflect-project').value;
  const reviewRows=diary.entries.filter(row=>(!project||row.project===project)&&(!app||({chatgpt:['chatgpt','openai'],claude:['claude','anthropic']}[app]||[app]).includes(row.provider)));
  if(!reviewRows.length){empty(target,'Every day starts somewhere.','No captured conversations match this app and collection for the selected calendar day.');return;}
  const reflectButton=node('button','quiet-button','✦ Reflect with AI');reflectButton.onclick=reflectWithAI;target.append(reflectButton);
  const intro=node('article','review-card');intro.append(node('h3','','The shape of your day'),node('p','',`You captured ${reviewRows.length} moment${reviewRows.length===1?'':'s'} across ${new Set(reviewRows.map(groupKey)).size} conversation${new Set(reviewRows.map(groupKey)).size===1?'':'s'}. Here are the questions you spent time with.`));target.append(intro);
  appendConversationGrid(target,reviewRows);
  if(diary.note&&!app&&!project){const card=node('article','review-card');card.append(node('h3','','In your own words'),node('p','',diary.note));target.append(card);}
}
function setRecording(capture){
  const running=Boolean(capture.running),starting=!capture.error&&startingAt&&Date.now()-startingAt<30000&&!running;
  if(capture.error){$('#recording-error').textContent=capture.error;$('#recording-error').hidden=false;}
  if(running||capture.error)startingAt=0;
  $('#chip-dot').classList.toggle('off',!running);$('#chip-label').textContent=running?'Recording':starting?'Starting':'Paused';
  $('#recording-chip').setAttribute('aria-label',`Recording ${running?'is on':starting?'is starting':'is paused'}. Open recording controls`);
  $('#recording-dot').classList.toggle('off',!running);$('#recording-title').textContent=running?'Your diary is remembering':starting?'Getting ready to remember':'Recording is paused';
  $('#capture-status').textContent=running?(capture.system_proxy?'Your recorder is connected. Supported text conversations are saved on this computer.':'The recorder is open, but your apps are not connected to it yet.'):starting?'Your recorder is starting. This can take a few moments.':'Your memories are still here. Resume when you want to capture new conversations.';
  const setup=!running&&!starting&&capture.setup_needed;
  const stopping=running&&capture.stopping;
  if(stopping){$('#recording-title').textContent='Pausing the recorder';$('#capture-status').textContent='Your recorder is stopping. You can resume in a moment.';}
  if(setup){$('#recording-title').textContent='Recording needs one-time setup';$('#capture-status').textContent='Your memories are still here. To record new conversations, stop the launcher and run "python start_wirebrain.py" again, then type yes when it asks to enable capture. Resume works after that.';}
  $('#recording-toggle').textContent=stopping?'Pausing…':running?'Pause recording':starting?'Starting…':setup?'Setup needed':'Resume recording';$('#recording-toggle').disabled=Boolean(starting||setup||stopping);$('#recording-toggle').dataset.running=String(running);$('#recording-toggle').dataset.stopping=String(Boolean(stopping));
}
async function refresh(){
  if(busy){pending=true;return;}busy=true;const version=revision,snapshot={day:selectedDay,view,query};
  try{
    const params=new URLSearchParams({day:selectedDay,offset:String(-asDate(selectedDay).getTimezoneOffset())});
    const tasks=[api('/api/stats'),api('/api/journal?'+params)];
    if((view==='memories'&&memoryPageTab==='conversations')||view==='saved')tasks.push(api('/api/memory/search?'+new URLSearchParams({q:query,mode:searchMode,project:collectionFilter,provider,saved:view==='saved'?'1':'0'})));
    const results=await Promise.all(tasks);if(version!==revision)return;
    stats=results[0];diary=results[1];$('#error').hidden=true;$('#nav-count').textContent=stats.exchanges;
    $('#search-status').textContent=results[2]?.unindexed?`${results[2].unindexed} memories are missing from the meaning index. Update it in Local setup.`:query?(searchMode==='semantic'?'Matched by meaning and words on this computer.':'Matched by words in your conversations.'):'';
    visibleRows=(results[2]?.rows||diary.entries).filter(row=>(!collectionFilter||row.project===collectionFilter)&&(!provider||({chatgpt:['chatgpt','openai'],claude:['claude','anthropic']}[provider]||[provider]).includes(row.provider)));
    $('#calendar-moment-count').textContent=diary.entries.length;
    $('#calendar-chat-count').textContent=new Set(diary.entries.map(groupKey)).size;
    $('#calendar-summary').setAttribute('aria-label',`Recorded on ${prettyDay(selectedDay)}`);
    if(noteDay!==selectedDay||!noteDirty){$('#day-note').value=diary.note;noteDay=selectedDay;$('#note-status').textContent=diary.note_updated?'Saved on this computer.':'Only you can see this.';}
    setRecording(stats.capture||{});$('#recording-support').textContent='ChatGPT, Claude, Gemini, Grok & Meta AI · Text capture. The new website adapters are experimental.';$('#recording-notices').textContent=(stats.capture_notices||[]).join(' ');heading();renderCalendar();
    const signature=JSON.stringify([view,memoryPageTab,selectedDay,provider,collectionFilter,query,sortOrder,visibleRows,diary.note]);if(signature!==lastRender){lastRender=signature;if(view==='review')renderReview();else if(view==='memories'&&memoryPageTab!=='conversations'){if(typeof loadPersonalMemory==='function')loadPersonalMemory();}else if(view!=='tools')renderTimeline(visibleRows);}
  }catch(error){showError(error);}finally{busy=false;if(pending){pending=false;refresh();}}
}
function canLeaveNote(){return !noteDirty||confirm('Your note has unsaved changes. Leave this day without saving?');}
function chooseDay(day){setMenu(false);const changed=day!==selectedDay;if(changed&&!canLeaveNote())return;if(changed)noteDirty=false;selectedDay=day;month=asDate(day);query='';$('#search').value='';if(view==='memories'||view==='saved')view='diary';revision++;lastRender='';heading();refresh();}
function showView(next){view=next;setMenu(false);query='';$('#search').value='';revision++;lastRender='';heading();if(next==='tools'&&typeof loadMcpConnections==='function')loadMcpConnections();if(next!=='tools'&&typeof clearRemoteMcpSecret==='function')clearRemoteMcpSecret();window.scrollTo({top:0,behavior:'smooth'});refresh();}
function renderText(text){
  const root=node('div','message-text'),parts=String(text||'').split(/```[^\n]*\n([\s\S]*?)```/g);
  const inline=(el,value)=>{const pattern=/(\*\*([^*]+)\*\*|`([^`]+)`)/g;let start=0,match;while((match=pattern.exec(value))){el.append(document.createTextNode(value.slice(start,match.index)));el.append(node(match[2]?'strong':'code','',match[2]||match[3]));start=pattern.lastIndex;}el.append(document.createTextNode(value.slice(start)));};
  parts.forEach((part,i)=>{if(i%2){root.append(node('pre','',part));return;}for(const paragraph of part.split(/\n\s*\n/)){if(!paragraph.trim())continue;const heading=paragraph.match(/^#{1,4}\s+(.+)$/);const block=node(heading?'h3':'p');inline(block,heading?heading[1]:paragraph);root.append(block);}});return root;
}
async function openMemory(row){
  active=row;$('#collection-name').value=row.project||'Inbox';const id=row.id;$('#detail-title').textContent=shortText(row.thread_title||row.prompt,120)||'A conversation to remember';$('#detail-meta').textContent=names[row.provider]||'AI conversation';$('#open-original').hidden=!row.source_url;if(row.source_url)$('#open-original').href=row.source_url;
  $('#detail-body').replaceChildren(node('p','muted','Opening your memory…'));if(!$('#detail').open)$('#detail').showModal();
  try{const rows=await api('/api/thread?exchange='+encodeURIComponent(id));if(active?.id!==id||!$('#detail').open)return;const body=$('#detail-body');body.replaceChildren();$('#detail-meta').textContent=`${names[row.provider]||'AI conversation'} · ${rows.length} remembered moment${rows.length===1?'':'s'}${!row.thread_id?' · Captured before chat grouping was available':''}`;
    for(const entry of rows){const turn=node('section','chat-turn'+(entry.id===id?' selected-turn':''));turn.append(node('div','chat-date',new Date(entry.created).toLocaleString([],{dateStyle:'medium',timeStyle:'short'})));const you=node('div','bubble you');you.append(node('div','bubble-label','You'),renderText(entry.prompt));const ai=node('div','bubble');ai.append(node('div','bubble-label',names[entry.provider]||'The reply'),renderText(entry.response||'No reply was captured for this memory.'));turn.append(you,ai);body.append(turn);}
  }catch(error){$('#detail-body').replaceChildren(node('p','muted',error.message));}
}
$('#day-note').oninput=()=>{noteDirty=true;$('#note-status').textContent='A thought in progress…';};
$('#save-note').onclick=async()=>{const button=$('#save-note'),day=selectedDay,body=$('#day-note').value;button.disabled=true;$('#note-status').textContent='Saving…';try{await post('/api/diary/note',{day,body});if(selectedDay===day&&$('#day-note').value===body){noteDirty=false;diary.note=body;$('#note-status').textContent='Saved. A little thought, kept safe.';}toast('Your note is saved.');lastRender='';await refresh();}catch(error){showError(error);$('#note-status').textContent='Not saved. Please try again.';}finally{button.disabled=false;}};
$('#recording-toggle').onclick=async()=>{const button=$('#recording-toggle');button.disabled=true;$('#recording-error').hidden=true;try{if(button.dataset.running==='true'){await post('/api/capture/stop',{});toast('Pausing new recordings. Your memories stay here.');}else{await post('/api/capture/start',{});startingAt=Date.now();setRecording({});toast('Starting your recorder…');}await refresh();}catch(error){startingAt=0;$('#recording-error').textContent=error.message;$('#recording-error').hidden=false;}finally{if(!startingAt&&button.dataset.stopping!=='true')button.disabled=false;}};
function openNotes(focus=false){$('#notes-sheet').showModal();if(focus)$('#day-note').focus();}
$('#quick-note').onclick=()=>openNotes(true);
$('#recording-chip').onclick=()=>{$('#recording-dialog').showModal();};
$('#close-recording').onclick=()=>$('#recording-dialog').close();
$('#close-notes').onclick=()=>$('#notes-sheet').close();
function syncMenuAccessibility(){const narrow=window.matchMedia('(max-width:1023px)').matches,open=document.body.classList.contains('menu-open'),hidden=narrow&&!open;$('#diary-navigation').inert=hidden;$('#diary-navigation').setAttribute('aria-hidden',String(hidden));$('main').inert=narrow&&open;}
function setMenu(open){const wasOpen=document.body.classList.contains('menu-open');document.body.classList.toggle('menu-open',open);$('#menu-toggle').setAttribute('aria-expanded',String(open));$('#menu-toggle').setAttribute('aria-label',open?'Close navigation':'Open navigation');$('#menu-backdrop').hidden=!open;syncMenuAccessibility();if(open)$('#diary-navigation .nav.active').focus();else if(wasOpen&&window.matchMedia('(max-width:1023px)').matches)$('#menu-toggle').focus();}
$('#menu-toggle').onclick=()=>setMenu(!document.body.classList.contains('menu-open'));
$('#menu-backdrop').onclick=()=>setMenu(false);
$('#close-navigation').onclick=()=>setMenu(false);
const navigationMedia=window.matchMedia('(max-width:1023px)');
navigationMedia.addEventListener('change',()=>setMenu(false));
$('#diary-navigation').addEventListener('keydown',event=>{
  if(event.key!=='Tab'||!navigationMedia.matches||!document.body.classList.contains('menu-open'))return;
  const controls=[...$('#diary-navigation').querySelectorAll('a[href],button:not([disabled])')].filter(el=>el.getClientRects().length);
  const first=controls[0],last=controls[controls.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
});
function setTheme(theme){document.documentElement.dataset.theme=theme;$('#theme-toggle').replaceChildren(node('span','',theme==='dark'?'☀':'◐'),document.createTextNode(theme==='dark'?'Light appearance':'Dark appearance'));try{localStorage.setItem('wirebrain-appearance',theme);}catch{}}
$('#theme-toggle').onclick=()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
try{setTheme(localStorage.getItem('wirebrain-appearance')==='dark'?'dark':'light');}catch{setTheme('light');}
$('#previous-month').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()-1,1,12);renderCalendar();};
$('#next-month').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()+1,1,12);renderCalendar();};
let searchTimer;$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{query=$('#search').value;if(view!=='saved'){if(view!=='memories')memoryPageTab='conversations';view='memories';}revision++;lastRender='';heading();refresh();},250);};
for(const button of document.querySelectorAll('.nav'))button.onclick=()=>showView(button.dataset.view);
for(const button of document.querySelectorAll('.filter'))button.onclick=()=>{provider=button.dataset.provider;document.querySelectorAll('.filter').forEach(el=>el.classList.toggle('active',el===button));revision++;lastRender='';refresh();};
$('#close-detail').onclick=()=>$('#detail').close();
$('#copy-entry').onclick=async()=>{try{await navigator.clipboard.writeText(active.prompt+'\n\n'+active.response);toast('Memory copied.');}catch(error){showError(error);}};
$('#delete-entry').onclick=async()=>{if(!active||!confirm('Delete this selected memory from your diary? This cannot be undone.'))return;try{await api('/api/conversations/'+active.id,{method:'DELETE'});if(typeof workflowInvalidate==='function')workflowInvalidate();$('#detail').close();lastRender='';await refresh();toast('Memory deleted.');}catch(error){showError(error);}};
$('#about-button').onclick=()=>{setMenu(false);$('#about').showModal();};$('#close-about').onclick=()=>$('#about').close();
$('#download-day').onclick=()=>{const lines=['# '+prettyDay(selectedDay),''];if(diary.note)lines.push('## A note to myself','',diary.note,'');for(const row of [...diary.entries].reverse())lines.push('## '+(names[row.provider]||'Conversation'),'','### You',row.prompt,'','### The reply',row.response,'');download(lines.join('\n'),'my-diary-'+selectedDay+'.md');};
window.addEventListener('beforeunload',event=>{if(noteDirty){event.preventDefault();event.returnValue='';}});
document.addEventListener('keydown',event=>{if(event.key==='Escape')setMenu(false);if(event.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)&&!$('#detail').open&&!$('#about').open&&!$('#notes-sheet').open&&!$('#snippet-editor').open){event.preventDefault();$('#search').focus();}});
let measuredWidth=0;new ResizeObserver(entries=>{syncMenuAccessibility();const width=entries[0].contentRect.width;if(Math.abs(width-measuredWidth)<2)return;measuredWidth=width;lastRender='';if(view==='review')renderReview();else if(view!=='tools')renderTimeline(visibleRows);}).observe($('.main-column'));
heading();refresh();setInterval(()=>{if(!document.hidden)refresh();},3000);


// Local memory tools remain optional; the diary does not require a model runtime.
let localState=null,indexing=false;
function modelOptions(select,models,current){
  select.replaceChildren(node('option','','Disabled'));select.firstChild.value='';
  for(const name of models){const option=node('option','',name==='builtin:bge'?'Small local search · CPU':name);option.value=name;select.append(option);}
  if(current&&!models.includes(current)){const option=node('option','',current+' (not found)');option.value=current;select.append(option);}
  select.value=current||'';
}
async function updateOverview(){
  try{const data=await api('/api/memory/overview'),box=$('#library-overview');box.replaceChildren();
    const space=bytes=>bytes>=1073741824?(bytes/1073741824).toFixed(1)+' GB':(bytes/1048576).toFixed(1)+' MB';
    for(const [value,label] of [[data.conversations,'conversations'],[data.favorites,data.favorites===1?'favorite':'favorites']]){const item=node('div');item.append(node('strong','',value),node('span','',label));box.append(item);}
    const storage=node('div','library-storage');storage.append(node('strong','',space(data.bytes)),node('span','','used /'),node('strong','',Number.isFinite(data.free_bytes)?space(data.free_bytes):'Unavailable'),node('span','','free'));
    storage.title='Diary database size / available space on the disk containing your diary. Wirebrain has no fixed storage quota.';box.append(storage);
    const selected=$('#collection-filter').value;$('#collection-filter').replaceChildren(node('option','','All collections'));$('#collection-filter').firstChild.value='';
    for(const project of data.projects){const option=node('option','',`${project.name} (${project.count})`);option.value=project.name;$('#collection-filter').append(option);}$('#collection-filter').value=selected;updateWorkflowCollections(data.projects);if(typeof updateReflectCollections==='function')updateReflectCollections(data.projects);
  }catch(error){showError(error);}
}
async function loadLocal(){
  $('#local-status').textContent='Checking this computer…';
  try{localState=await api('/api/local/status');const config=localState.settings;
    $('#writing-provider').value=config.writing_provider||'ollama';
    modelOptions($('#embedding-model'),localState.native_available?['builtin:bge',...localState.models]:localState.models,config.embedding_model);modelOptions($('#chat-model'),localState.models,config.writing_provider==='chatgpt'?'':config.chat_model);
    $('#writing-model-field').hidden=config.writing_provider==='chatgpt';
    $('#chatgpt-connection-status').textContent=localState.chatgpt?.message||'Codex CLI is not available.';
    $('#prepare-search').disabled=!localState.native_available;$('#prepare-status').textContent=localState.native_available?'Small local search engine is installed. Enable it to download its model.':'Use the source launcher with local-search support, or install the optional [memory] dependency.';
    if(config.embedding_model==='builtin:bge')$('#prepare-status').textContent='Local search is enabled on this computer.';
    $('#local-status').textContent=localState.available?'Ollama is available on this computer.':config.embedding_model==='builtin:bge'?'Local search is enabled. A writing model is optional; connect Ollama for written answers and reflections.':'The diary is ready. Enable small local search below, or connect Ollama for written answers.';
    if(config.writing_provider==='chatgpt')$('#local-status').textContent='ChatGPT testing mode is selected. Selected excerpts are sent to OpenAI; keyword and embedding search stay on this computer.';
    $('#setup-capture-status').textContent=stats.capture?.running?'Your recorder is running. Send a test message in each supported app and check that the complete reply appears.':`Recording is paused. Automatic setup supports Windows and macOS; macOS capture still needs real-device verification.`;
    const quotedHome="'"+localState.home.replaceAll("'",localState.platform==='Windows'?"''":"'\\''")+"'";
    $('#setup-command').textContent='wirebrain --home '+quotedHome+' capture --install-ca --system-proxy';
  }catch(error){$('#local-status').textContent=error.message;}
}
$('#local-setup').onclick=()=>{setMenu(false);$('#local-dialog').showModal();loadLocal();};
$('#close-local').onclick=()=>$('#local-dialog').close();$('#refresh-models').onclick=loadLocal;
$('#save-local').onclick=async()=>{const button=$('#save-local');button.disabled=true;try{const config=await post('/api/local/settings',{embedding_model:$('#embedding-model').value,chat_model:$('#chat-model').value,writing_provider:$('#writing-provider').value});if(localState)localState.settings=config;$('#index-status').textContent='Settings saved. Update the memory index to enable meaning search.';}catch(error){$('#index-status').textContent=error.message;}finally{button.disabled=false;}};
$('#writing-provider').onchange=()=>{$('#writing-model-field').hidden=$('#writing-provider').value==='chatgpt';};
$('#test-chatgpt').onclick=async()=>{const button=$('#test-chatgpt');button.disabled=true;$('#chatgpt-connection-status').textContent='Testing ChatGPT sign-in…';try{const result=await post('/api/chatgpt/test',{});$('#chatgpt-connection-status').textContent='Connected. ChatGPT replied: '+result.reply;}catch(error){$('#chatgpt-connection-status').textContent=error.message;}finally{button.disabled=false;}};
$('#index-memories').onclick=async()=>{if(indexing)return;indexing=true;$('#index-memories').disabled=true;$('#index-status').textContent='Loading your local search model and indexing memories…';let completed=0;try{let result;do{result=await post('/api/local/index',{});completed+=result.indexed;$('#index-status').textContent=`Indexed ${completed} passages; ${result.remaining} remaining…`;}while(result.remaining);$('#index-status').textContent=`Your memory index is up to date. ${completed} passages updated.`;}catch(error){$('#index-status').textContent=error.message;}finally{indexing=false;$('#index-memories').disabled=false;}};
$('#search-mode').onchange=()=>{searchMode=$('#search-mode').value;revision++;lastRender='';refresh();};
$('#collection-filter').onchange=()=>{collectionFilter=$('#collection-filter').value;revision++;lastRender='';refresh();};
$('#conversation-sort').onchange=()=>{sortOrder=$('#conversation-sort').value;lastRender='';if(view==='memories'&&memoryPageTab!=='conversations')loadPersonalMemory();else renderTimeline(visibleRows);};
$('#save-collection').onclick=async()=>{if(!active)return;const button=$('#save-collection');button.disabled=true;try{const result=await post('/api/memory/collection',{id:active.id,name:$('#collection-name').value});active.project=result.name;toast('Conversation added to '+result.name);lastRender='';await updateOverview();await refresh();}catch(error){showError(error);}finally{button.disabled=false;}};
function sourceCards(rows){const target=$('#answer-sources');target.replaceChildren();rows.forEach((row,i)=>{const button=node('button','source-card');button.append(node('strong','',`[${i+1}] ${shortText(row.thread_title||row.prompt,100)}`),node('span','',`${names[row.provider]||row.provider} · ${new Date(row.created).toLocaleDateString()} · ${row.project}`),node('p','',shortText(row.response,220)));button.onclick=()=>{ $('#memory-answer').close();openMemory(row);};target.append(button);});}
$('#ask-memory').onclick=()=>{$('#answer-title').textContent='Ask your memories.';$('#ask-form').hidden=false;$('#answer-body').replaceChildren();$('#answer-sources').replaceChildren();$('#memory-answer').showModal();$('#memory-question').focus();};
$('#close-answer').onclick=()=>$('#memory-answer').close();
$('#ask-form').onsubmit=async event=>{event.preventDefault();const button=$('#submit-question');button.disabled=true;$('#answer-body').textContent='Looking through your memories…';$('#answer-sources').replaceChildren();try{const result=await post('/api/ask',{query:$('#memory-question').value,mode:searchMode,provider,project:collectionFilter,generate:$('#generate-answer').checked,use_personal_memory:true,memory_only:view==='memories'&&memoryPageTab!=='conversations'});$('#answer-body').replaceChildren(node('p','muted',result.generated?(result.writing_provider==='chatgpt'?'Generated with ChatGPT sign-in (testing). Check the sources below.':'Generated locally. Check the original sources below.'):'Original sources from your diary.'),renderText(result.answer));for(const [i,memory] of (result.memories||[]).entries())$('#answer-body').append(node('p','muted',`[M${i+1}] ${memory.text}`));if(result.unindexed)$('#answer-body').append(node('p','muted',`${result.unindexed} memories need indexing in Local setup.`));sourceCards(result.sources);}catch(error){$('#answer-body').textContent=error.message;}finally{button.disabled=false;}};
async function reflectWithAI(){
  $('#answer-title').textContent='A reflection on your day.';$('#ask-form').hidden=true;$('#answer-body').textContent='Reflecting on the captured conversations…';$('#answer-sources').replaceChildren();$('#memory-answer').showModal();
  try{const result=await post('/api/memory/reflect',{day:selectedDay,offset:-asDate(selectedDay).getTimezoneOffset(),provider:$('#reflect-provider').value,project:$('#reflect-project').value});$('#answer-body').replaceChildren(node('p','muted',(result.writing_provider==='chatgpt'?'Generated with ChatGPT sign-in (testing)':'Generated locally')+' from up to eight recorded moments and your note. Suggestions are optional; this is not a prediction of your day.'),renderText(result.answer));sourceCards(result.sources);}catch(error){$('#answer-body').textContent=error.message;}
}
$('#import-history').onchange=async()=>{const file=$('#import-history').files[0];if(!file)return;if(file.size>7*1024*1024){$('#import-status').textContent='Choose a JSON file smaller than 7 MB.';return;}$('#import-history').disabled=true;try{const result=await post('/api/memory/import',{data:JSON.parse(await file.text())});$('#import-status').textContent=`Imported ${result.imported} moments; skipped ${result.skipped} duplicates. Update the local index to search them by meaning.`;lastRender='';await updateOverview();await refresh();}catch(error){$('#import-status').textContent=error.message;}finally{$('#import-history').disabled=false;$('#import-history').value='';}};
updateOverview();setInterval(()=>{if(!document.hidden)updateOverview();},15000);

$('#prepare-search').onclick=async()=>{const button=$('#prepare-search');button.disabled=true;$('#prepare-status').textContent='Downloading and preparing the small search model. This first step needs internet; your conversations stay on this computer.';try{await post('/api/local/prepare',{});await loadLocal();$('#prepare-status').textContent='Local search is enabled. Update the memory index below to search your existing conversations.';}catch(error){$('#prepare-status').textContent=error.message;}finally{button.disabled=false;}};

function updateWorkflowCollections(projects){
  const select=$('#workflow-project'),chosen=select.value,signature=JSON.stringify(projects.map(p=>p.name));
  if(select.dataset.projects===signature)return;select.dataset.projects=signature;
  select.replaceChildren(node('option','','All collections'));select.firstChild.value='';
  for(const project of projects){const option=node('option','',project.name);option.value=project.name;select.append(option);}
  select.value=chosen;
  if(chosen&&!projects.some(p=>p.name===chosen)&&typeof workflowInvalidate==='function')workflowInvalidate();
}
