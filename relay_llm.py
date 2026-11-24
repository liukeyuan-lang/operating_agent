"""V-API Chat Completions client (Python standard library only).

Docs: https://api-gpt-ge.apifox.cn/210339408e0
Set RELAY_API_KEY, or use --ask-key to enter it without saving it.
Examples:
  python relay_llm.py --ask-key "只回复：连接成功"
  python relay_llm.py --ask-key --list-models --filter flash
  python relay_llm.py --model MODEL_ID --json "你好"
macOS: use python3. Requests are never retried or switched to another model.
"""
import argparse
import getpass
import json
import math
import os
import sys
import time
from datetime import datetime,timezone
from http.client import IncompleteRead
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from urllib.request import Request,HTTPRedirectHandler,build_opener

DEFAULT_BASE_URL='https://api.gpt.ge/v1'
DEFAULT_MODEL='gemini-3.8-flash'


class RelayError(Exception):
    """Safe-to-display error; credentials are removed before it is raised."""
    def __init__(self,message,execution_unknown=False,diagnostics=None):
        super().__init__(message)
        self.execution_unknown=execution_unknown
        self.diagnostics=diagnostics


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        # Do not forward the bearer credential to a redirected destination.
        return None


class ProgressBody:
    """Content-Length body; confirm each block only when the sender asks for the next.

    http.client sends a read() block before requesting another. These counts mean
    accepted by the local socket, not acknowledged or processed by the server.
    """
    def __init__(self,body,report):
        self.body=body;self.report=report;self.position=0;self.pending=0

    def read(self,size=-1):
        self.position+=self.pending;self.pending=0
        self.report('waiting_response' if self.position==len(self.body) else 'uploading',uploaded_bytes=self.position)
        end=len(self.body) if size<0 else min(len(self.body),self.position+size)
        block=self.body[self.position:end];self.pending=len(block)
        return block


