"""Transport/credential/error checks with synthetic data, no paid requests."""
import io
import json
from http.client import HTTPConnection
import unittest
from contextlib import redirect_stderr,redirect_stdout
from unittest.mock import Mock,patch
from urllib.error import HTTPError,URLError

from relay_llm import RelayClient,RelayError,NoRedirect,ProgressBody,main

KEY='fixture-key-not-real'


class RelayTest(unittest.TestCase):
    def client(self,body):
        client=RelayClient(KEY)
        response=Mock();response.read.return_value=json.dumps(body,ensure_ascii=False).encode('utf-8')
        client._opener.open=Mock(return_value=Mock(__enter__=Mock(return_value=response),__exit__=Mock(return_value=False)))
        return client
    def test_actual_request_uses_exact_model_json_utf8_and_bearer_header(self):
        client=self.client({'model':'vendor-reported','choices':[{'message':{'content':'连接成功'},'finish_reason':'stop'}],
                            'usage':{'total_tokens':8}})
        result=client.chat([{'role':'user','content':'你好'}],model='gemin-3.8-flash',max_tokens=128)
        request=client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.gpt.ge/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer '+KEY)
        payload=json.loads(request.data)
        self.assertEqual(payload['model'],'gemin-3.8-flash')
        self.assertEqual(payload['messages'][0]['content'],'你好')
        self.assertFalse(payload['stream'])
        self.assertEqual((result['requested_model'],result['model'],result['text']),('gemin-3.8-flash','vendor-reported','连接成功'))
    def test_list_models_dedups_filters_and_does_not_generate(self):
        client=self.client({'data':[{'id':'flash-test'},{'id':'flash-test'},{'id':'other'}]})
        self.assertEqual(client.list_models(),['flash-test','other'])
        request=client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.gpt.ge/v1/models')
        self.assertIsNone(request.data)
    def test_failures_redact_key_and_are_never_retried_or_switched(self):
        client=RelayClient(KEY)
        body=json.dumps({'error':{'message':'model unavailable '+KEY}}).encode()
        client._opener.open=Mock(side_effect=HTTPError('https://api.gpt.ge',503,'Unavailable',{},io.BytesIO(body)))
        with self.assertRaises(RelayError) as caught:client.chat([{'role':'user','content':'test'}])
        self.assertNotIn(KEY,str(caught.exception));self.assertIn('503',str(caught.exception))
        client._opener.open.assert_called_once()
        client._opener.open=Mock(side_effect=URLError('connection timeout'))
        with self.assertRaisesRegex(RelayError,'未取得服务器响应'):client.list_models()
        client._opener.open.assert_called_once()
        client._opener.open=Mock(side_effect=URLError(ConnectionAbortedError('synthetic disconnect '+KEY)))
        with self.assertRaises(RelayError) as caught:client.chat([{'role':'user','content':'test'}])
        self.assertTrue(caught.exception.execution_unknown);self.assertNotIn(KEY,str(caught.exception))
        self.assertGreater(caught.exception.diagnostics['request_bytes'],0)
        self.assertEqual(caught.exception.diagnostics['phase'],'connect_send_or_wait_headers')
        client._opener.open.assert_called_once()
    def test_bad_endpoint_key_and_empty_visible_answer_fail_explicitly(self):
        for url in ('http://example.test/v1','https://user:password@example.test/v1','https://example.test/?key=secret'):
            with self.assertRaises(RelayError):RelayClient(KEY,url)
        with self.assertRaises(RelayError):RelayClient('')
        client=self.client({'choices':[{'message':{'content':None},'finish_reason':'length'}]})
        with self.assertRaisesRegex(RelayError,'可见回答'):client.chat([{'role':'user','content':'test'}])
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://other.test'))

    def stream_client(self,events,content_type='text/event-stream'):
        response=io.BytesIO(events.encode('utf-8'));response.headers={'Content-Type':content_type}
        client=RelayClient(KEY);client._opener.open=Mock(return_value=response);return client

    def test_stream_collects_visible_text_and_usage_skips_reasoning_and_heartbeat(self):
        chunks=[{'id':'run-1','model':'exact-reported','choices':[{'index':0,'delta':{'role':'assistant','reasoning_content':'not an answer'}}]},
                {'choices':[{'index':0,'delta':{'content':'你好'}}]},
                {'choices':[{'index':0,'delta':{'content':'，成功'},'finish_reason':'stop'}]},
                {'choices':[],'usage':{'total_tokens':17}}]
        wire=': heartbeat\n\n'+''.join('data: '+json.dumps(c,ensure_ascii=False)+'\n\n' for c in chunks)+'data: [DONE]\n\n'
        client=self.stream_client(wire);result=client.chat([{'role':'user','content':'test'}],stream=True)
        self.assertEqual(result['text'],'你好，成功');self.assertEqual(result['usage']['total_tokens'],17)
        self.assertEqual(result['model'],'exact-reported');self.assertEqual(result['request_diagnostics']['events'],4)
        self.assertEqual(result['request_diagnostics']['response_mode'],'read_stream')
        self.assertTrue(json.loads(client._opener.open.call_args.args[0].data)['stream'])
        client._opener.open.assert_called_once()

    def test_stream_without_completion_is_unknown_and_never_automatically_retried(self):
        client=self.stream_client('data: '+json.dumps({'choices':[{'delta':{'content':'partial'}}]})+'\n\n')
        with self.assertRaises(RelayError) as caught:client.chat([{'role':'user','content':'test'}],stream=True)
        self.assertTrue(caught.exception.execution_unknown)
        self.assertEqual(caught.exception.diagnostics['phase'],'read_stream');client._opener.open.assert_called_once()

    def test_stream_request_accepts_server_json_fallback_without_second_request(self):
        client=self.stream_client(json.dumps({'choices':[{'message':{'content':'JSON response'},'finish_reason':'stop'}]}),'application/json')
        result=client.chat([{'role':'user','content':'test'}],stream=True)
        self.assertEqual(result['text'],'JSON response');self.assertEqual(result['request_diagnostics']['response_mode'],'read_response')
        client._opener.open.assert_called_once()

    def test_heartbeat_cannot_keep_stream_open_forever(self):
        client=self.stream_client(': heartbeat\n\n')
        with patch('relay_llm.time.monotonic',side_effect=[0,0,0,601,601]):
            with self.assertRaises(RelayError) as caught:client.chat([{'role':'user','content':'test'}],stream=True)
        self.assertTrue(caught.exception.execution_unknown);self.assertIn('总时限',str(caught.exception))
        client._opener.open.assert_called_once()

    def test_stream_error_redacts_secret_and_retains_execution_state(self):
        client=self.stream_client('data: '+json.dumps({'error':{'message':'synthetic error '+KEY}})+'\n\n')
        with self.assertRaises(RelayError) as caught:client.chat([{'role':'user','content':'test'}],stream=True)
        self.assertNotIn(KEY,str(caught.exception));self.assertEqual(caught.exception.diagnostics['phase'],'read_stream')
        client._opener.open.assert_called_once()

    def test_progress_body_uses_content_length_and_counts_only_successfully_sent_blocks(self):
        body=b'payload'*3000;events=[]
        socket=Mock();sent=[];socket.sendall.side_effect=lambda block:sent.append(bytes(block))
        connection=HTTPConnection('example.test');connection.sock=socket
        connection.request('POST','/chat',ProgressBody(body,lambda phase,**v:events.append((phase,v))),{'Content-Length':str(len(body))})
        wire=b''.join(sent);headers,actual=wire.split(b'\r\n\r\n',1)
        self.assertEqual(actual,body);self.assertIn(b'Content-Length: '+str(len(body)).encode(),headers)
        self.assertNotIn(b'Transfer-Encoding',headers)
        self.assertEqual(events[-1],('waiting_response',{'uploaded_bytes':len(body)}))
        self.assertEqual(events[0][1]['uploaded_bytes'],0)
        # A failed send never becomes a completed upload, even if read() returned the block.
        events.clear();calls=0
        def fail(block):
            nonlocal calls
            calls+=1
            if calls==3:raise TimeoutError('synthetic write timeout')
        socket.sendall.side_effect=fail
        connection=HTTPConnection('example.test');connection.sock=socket
        with self.assertRaises(TimeoutError):
            connection.request('POST','/chat',ProgressBody(body,lambda phase,**v:events.append((phase,v))),{'Content-Length':str(len(body))})
        self.assertEqual(events[-1],('uploading',{'uploaded_bytes':8192}))

    def test_chat_reports_upload_wait_and_visible_output_without_exposing_content(self):
        secret_text='private material description'
        client=self.stream_client('data: '+json.dumps({'choices':[{'delta':{'content':'可见回答'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n')
        response=client._opener.open.return_value;events=[];bodies=[]
        def open_request(request,timeout):
            chunks=[]
            while block:=request.data.read(8192):chunks.append(block)
            bodies.append(b''.join(chunks))
            self.assertEqual(int(request.get_header('Content-length')),len(bodies[-1]))
            return response
        client._opener.open.side_effect=open_request
        result=client.chat([{'role':'user','content':secret_text}],stream=True,on_progress=events.append)
        phases=[e['phase'] for e in events]
        for phase in ['encoding_request','connecting','uploading','waiting_response','waiting_output','receiving','response_complete']:
            self.assertIn(phase,phases)
        self.assertEqual(json.loads(bodies[0])['messages'][0]['content'],secret_text)
        self.assertEqual(events[-1]['uploaded_bytes'],len(bodies[0]));self.assertEqual(events[-1]['received_characters'],4)
        self.assertNotIn(KEY,json.dumps(events));self.assertNotIn(secret_text,json.dumps(events))
        self.assertEqual(result['request_diagnostics']['response_mode'],'read_stream');client._opener.open.assert_called_once()

    def test_progress_display_failure_never_aborts_or_retries_request(self):
        client=self.client({'choices':[{'message':{'content':'成功'}}]})
        result=client.chat([{'role':'user','content':'test'}],on_progress=Mock(side_effect=ValueError('broken display')))
        self.assertEqual(result['text'],'成功');client._opener.open.assert_called_once()

    def test_progress_upload_timeout_keeps_last_confirmed_bytes_and_never_retries(self):
        client=RelayClient(KEY);events=[]
        def interrupted(request,timeout):
            request.data.read(10);request.data.read(10)
            raise TimeoutError('synthetic write timeout')
        client._opener.open=Mock(side_effect=interrupted)
        with self.assertRaises(RelayError) as caught:
            client.chat([{'role':'user','content':'test'}],on_progress=events.append)
        self.assertTrue(caught.exception.execution_unknown)
        self.assertEqual(caught.exception.diagnostics['phase'],'uploading')
        self.assertEqual(caught.exception.diagnostics['uploaded_bytes'],10)
        self.assertNotIn('waiting_response',[e['phase'] for e in events]);client._opener.open.assert_called_once()
    def test_cli_uses_environment_and_reports_failure_without_secret(self):
        with patch.dict('os.environ',{'RELAY_API_KEY':KEY}),patch.object(RelayClient,'chat',return_value={'text':'成功'}) as chat:
            output=io.StringIO()
            with redirect_stdout(output):self.assertEqual(main(['--model','exact-model','你好']),0)
            self.assertEqual(output.getvalue().strip(),'成功')
            self.assertEqual(chat.call_args.args[1],'exact-model')
        with patch.dict('os.environ',{},clear=True),redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(['你好']),1)
            self.assertIn('RELAY_API_KEY',errors.getvalue())
