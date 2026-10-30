'use strict';
let workflowRevision=0,workflowReport=null,workflowSnippets=[];
function workflowScope(){return {date_from:$('#workflow-from').value,date_to:$('#workflow-to').value,provider:$('#workflow-provider').value,project:$('#workflow-project').value,offset:-asDate($('#workflow-to').value||today()).getTimezoneOffset()};}
function workflowPeriod(period){
  const end=asDate(today()),start=asDate(today());
  if(period==='yesterday'){end.setDate(end.getDate()-1);start.setDate(start.getDate()-1);}
  else start.setDate(start.getDate()-(period==='month'?29:period==='week'?6:0));
  $('#workflow-from').value=localDay(start);$('#workflow-to').value=localDay(end);workflowInvalidate();
}
function workflowInvalidate(){
  workflowRevision++;workflowReport=null;workflowSnippets=[];
  $('#report-actions').hidden=true;
  for(const id of ['learning-topics','report-result','report-sources','snippet-results','comparison-result','usage-results','mcp-config'])$('#'+id).replaceChildren();
  for(const id of ['compare-left','compare-right']){$('#'+id).replaceChildren(node('option','','Choose a moment'));$('#'+id).firstChild.value='';}
  $('#workflow-status').textContent='Choose a tool to work with this selection.';
}
async function workflowRequest(button,message,path,payload,render){
  const version=++workflowRevision;button.disabled=true;$('#workflow-status').textContent=message;
  try{const result=await post(path,payload);if(version!==workflowRevision)return;render(result);}
  catch(error){if(version===workflowRevision)$('#workflow-status').textContent=error.message;}
  finally{button.disabled=false;}
}
function workflowTab(name,focus=false){
  const tabs=[...document.querySelectorAll('[data-workflow]')];
  for(const tab of tabs){const active=tab.dataset.workflow===name;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;$('#panel-'+tab.dataset.workflow).hidden=!active;if(active&&focus)tab.focus();}
}
for(const tab of document.querySelectorAll('[data-workflow]')){
  tab.onclick=()=>workflowTab(tab.dataset.workflow);
  tab.onkeydown=event=>{const tabs=[...document.querySelectorAll('[data-workflow]')];let index=tabs.indexOf(tab);if(event.key==='ArrowRight')index=(index+1)%tabs.length;else if(event.key==='ArrowLeft')index=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')index=0;else if(event.key==='End')index=tabs.length-1;else return;event.preventDefault();workflowTab(tabs[index].dataset.workflow,true);};
}
for(const button of document.querySelectorAll('[data-period]'))button.onclick=()=>workflowPeriod(button.dataset.period);
for(const id of ['workflow-from','workflow-to','workflow-provider','workflow-project'])$('#'+id).onchange=workflowInvalidate;
function workflowEvidence(target,rows){
  target.replaceChildren();if(!rows.length)return;
  const details=node('details','workflow-source-list'),list=node('div');details.append(node('summary','',`Original sources (${rows.length} shown)`),list);target.append(details);
  rows.forEach((row,index)=>{const button=node('button','source-card');button.append(node('strong','',`[${index+1}] ${shortText(row.thread_title||row.prompt,100)}`),node('span','',`${names[row.provider]||row.provider} · ${new Date(row.created).toLocaleString()} · ${row.project}`));button.onclick=()=>openMemory(row);list.append(button);});
}
$('#report-form').onsubmit=event=>{
  event.preventDefault();workflowReport=null;$('#report-actions').hidden=true;$('#report-result').replaceChildren();$('#report-sources').replaceChildren();$('#learning-topics').replaceChildren();
  workflowRequest($('#create-report'),'Preparing your report…','/api/workflows/report',{...workflowScope(),kind:$('#report-kind').value,generate:$('#report-generate').checked},result=>{
    workflowReport=result;$('#report-actions').hidden=false;
    $('#workflow-status').textContent=`${result.total} captured moments. ${result.generated?`Local draft based on ${result.source_count} selected moments; verify the sources.`:`Original-source report; ${result.source_count} moments included. No AI model was used.`}${result.notes_included?' Personal notes included.':''}`;
    if(result.topics.length){const heading=node('h3','','Topics you returned to'),grid=node('div','learning-grid');$('#learning-topics').append(heading,grid);for(const topic of result.topics){const card=node('article','learning-card');card.append(node('strong','',topic.topic),node('span','',`${topic.count} prompts · ${topic.days.length} day${topic.days.length===1?'':'s'}`),node('p','',topic.suggestion));const button=node('button','text-button','Revisit a source ↗');button.onclick=async()=>{try{const rows=await api('/api/thread?exchange='+encodeURIComponent(topic.sources[0]));const row=rows.find(r=>r.id===topic.sources[0]);if(row)openMemory(row);else toast('That source is no longer available.');}catch(error){$('#workflow-status').textContent=error.message;}};card.append(button);grid.append(card);}}
    $('#report-result').replaceChildren(renderText(result.body.slice(0,60000)));
    if(result.body.length>60000)$('#report-result').prepend(node('p','muted','Preview shortened. Copy or download the complete report.'));
    workflowEvidence($('#report-sources'),result.sources);
  });
};
async function workflowCopy(text){try{await navigator.clipboard.writeText(text);toast('Copied.');}catch{toast('Copy is unavailable here. Select the text or download a copy.');}}
$('#copy-report').onclick=()=>{if(workflowReport)workflowCopy(workflowReport.body);};
$('#export-report').onclick=()=>{if(workflowReport)download(workflowReport.body,workflowReport.filename);};
$('#make-mcp-config').onclick=()=>workflowRequest($('#make-mcp-config'),'Preparing your coding-assistant connection…','/api/workflows/mcp-config',workflowScope(),result=>{$('#mcp-config').textContent=JSON.stringify(result,null,2);$('#workflow-status').textContent=$('#workflow-project').value?'Connection restricted to '+$('#workflow-project').value+'.':'This connection can read all your recorded collections.';});
function workflowFilteredSnippets(){const query=$('#snippet-query').value.toLowerCase();return workflowSnippets.filter(item=>(!$('#saved-snippets-only').checked||item.saved)&&(!query||[item.title,item.content,item.language].join(' ').toLowerCase().includes(query)));}
function workflowRenderSnippets(){
  const target=$('#snippet-results'),items=workflowFilteredSnippets();target.replaceChildren();
  if(!items.length){empty(target,'No snippets in this selection.','Choose another period, or keep an excerpt from a conversation.');return;}
  for(const item of items){
    const card=node('article','snippet-card'),actions=node('div','workflow-actions');card.append(node('h3','',item.title),node('p','muted',`${names[item.provider]||item.provider} · ${item.project} · ${item.language||'text'}${item.saved?' · Kept':''}`),node('pre','snippet-code',item.content));
    const copy=node('button','quiet-button','Copy'),source=node('button','quiet-button','Open source ↗');copy.onclick=()=>workflowCopy(item.content);source.onclick=()=>openMemory(item.source);actions.append(copy,source);
    const keep=node('button','quiet-button',item.saved?'Remove kept copy':'Keep snippet');keep.onclick=async()=>{
      if(item.saved){if(!confirm('Remove this kept snippet? Its original conversation will remain.'))return;keep.disabled=true;try{await post('/api/workflows/remove-snippet',{id:item.id});workflowSnippets=workflowSnippets.filter(row=>row.id!==item.id);workflowRenderSnippets();toast('Kept copy removed.');}catch(error){$('#workflow-status').textContent=error.message;}finally{keep.disabled=false;}}
      else workflowOpenSnippet(item.source,item.content,item.language,item.title);
    };actions.append(keep);card.append(actions);target.append(card);
  }
}
$('#load-snippets').onclick=()=>workflowRequest($('#load-snippets'),'Looking for reusable snippets…','/api/workflows/snippets',workflowScope(),result=>{workflowSnippets=result.snippets;workflowRenderSnippets();$('#workflow-status').textContent=`${result.snippets.length} snippets in this selection (up to 500 shown).`;});
$('#snippet-query').oninput=workflowRenderSnippets;$('#saved-snippets-only').onchange=workflowRenderSnippets;
$('#export-snippets').onclick=()=>{const snippets=workflowFilteredSnippets();if(!snippets.length){toast('Find or keep a snippet first.');return;}const lines=['# My snippet vault',''];for(const item of snippets)lines.push('## '+item.title,'',`${item.provider} · ${item.project} · Source: ${item.exchange_id}`,'',item.content,'');download(lines.join('\n'),'wirebrain-snippets.md');};
function workflowOpenSnippet(row,content,language='',title=''){
  $('#snippet-source').value=row.id;$('#snippet-name').value=title||shortText(row.thread_title||row.prompt,120)||'A useful snippet';$('#snippet-language').value=language;$('#snippet-content').value=content.slice(0,20000);$('#snippet-save-status').textContent='Kept locally with a link to the original conversation.';$('#snippet-editor').showModal();$('#snippet-name').focus();
}
$('#keep-excerpt').onclick=()=>{if(!active)return;const block=(active.response||'').match(/```([^\n`]*)\n([\s\S]*?)```/);workflowOpenSnippet(active,block?block[2]:(active.response||active.prompt),block?block[1]:'text');};
$('#close-snippet').onclick=()=>$('#snippet-editor').close();
$('#snippet-form').onsubmit=async event=>{event.preventDefault();const button=$('#save-snippet');button.disabled=true;try{await post('/api/workflows/save-snippet',{exchange_id:$('#snippet-source').value,title:$('#snippet-name').value,language:$('#snippet-language').value,content:$('#snippet-content').value});$('#snippet-editor').close();toast('Snippet kept in your vault.');if(view==='tools'&&!$('#panel-snippets').hidden){const version=workflowRevision;try{const refreshed=await post('/api/workflows/snippets',workflowScope());if(version===workflowRevision){workflowSnippets=refreshed.snippets;workflowRenderSnippets();}}catch{ $('#workflow-status').textContent='Snippet kept. Refresh the vault to see the latest selection.';}}}catch(error){$('#snippet-save-status').textContent=error.message;}finally{button.disabled=false;}};
$('#load-comparison').onclick=()=>workflowRequest($('#load-comparison'),'Loading captured moments…','/api/workflows/candidates',workflowScope(),result=>{
  for(const id of ['compare-left','compare-right']){const select=$('#'+id);select.replaceChildren(node('option','','Choose a moment'));select.firstChild.value='';for(const row of result.rows){const option=node('option','',`${new Date(row.created).toLocaleString()} · ${names[row.provider]||row.provider} · ${row.model} · ${shortText(row.prompt,65)}`);option.value=row.id;select.append(option);}}
  $('#workflow-status').textContent=`${result.rows.length} moments available. Choose two to compare.`;
});
$('#compare-memories').onclick=()=>workflowRequest($('#compare-memories'),'Comparing the recorded text…','/api/workflows/compare',{ids:[$('#compare-left').value,$('#compare-right').value]},result=>{
  const target=$('#comparison-result'),columns=node('div','comparison-columns');target.replaceChildren(columns);
  for(const [label,row] of [['First selection',result.left],['Second selection',result.right]]){const card=node('article','comparison-card');card.append(node('h3','',label),node('p','muted',`${names[row.provider]||row.provider} · ${row.model} · ${new Date(row.created).toLocaleString()}`),node('h4','','Prompt'),node('pre','',row.prompt),node('h4','','Reply'),node('pre','',row.response));const source=node('button','quiet-button','Open original memory ↗');source.onclick=()=>openMemory(row);card.append(source);columns.append(card);}
  for(const field of ['prompt','response']){const details=node('details','comparison-diff');details.append(node('summary','',field==='prompt'?'Prompt changes':'Reply changes'),node('pre','',result[field+'_diff']||'No text changes.'));target.append(details);}
  $('#workflow-status').textContent='Recorded text compared. Model names describe the captured requests; no quality ranking is inferred.';
});
$('#load-usage').onclick=()=>workflowRequest($('#load-usage'),'Reading provider-reported usage…','/api/workflows/usage',workflowScope(),result=>{
  const target=$('#usage-results');target.replaceChildren(node('p','workflow-hint',result.notice));
  const summary=node('div','library-overview');for(const [value,label] of [[result.moments,'captured moments'],[result.reported,'with reported usage'],[result.input_reports?result.input_tokens.toLocaleString():'Unknown','reported input tokens'],[result.output_reports?result.output_tokens.toLocaleString():'Unknown','reported output tokens']]){const item=node('div');item.append(node('strong','',value),node('span','',label));summary.append(item);}target.append(summary);
  if(!result.groups.length){empty(target,'No activity in this selection.','Choose another date range or collection.');return;}
  const wrap=node('div','usage-table-wrap'),table=node('table','usage-table'),head=node('thead'),heading=node('tr');for(const label of ['App','Model','Collection','Usage reported','Input','Output'])heading.append(node('th','',label));head.append(heading);table.append(head);const body=node('tbody');for(const group of result.groups){const tr=node('tr');for(const value of [names[group.provider]||group.provider,group.model,group.project,`${group.reported} / ${group.moments}${group.samples?' · '+group.samples+' samples excluded':''}`,group.input_reports?group.input_tokens.toLocaleString():'Unknown',group.output_reports?group.output_tokens.toLocaleString():'Unknown'])tr.append(node('td','',value));body.append(tr);}table.append(body);wrap.append(table);target.append(wrap);$('#workflow-status').textContent='Only reported token fields are counted. No bill or subscription cost is estimated.';
});
workflowPeriod('week');
