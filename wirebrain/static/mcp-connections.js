'use strict';
let mcpRemoteBusy=false,mcpRemoteLoaded=false;
async function remoteMcp(action='status',extra={}){
  if(mcpRemoteBusy)return;
  mcpRemoteBusy=true;
  $('#remote-mcp-status').textContent='Checking connection…';
  try{
    const result=await post('/api/workflows/mcp-http',{action,...extra});
    if(action==='issue-token'){
      $('#remote-mcp-secret').textContent=JSON.stringify(result.connection,null,2);$('#remote-mcp-secret').hidden=false;$('#remote-mcp-copy-secret').hidden=false;
      $('#remote-mcp-status').textContent='HTTP client configuration created. Copy it now; the token is shown only here and expires in 30 days. Revoke the connection below to disable it.';
    }else{
      mcpRemoteLoaded=true;
      if(document.activeElement!==$('#remote-mcp-public-url'))$('#remote-mcp-public-url').value=result.public_url;
      if(document.activeElement!==$('#remote-mcp-port'))$('#remote-mcp-port').value=result.port;
      $('#remote-mcp-endpoint').textContent=result.endpoint;
      $('#remote-mcp-status').textContent=result.running?(result.public_url?'MCP is running locally with this configured HTTPS address. A working HTTPS tunnel is still required.':'MCP is running locally. Coding clients can connect now; web assistants need an HTTPS tunnel later.'):'Remote MCP is stopped. Local stdio connections still work.';
      $('#remote-mcp-stop').disabled=!result.running;$('#remote-mcp-token').disabled=!result.running;
      const pending=$('#remote-mcp-pending');pending.replaceChildren();
      for(const request of result.pending){
        const card=node('article','tool-turn');card.append(node('h3','',`${request.name} · ${request.pairing}`),node('p','muted','Client-supplied name. Match this code with the assistant’s connection window.'),node('p','muted','Redirect: '+request.redirect));
        const actions=node('div','workflow-actions');
        const project=$('#workflow-project').value;
        const approve=node('button','solid-button','Approve: '+(project||'all collections'));
        approve.onclick=()=>remoteMcp('approve',{id:request.id,project});
        const deny=node('button','quiet-button','Reject');deny.onclick=()=>remoteMcp('reject',{id:request.id});actions.append(approve,deny);card.append(actions);pending.append(card);
      }
      if(!result.pending.length)pending.append(node('p','muted','No connections awaiting approval.'));
      const connections=$('#remote-mcp-connections');connections.replaceChildren();
      for(const connection of result.connections){const item=node('article','tool-turn');item.append(node('strong','',connection.name),node('p','muted',`${connection.project||'All collections'} · Expires ${new Date(connection.expires*1000).toLocaleDateString()}`));const button=node('button','quiet-button','Revoke access');button.onclick=()=>remoteMcp('revoke',{id:connection.id});item.append(button);connections.append(item);}
      if(!result.connections.length)connections.append(node('p','muted','No active HTTP connections.'));
      if(['stop','start','revoke'].includes(action))clearRemoteMcpSecret();
    }
  }catch(error){$('#remote-mcp-status').textContent=error.message;}
  finally{mcpRemoteBusy=false;}
}
function clearRemoteMcpSecret(){$('#remote-mcp-secret').textContent='';$('#remote-mcp-secret').hidden=true;$('#remote-mcp-copy-secret').hidden=true;}
function loadMcpConnections(){if(!mcpRemoteLoaded)remoteMcp();}
$('#remote-mcp-start').onclick=()=>remoteMcp('start',{port:Number($('#remote-mcp-port').value),public_url:$('#remote-mcp-public-url').value.trim()});
$('#remote-mcp-stop').onclick=()=>remoteMcp('stop');
$('#remote-mcp-refresh').onclick=()=>remoteMcp();
$('#remote-mcp-token').onclick=()=>remoteMcp('issue-token',{name:$('#remote-mcp-name').value.trim()||'Coding assistant',project:$('#workflow-project').value});
$('#remote-mcp-copy-endpoint').onclick=()=>workflowCopy($('#remote-mcp-endpoint').textContent);
$('#remote-mcp-copy-secret').onclick=()=>workflowCopy($('#remote-mcp-secret').textContent);
$('#remote-mcp-hide-secret').onclick=clearRemoteMcpSecret;
