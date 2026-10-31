'use strict';
let toolContext=null,toolConversationCursor=null,toolTurnCursor=null;
function resetToolContext(){
  toolContext=null;toolTurnCursor=null;
  for(const id of ['tool-context-preview','tool-context-actions','tool-more-turns'])$('#'+id).hidden=true;
  $('#tool-conversation-preview').replaceChildren();$('#tool-context-preview').textContent='';$('#tool-context-coverage').textContent='';
}
function resetConversationTools(){
  resetToolContext();toolConversationCursor=null;
  const select=$('#tool-conversation');select.replaceChildren(node('option','','Find conversations to choose one'));select.firstChild.value='';
  $('#tool-read-conversation').disabled=true;$('#tool-prepare-handoff').disabled=true;
  $('#tool-more-conversations').hidden=true;$('#copy-mcp-config').hidden=true;
}
function findToolConversations(more=false){
  if(!more){resetConversationTools();$('#tool-conversation').replaceChildren(node('option','','Choose a conversation'));$('#tool-conversation').firstChild.value='';}
  const button=$('#'+(more?'tool-more-conversations':'tool-find-conversations'));
  workflowRequest(button,'Finding captured conversations…','/api/workflows/list-conversations',{...workflowScope(),query:$('#tool-conversation-query').value,cursor:more?toolConversationCursor:0,limit:30},result=>{
    for(const row of result.conversations){const option=node('option','',`${names[row.provider]||row.provider} · ${shortText(row.title,90)} · ${row.moments} moments`);option.value=row.exchange_id;$('#tool-conversation').append(option);}
    toolConversationCursor=result.next_cursor;$('#tool-more-conversations').hidden=result.next_cursor===null;
    $('#workflow-status').textContent=`${result.total} conversations in this selection. Choose one to read or continue elsewhere.`;
  });
}
$('#tool-find-conversations').onclick=()=>findToolConversations();
$('#tool-more-conversations').onclick=()=>findToolConversations(true);
$('#tool-conversation-query').oninput=()=>{workflowRevision++;resetConversationTools();};
$('#tool-conversation-query').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();findToolConversations();}};
$('#tool-conversation').onchange=()=>{workflowRevision++;resetToolContext();const ready=!!$('#tool-conversation').value;$('#tool-read-conversation').disabled=!ready;$('#tool-prepare-handoff').disabled=!ready;};
function readToolConversation(more=false){
  if(!$('#tool-conversation').value)return;
  if(!more)$('#tool-conversation-preview').replaceChildren();
  workflowRequest($('#'+(more?'tool-more-turns':'tool-read-conversation')),'Reading captured dialogue…','/api/workflows/read-conversation',{...workflowScope(),exchange_id:$('#tool-conversation').value,cursor:more?toolTurnCursor:0,limit:5},result=>{
    for(const row of result.moments){const card=node('details','tool-turn');card.append(node('summary','',`${new Date(row.created).toLocaleString()} · ${shortText(row.prompt,100)}`),node('h3','','You'),node('pre','',row.prompt),node('h3','',names[row.provider]||row.provider),node('pre','',row.response||'(No reply captured)'));if(row.excerpted)card.append(node('p','muted','Long text is excerpted here. Open the original captured moment for its full text.'));const open=node('button','quiet-button','Open captured moment');open.onclick=async()=>{try{const rows=await api('/api/thread?exchange='+encodeURIComponent(row.id));const original=rows.find(item=>item.id===row.id);if(original)openMemory(original);else toast('This moment is no longer available.');}catch(error){toast(error.message);}};card.append(open);$('#tool-conversation-preview').append(card);}
    toolTurnCursor=result.next_cursor;$('#tool-more-turns').hidden=result.next_cursor===null;$('#workflow-status').textContent=`${result.total} captured moments in this conversation and selection. ${result.coverage}`;
  });
}
$('#tool-read-conversation').onclick=()=>readToolConversation();
$('#tool-more-turns').onclick=()=>readToolConversation(true);
$('#tool-prepare-handoff').onclick=()=>{
  if(!$('#tool-conversation').value)return;
  toolContext=null;$('#tool-context-actions').hidden=true;$('#tool-context-preview').hidden=true;
  workflowRequest($('#tool-prepare-handoff'),'Preparing portable context…','/api/workflows/conversation-handoff',{...workflowScope(),exchange_id:$('#tool-conversation').value},result=>{
    toolContext=result;$('#tool-context-preview').textContent=result.body;$('#tool-context-preview').hidden=false;$('#tool-context-actions').hidden=false;
    $('#tool-context-coverage').textContent=`Latest ${result.included} of ${result.total} captured moments. Text limits are marked in the preview. Copy into the app where you want to continue.`;
    $('#workflow-status').textContent='Context is ready for review. No AI model was used and nothing was sent.';
  });
};
$('#tool-copy-context').onclick=()=>{if(toolContext)workflowCopy(toolContext.body);};
$('#tool-download-context').onclick=()=>{if(toolContext)download(toolContext.body,toolContext.filename);};