class RelayClient:
    def __init__(self,api_key,base_url=DEFAULT_BASE_URL,timeout=60):
        if not isinstance(api_key,str) or not api_key.strip():
            raise RelayError('缺少密钥：请设置RELAY_API_KEY，或使用--ask-key交互输入')
        self._api_key=api_key.strip()
        if any(c.isspace() for c in self._api_key):raise RelayError('密钥不能包含空格或换行')
        parsed=urlsplit(base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RelayError('API根地址须为不带账号密码、查询参数或片段的HTTPS地址，例如https://api.gpt.ge/v1')
        if not math.isfinite(timeout) or timeout<=0:raise RelayError('timeout须为正数')
        self.base_url=base_url.rstrip('/')
        self.timeout=timeout
        self._opener=build_opener(NoRedirect())

    def _redact(self,value):
        if isinstance(value,str):return value.replace(self._api_key,'[REDACTED]')
        if isinstance(value,dict):return {self._redact(k):self._redact(v) for k,v in value.items()}
        if isinstance(value,list):return [self._redact(v) for v in value]
        return value

    def _read_stream(self,response,report=None):
        parts=[];result={};usage=None;finish=None;done=False;events=0;first_event=None;data=[]
        characters=0
        started=time.monotonic()
        def consume(lines):
            nonlocal usage,finish,done,events,first_event,characters
            value='\n'.join(lines)
            if value.strip()=='[DONE]':done=True;return
            try:event=json.loads(value)
            except ValueError:raise RelayError('流式响应包含无效JSON，未自动重试',execution_unknown=True) from None
            if not isinstance(event,dict):raise RelayError('流式响应格式无效',execution_unknown=True)
            if event.get('error'):raise RelayError('服务返回错误：'+json.dumps(self._redact(event['error']),ensure_ascii=False)[:800])
            events+=1
            if first_event is None:first_event=round(time.monotonic()-started,2)
            for key in ['id','model']:
                if key in event:result[key]=event[key]
            if event.get('usage') is not None:usage=event['usage']
            for choice in event.get('choices') or []:
                if choice.get('index',0)!=0:continue
                delta=choice.get('delta') or choice.get('message') or {}
                content=delta.get('content')
                text=content if isinstance(content,str) else ''.join(c['text'] for c in content if isinstance(c,dict) and isinstance(c.get('text'),str)) if isinstance(content,list) else ''
                if text:parts.append(text);characters+=len(text)
                if choice.get('finish_reason') is not None:finish=choice['finish_reason']
            if report:report('receiving' if characters else 'waiting_output',received_characters=characters,stream_events=events)
        for raw in response:
            if time.monotonic()-started>max(self.timeout,600):raise TimeoutError('流式读取超过总时限，执行状态未知')
            try:line=raw.decode('utf-8').rstrip('\r\n')
            except UnicodeDecodeError:raise RelayError('流式响应不是有效UTF-8',execution_unknown=True) from None
            if not line:
                if data:consume(data);data=[]
                if done:break
            elif line.startswith('data:'):data.append(line[5:].lstrip(' '))
            # SSE comments/heartbeat and other event fields carry no answer text.
        if data and not done:consume(data)
        if not done and finish is None:raise ConnectionError('流式响应提前结束，未收到完成标记')
        result.update(choices=[{'message':{'content':''.join(parts)},'finish_reason':finish}],usage=usage)
        result['_stream_diagnostics']={'events':events,'first_event_seconds':first_event,'done':done}
        return result

    def _request(self,path,payload=None,stream=False,on_progress=None):
        started_at=datetime.now(timezone.utc).isoformat();started=time.monotonic()
        state={'request_started_at':started_at,'request_bytes':0,'uploaded_bytes':0,'received_characters':0}
        last_phase=None;last_report=0
        phase='connect_send_or_wait_headers'
        def report(current,**values):
            nonlocal phase,last_phase,last_report
            if on_progress is None:return
            phase=current;state.update(values)
            now=time.monotonic()
            if current==last_phase and now-last_report<0.75:return
            last_phase=current;last_report=now
            # A progress display must never interrupt or resend a paid request.
            try:on_progress({**state,'phase':current,'elapsed_seconds':round(now-started,2)})
            except Exception:pass
        report('encoding_request')
        body=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
        state['request_bytes']=len(body or b'')
        report('connecting')
        request=Request(self.base_url+path,data=ProgressBody(body,report) if body is not None and on_progress else body,headers={
            'Authorization':'Bearer '+self._api_key,'Content-Type':'application/json',
            'Accept':'text/event-stream' if stream else 'application/json','User-Agent':'operating-agent-relay/0.1'})
        if body is not None:request.add_header('Content-Length',str(len(body)))
        try:
            with self._opener.open(request,timeout=self.timeout) as response:
                header_seconds=round(time.monotonic()-started,2)
                if stream and 'application/json' not in str(response.headers.get('Content-Type','')).lower():
                    phase='read_stream';report('waiting_output');result=self._read_stream(response,report if on_progress else None)
                else:
                    phase='read_response';report('read_response');raw=response.read().decode('utf-8');result=None
        except HTTPError as error:
            report('http_error',http_status=error.code)
            detail=error.read(8192).decode('utf-8',errors='replace')
            try:
                parsed=json.loads(detail)
                value=parsed.get('error',parsed)
                detail=value.get('message',json.dumps(value,ensure_ascii=False)) if isinstance(value,dict) else str(value)
            except (ValueError,AttributeError):pass
            suffix='（未重试；模型名称请通过--list-models核对）' if error.code in {400,404,503} else '（未自动重试）'
            raise RelayError(f'HTTP {error.code}: '+self._redact(detail)[:800]+suffix) from None
        except (URLError,TimeoutError,OSError,IncompleteRead) as error:
            reason=error.reason if isinstance(error,URLError) else error
            diagnostics={'phase':phase,'request_bytes':len(body or b''),'elapsed_seconds':round(time.monotonic()-started,2),
                         'timeout_seconds':self.timeout,
                         'uploaded_bytes':state['uploaded_bytes'] if on_progress else None,
                         'winerror':getattr(reason,'winerror',None),'error_type':type(reason).__name__}
            uncertain=payload is not None
            suffix='；未自动重试，连接中断不能证明服务端未执行' if uncertain else '；未自动重试，未取得服务器响应'
            size=round(diagnostics['request_bytes']/1048576,2)
            raise RelayError('网络请求失败：'+self._redact(str(error))[:500]+f'（请求约{size}MiB，耗时{diagnostics["elapsed_seconds"]}秒）'+suffix,
                             execution_unknown=uncertain,diagnostics=diagnostics) from None
        except RelayError as error:
            if error.diagnostics is None:error.diagnostics={'phase':phase,'request_bytes':len(body or b''),'elapsed_seconds':round(time.monotonic()-started,2)}
            raise
        if result is None:
            try:result=json.loads(raw)
            except ValueError:raise RelayError('服务未返回有效JSON；未自动重试') from None
        if not isinstance(result,dict):raise RelayError('服务返回的JSON不是对象')
        result=self._redact(result)
        if result.get('error'):raise RelayError('服务返回错误：'+json.dumps(result['error'],ensure_ascii=False)[:800])
        result['_client_diagnostics']={'request_bytes':len(body or b''),'elapsed_seconds':round(time.monotonic()-started,2),
                                       'header_seconds':header_seconds,'phase':'complete','response_mode':'read_stream' if stream and phase in {'waiting_output','receiving'} else phase,
                                       **result.pop('_stream_diagnostics',{})}
        report('response_complete')
        return result

    def list_models(self):
        result=self._request('/models')
        rows=result.get('data')
        if not isinstance(rows,list):raise RelayError('模型列表响应缺少data数组')
        return sorted({row['id'] for row in rows if isinstance(row,dict) and isinstance(row.get('id'),str)})

    def chat(self,messages,model=DEFAULT_MODEL,max_tokens=512,stream=False,on_progress=None):
        if not isinstance(model,str) or not model.strip():raise RelayError('模型ID不能为空')
        if type(max_tokens) is not int or max_tokens<=0:raise RelayError('max_tokens须为正整数')
        if not isinstance(messages,list) or not messages:raise RelayError('messages须为非空消息数组')
        result=self._request('/chat/completions',{'model':model,'messages':messages,
                             'max_tokens':max_tokens,'stream':bool(stream)},stream=bool(stream),on_progress=on_progress)
        choices=result.get('choices')
        if not isinstance(choices,list) or not choices or not isinstance(choices[0],dict):
            raise RelayError('响应缺少choices，未取得模型回答')
        first=choices[0];message=first.get('message')
        content=message.get('content') if isinstance(message,dict) else None
        if isinstance(content,list):content='\n'.join(c['text'] for c in content if isinstance(c,dict) and isinstance(c.get('text'),str))
        if not isinstance(content,str) or not content.strip():
            raise RelayError('服务没有返回可见回答，finish_reason='+str(first.get('finish_reason'))+'；未自动重试')
        return {'requested_model':model,'model':result.get('model'),'text':content,
                'usage':result.get('usage'),'finish_reason':first.get('finish_reason'),'id':result.get('id'),
                'request_diagnostics':result.get('_client_diagnostics')}


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='调用用户指定中转站，不上传项目文件，不保存密钥或自动切换模型')
    parser.add_argument('prompt',nargs='?',help='要发送的文字')
    parser.add_argument('--model',default=os.environ.get('RELAY_MODEL',DEFAULT_MODEL),help='准确模型ID，按原样发送')
    parser.add_argument('--base-url',default=os.environ.get('RELAY_BASE_URL',DEFAULT_BASE_URL),help='API根地址，默认https://api.gpt.ge/v1')
    parser.add_argument('--ask-key',action='store_true',help='交互输入密钥，不回显或保存')
    parser.add_argument('--timeout',type=float,default=60)
    parser.add_argument('--max-tokens',type=int,default=512)
    parser.add_argument('--json',action='store_true',help='输出回答及模型、用量元数据')
    parser.add_argument('--stream',action='store_true',help='通过SSE接收响应，收到完成结果后输出；未自动重试')
    parser.add_argument('--list-models',action='store_true',help='读取当前密钥可用的模型ID，不调用聊天生成')
    parser.add_argument('--filter',default='',help='模型列表关键词过滤')
    args=parser.parse_args(argv)
    if not args.list_models and not (args.prompt or '').strip():parser.error('请填写prompt，或使用--list-models')
    try:
        key=getpass.getpass('API key（不回显、不保存）：') if args.ask_key else os.environ.get('RELAY_API_KEY','')
        client=RelayClient(key,args.base_url,args.timeout)
        if args.list_models:
            result=[m for m in client.list_models() if args.filter.casefold() in m.casefold()]
            print(json.dumps(result,ensure_ascii=False,indent=2))
        else:
            result=client.chat([{'role':'user','content':args.prompt}],args.model,args.max_tokens,stream=args.stream)
            print(json.dumps(result,ensure_ascii=False,indent=2) if args.json else result['text'])
        return 0
    except (RelayError,EOFError) as error:
        print(str(error),file=sys.stderr);return 1
    except KeyboardInterrupt:
        print('已中止；未自动重试',file=sys.stderr);return 130


if __name__=='__main__':raise SystemExit(main())
