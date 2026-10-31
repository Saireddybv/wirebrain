"""Read-only MCP stdio, protocol version 2025-06-18 (legacy initialize lifecycle)."""
from .prompting import render_prompt
import json
import sys

FILTERS = {
    'project': {'type':'string','description':'Exact collection name; memories from other collections are excluded.'},
    'provider': {'type':'string','description':'Optional app: chatgpt, claude, gemini, grok, meta, openai, anthropic, or groq.'},
    'date_from': {'type':'string','description':'Inclusive local date, YYYY-MM-DD; provide date_to too.'},
    'date_to': {'type':'string','description':'Inclusive local date, YYYY-MM-DD; provide date_from too.'},
    'offset': {'type':'integer','minimum':-840,'maximum':840,'description':'Local timezone offset in minutes east of UTC.'},
}
TOOLS = [
    {'name':'list_conversations','description':render_prompt('mcp.tools.list_conversations'),
     'inputSchema':{'type':'object','properties':{**FILTERS,'query':{'type':'string'},'lookback_minutes':{'type':'integer','minimum':0,'maximum':525600},'cursor':{'type':'integer','minimum':0,'maximum':10000},'limit':{'type':'integer','minimum':1,'maximum':50}},'additionalProperties':False}},
    {'name':'read_conversation','description':render_prompt('mcp.tools.read_conversation'),
     'inputSchema':{'type':'object','properties':{**FILTERS,'exchange_id':{'type':'string'},'cursor':{'type':'integer','minimum':0,'maximum':10000},'limit':{'type':'integer','minimum':1,'maximum':10}},'required':['exchange_id'],'additionalProperties':False}},
    {'name':'conversation_handoff','description':render_prompt('mcp.tools.conversation_handoff'),
     'inputSchema':{'type':'object','properties':{**FILTERS,'exchange_id':{'type':'string'}},'required':['exchange_id'],'additionalProperties':False}},
    {'name':'search_personal_memory','description':render_prompt('mcp.tools.search_personal_memory'),
     'inputSchema':{'type':'object','properties':{'query':{'type':'string'},'project':{'type':'string'},'provider':{'type':'string'},'mode':{'type':'string','enum':['keyword','semantic'],'default':'keyword'}},'required':['query'],'additionalProperties':False}},
    {'name':'search_memory','description':render_prompt('mcp.tools.search_memory'),
     'inputSchema':{'type':'object','properties':{**FILTERS,'query':{'type':'string'},'mode':{'type':'string','enum':['keyword','semantic'],'default':'keyword'}},'required':['query'],'additionalProperties':False}},
    {'name':'recent_memory','description':render_prompt('mcp.tools.recent_memory'),
     'inputSchema':{'type':'object','properties':FILTERS,'additionalProperties':False}},
    {'name':'read_memory','description':render_prompt('mcp.tools.read_memory'),
     'inputSchema':{'type':'object','properties':{'exchange_id':{'type':'string'},'field':{'type':'string','enum':['prompt','response'],'default':'response'},'start':{'type':'integer','minimum':0,'default':0},'length':{'type':'integer','minimum':1,'maximum':12000,'default':6000}},'required':['exchange_id'],'additionalProperties':False}},
    {'name':'context_handoff','description':render_prompt('mcp.tools.context_handoff'),
     'inputSchema':{'type':'object','properties':FILTERS,'additionalProperties':False}},
]

for tool in TOOLS:
    tool['annotations'] = {'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False}


def excerpt(row):
    return {**row,'prompt':row['prompt'][:1600],'response':row['response'][:2400],
            'excerpted':len(row['prompt'])>1600 or len(row['response'])>2400}


def dispatch(store, msg, project=""):

    method, params = msg.get("method"), msg.get("params", {})
    if "id" not in msg:
        return None
    result = {}
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "wirebrain", "version": "0.1.0"},
                  "instructions": render_prompt('mcp.context')}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        try:
            if not isinstance(args,dict): raise ValueError('Expected tool arguments')
            tool = next((t for t in TOOLS if t['name']==name),None)
            if not tool or set(args)-set(tool['inputSchema']['properties']): raise ValueError('Unknown tool or invalid arguments')
            if project:
                if args.get('project',project) != project: raise ValueError('This MCP server is restricted to its configured collection')
                args = {**args,'project':project}
            from .workflows import scope, report
            filters = scope(args)
            if name in ('list_conversations','read_conversation','conversation_handoff'):
                from . import memory_tools
                data = getattr(memory_tools,name)(store,args)
            elif name == 'read_memory':
                ident, field = args.get('exchange_id'), args.get('field','response')
                start, length = args.get('start',0), args.get('length',6000)
                if not isinstance(ident,str) or field not in ('prompt','response') or any(isinstance(n,bool) or not isinstance(n,int) for n in (start,length)) or start<0 or not 1<=length<=12000:
                    raise ValueError('Choose a memory, text field, and valid page bounds')
                found = store.list(exchange_id=ident,project=project,limit=1)
                if not found: raise ValueError('Memory not found in this server scope')
                row = found[0]
                data = {'id':row['id'],'provider':row['provider'],'project':row['project'],'status':row['status'],
                        'field':field,'text':row[field][start:start+length],'start':start,
                        'next_start':start+length if start+length<len(row[field]) else None,'total_characters':len(row[field])}
            elif name == 'search_personal_memory':
                from .personal_memory import retrieve
                data = retrieve(store,args.get('query'),filters['provider'],filters['project'],args.get('mode','keyword'))
            elif name == 'search_memory':
                from .intelligence import search
                data = search(store,args.get('query'),args.get('mode','keyword'),filters['provider'],filters['project'],limit=20,
                              date_from=filters['date_from'],date_to=filters['date_to'],offset=filters['day_offset'])['rows']
            elif name == 'recent_memory': data = store.list(limit=20,**filters)
            else:
                data = report(store,{**args,'kind':'handoff','generate':False})
                data['sources'] = [excerpt(row) for row in data['sources']]
            if name in ('search_memory','recent_memory'): data = [excerpt(row) for row in data]
        except (ValueError,TypeError) as exc:
            return {'jsonrpc':'2.0','id':msg['id'],'result':{'isError':True,'content':[{'type':'text','text':str(exc)}]}}
        result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
    elif method != "ping":
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": msg["id"], "result": result}


def run(store, project=""):
    for line in sys.stdin:
        try:
            msg = json.loads(line)
            if not isinstance(msg, dict): raise ValueError()
            result = dispatch(store, msg, project)
        except (ValueError, TypeError, AttributeError):
            result = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid request"}}
        if result is not None:
            print(json.dumps(result, ensure_ascii=False), flush=True)
