import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from wirebrain import chatgpt_gateway as gateway
from wirebrain.intelligence import settings, writing_request
from wirebrain.store import Store
import tempfile


class ChatGPTGatewayTests(unittest.TestCase):
    @patch('wirebrain.chatgpt_gateway.executable', return_value='codex')
    @patch('wirebrain.chatgpt_gateway.subprocess.run')
    def test_status_requires_chatgpt_not_api_key_login(self, run, binary):
        run.return_value=subprocess.CompletedProcess([],0,'','Logged in using an API key')
        self.assertFalse(gateway.status()['connected'])
        run.return_value=subprocess.CompletedProcess([],0,'','Logged in using ChatGPT')
        self.assertTrue(gateway.status()['connected'])

    @patch('wirebrain.chatgpt_gateway.status', return_value={'connected':True})
    @patch('wirebrain.chatgpt_gateway.executable', return_value='codex')
    @patch('wirebrain.chatgpt_gateway.subprocess.run')
    def test_ephemeral_text_only_runner_uses_stdin_and_no_api_keys(self, run, binary, status):
        paths=[]
        def invoke(args,**kwargs):
            self.assertIn('--ephemeral',args)
            self.assertIn('--ignore-user-config',args)
            self.assertEqual(args[args.index('--sandbox')+1],'read-only')
            self.assertNotIn('OPENAI_API_KEY',kwargs['env'])
            self.assertNotIn('CODEX_API_KEY',kwargs['env'])
            self.assertNotIn('private test message',' '.join(args))
            self.assertIn('private test message',kwargs['input'])
            schema_path=Path(args[args.index('--output-schema')+1])
            self.assertTrue(schema_path.is_file());paths.append(schema_path)
            for feature in gateway.DISABLED:self.assertIn(feature,args)
            events=[{'type':'item.completed','item':{'type':'agent_message','text':'{"reply":"hello"}'}},{'type':'turn.completed'}]
            return subprocess.CompletedProcess(args,0,'\n'.join(json.dumps(event) for event in events),'')
        run.side_effect=invoke
        with patch.dict(os.environ,{'OPENAI_API_KEY':'secret-test','CODEX_API_KEY':'secret-test'}):
            response=gateway.chat([{'role':'user','content':'private test message'}],{'type':'object'})
        self.assertEqual(json.loads(response['message']['content']),{'reply':'hello'})
        self.assertFalse(paths[0].exists())

    @patch('wirebrain.chatgpt_gateway.status', return_value={'connected':False})
    @patch('wirebrain.chatgpt_gateway.executable', return_value='codex')
    @patch('wirebrain.chatgpt_gateway.subprocess.run')
    def test_rejects_unsigned_or_api_key_sessions_without_fallback(self, run, binary, status):
        with self.assertRaises(ValueError):gateway.chat([{'role':'user','content':'hello'}])
        run.assert_not_called()

    @patch('wirebrain.chatgpt_gateway.status', return_value={'connected':True})
    @patch('wirebrain.chatgpt_gateway.executable', return_value='codex')
    @patch('wirebrain.chatgpt_gateway.subprocess.run')
    def test_failed_turn_tool_action_and_timeout_are_not_success(self, run, binary, status):
        for events in [[{'type':'turn.failed'}],[{'type':'item.completed','item':{'type':'command_execution'}},{'type':'turn.completed'}]]:
            run.return_value=subprocess.CompletedProcess([],0,'\n'.join(json.dumps(e) for e in events),'')
            with self.assertRaises(ValueError):gateway.chat([{'role':'user','content':'hello'}])
        run.side_effect=subprocess.TimeoutExpired('codex',150)
        with self.assertRaises(ValueError):gateway.chat([{'role':'user','content':'hello'}])
        self.assertFalse(gateway.LOCK.locked())

    @patch('wirebrain.chatgpt_gateway.chat')
    @patch('wirebrain.intelligence.local_request')
    def test_writing_backend_is_explicit_and_local_embeddings_are_preserved(self, local, cloud):
        with tempfile.TemporaryDirectory() as home:
            store=Store(home)
            config=settings(store,{'embedding_model':'builtin:bge','chat_model':'','writing_provider':'chatgpt'})
            self.assertEqual(config['embedding_model'],'builtin:bge')
            self.assertEqual(config['chat_model'],'chatgpt-default')
            writing_request(store,{'messages':[{'role':'user','content':'hello'}]})
            cloud.assert_called_once();local.assert_not_called()
            settings(store,{'chat_model':'local-writer','writing_provider':'ollama'})
            writing_request(store,{'messages':[{'role':'user','content':'hello'}]})
            local.assert_called_once()
