// One browser transport for every platform. The agent still chooses what to read.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';

export const ROOT=dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
export function settings(env=process.env){
  const port=Number(env.OPPORTUNITY_BROWSER_PORT||8931),channel=env.OPPORTUNITY_BROWSER_CHANNEL||'chrome';
  if(!Number.isInteger(port)||port<1024||port>65535)throw Error('浏览器端口须为1024–65535');
  if(!['chrome','msedge'].includes(channel))throw Error('浏览器渠道支持chrome或msedge');
  return {port,channel,endpoint:`http://127.0.0.1:${port}/mcp`,profile:resolve(ROOT,'data/browser-profile'),output:resolve(ROOT,'data/browser-output')};
}
export function serverArgs(config,cli){
  return [cli,'--browser',config.channel,'--user-data-dir',config.profile,'--output-dir',config.output,
    '--ignore-roots','--no-webmcp','--timeout-navigation','25000','--timeout-action','10000',
    '--redact-url-params','xsec_token,access_token,code,token','--viewport-size','1280x900'];
}
async function serve(config){
  // Keep ONE genuine Microsoft MCP session alive. A new HTTP client otherwise
  // creates a new backend and loses the selected tab/ref namespace on disconnect.
  const {Client}=await import('@modelcontextprotocol/sdk/client/index.js');
  const {StdioClientTransport}=await import('@modelcontextprotocol/sdk/client/stdio.js');
  const {Server}=await import('@modelcontextprotocol/sdk/server/index.js');
  const {StreamableHTTPServerTransport}=await import('@modelcontextprotocol/sdk/server/streamableHttp.js');
  const {ListToolsRequestSchema,CallToolRequestSchema}=await import('@modelcontextprotocol/sdk/types.js');
  await mkdir(config.output,{recursive:true});
  const upstream=new Client({name:'operating_agent-persistent-browser',version:'0.1.0'});
  const upstreamTransport=new StdioClientTransport({command:process.execPath,args:serverArgs(config,mcpPath()),cwd:ROOT,stderr:'pipe'});
  upstreamTransport.stderr?.on('data',chunk=>process.stderr.write(chunk));
  await upstream.connect(upstreamTransport);
  const sessions=new Map();let queue=Promise.resolve();
  const http=createServer(async(req,res)=>{
    try{
      const allowed=[`127.0.0.1:${config.port}`,`localhost:${config.port}`];
      if(!allowed.includes(req.headers.host)||req.headers.origin&&!allowed.some(host=>req.headers.origin===`http://${host}`)){res.writeHead(403);res.end('Local clients only');return}
      if(req.url!=='/mcp'){res.writeHead(404);res.end('Use /mcp');return}
      const id=req.headers['mcp-session-id'];
      if(id){const entry=sessions.get(id);if(!entry){res.writeHead(404);res.end('Session not found');return}await entry.transport.handleRequest(req,res);return}
      if(req.method!=='POST'){res.writeHead(400);res.end('Initialize an MCP session first');return}
      const server=new Server({name:'operating_agent-playwright',version:'0.1.0'},{capabilities:{tools:{}}});
      server.setRequestHandler(ListToolsRequestSchema,()=>upstream.listTools());
      server.setRequestHandler(CallToolRequestSchema,request=>{
        const task=queue.then(()=>upstream.callTool(request.params,undefined,{timeout:45000}));
        queue=task.catch(()=>{});return task;
      });
      const transport=new StreamableHTTPServerTransport({sessionIdGenerator:randomUUID,
        onsessioninitialized:sessionId=>sessions.set(sessionId,{server,transport})});
      await server.connect(transport);
      const closed=transport.onclose;
      transport.onclose=()=>{closed?.();if(transport.sessionId)sessions.delete(transport.sessionId)};
      await transport.handleRequest(req,res);
    }catch(error){if(!res.headersSent)res.writeHead(500);if(!res.writableEnded)res.end('MCP request failed: '+error.message)}
  });
  try{await new Promise((resolve,reject)=>{http.once('error',reject);http.listen(config.port,'127.0.0.1',resolve)})}
  catch(error){await upstream.close();throw error}
  console.log('Playwright MCP：'+config.endpoint+'\n专用登录目录：'+config.profile+'\n保持本窗口开启；Ctrl+C停止。HTTP调用共享一个真实Microsoft MCP会话；请由一个Agent串行操作。');
  let stopping=false;
  const stop=async()=>{if(stopping)return;stopping=true;for(const {server} of sessions.values())await server.close().catch(()=>{});await upstream.close().catch(()=>{});http.close();http.closeAllConnections()};
  process.on('SIGINT',stop);process.on('SIGTERM',stop);
  await new Promise(resolve=>http.once('close',resolve));
}
function mcpPath(){
  try{return resolve(dirname(require.resolve('@playwright/mcp/package.json')),'cli.js')}
  catch{throw Error('尚未安装浏览器依赖，请在项目目录运行 npm ci --ignore-scripts')}
}
async function doctor(){
  const c=settings(),checks=[{name:'Node.js ≥22',ok:Number(process.versions.node.split('.')[0])>=22,detail:process.version}];
  try{checks.push({name:'Playwright MCP',ok:true,detail:JSON.parse(await readFile(resolve(dirname(mcpPath()),'package.json'),'utf8')).version})}
  catch(error){checks.push({name:'Playwright MCP',ok:false,detail:error.message})}
  const pythonPath=process.env.OPPORTUNITY_PYTHON||[resolve(ROOT,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python')].find(existsSync)||(process.platform==='win32'?'python':'python3');
  const python=spawnSync(pythonPath,['-c','import sys,json;print(json.dumps({"version":sys.version.split()[0],"ok":sys.version_info>=(3,11)}))'],{encoding:'utf8',windowsHide:true});
  try{const py=JSON.parse(python.stdout);checks.push({name:'Python ≥3.11',ok:py.ok,detail:py.version})}
  catch{checks.push({name:'Python ≥3.11',ok:false,detail:'无法启动Python：'+(python.error?.message||python.stderr?.trim()||'未返回版本')+'；检查PATH、虚拟环境和进程权限，可用OPPORTUNITY_PYTHON指定解释器'})}
  const paths=process.platform==='win32'?(c.channel==='chrome'?
    ['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',resolve(process.env.LOCALAPPDATA||ROOT,'Google/Chrome/Application/chrome.exe')]:
    ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe']):
    (process.platform==='darwin'?['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']:['/usr/bin/google-chrome','/usr/bin/google-chrome-stable']);
  checks.push({name:c.channel==='chrome'?'Google Chrome':'Microsoft Edge',ok:paths.some(existsSync),detail:paths.find(existsSync)||'未在常用位置找到；浏览器启动实测为准'});
  const optional=spawnSync(pythonPath,['-c','import PIL,imageio_ffmpeg;from covers import font_path;print(PIL.__version__,imageio_ffmpeg.__version__,font_path())'],{encoding:'utf8',windowsHide:true,cwd:ROOT});
  const media=spawnSync(pythonPath,['-c','from material_media import ffmpeg_path;from PIL import Image;print(ffmpeg_path());print("Pillow "+Image.__version__)'],{encoding:'utf8',windowsHide:true,cwd:ROOT});
  const result={required:checks,optional_media:{ok:media.status===0,detail:media.status===0?media.stdout.trim():'素材切片/格式转换需FFmpeg和Pillow；运行 python -m pip install -r requirements-media.txt'},optional_cover:{ok:optional.status===0,detail:optional.status===0?optional.stdout.trim():'封面渲染可选；运行 python -m pip install -r requirements-cover.txt'},
    browser_endpoint:c.endpoint,profile:c.profile,note:'依赖检查不等于平台已登录或搜索已通过。'};
  console.log(JSON.stringify(result,null,2));if(checks.some(row=>!row.ok))process.exitCode=1;
}
async function connect(config){
  const {Client}=await import('@modelcontextprotocol/sdk/client/index.js');
  const {StreamableHTTPClientTransport}=await import('@modelcontextprotocol/sdk/client/streamableHttp.js');
  const client=new Client({name:'operating_agent-browser',version:'0.1.0'});
  const transport=new StreamableHTTPClientTransport(new URL(config.endpoint));
  try{await client.connect(transport,{timeout:10000})}
  catch(error){await client.close().catch(()=>{});throw Error('未能连接Playwright MCP。先运行 node browser.mjs serve 并保持窗口开启。原始错误：'+error.message)}
  return {client,transport};
}
async function saveResult(config,request,result){
  await mkdir(config.output,{recursive:true});
  const stamp=new Date().toISOString().replace(/[:.]/g,'-'),base=resolve(config.output,stamp+'-'+request.name.replace(/[^a-z0-9_-]/gi,'_'));
  const clean={...result,content:await Promise.all((result.content||[]).map(async(block,index)=>{
    if(block.type!=='image')return block;
    const path=base+'-'+index+'.'+(block.mimeType==='image/jpeg'?'jpg':block.mimeType==='image/webp'?'webp':'png');
    await writeFile(path,Buffer.from(block.data,'base64'));return {type:'image',mimeType:block.mimeType,path};
  }))};
  await writeFile(base+'.json',JSON.stringify({at:new Date().toISOString(),request,result:clean},null,2),'utf8');
  console.log('完整调用记录：'+base+'.json');
  for(const block of clean.content||[]){if(block.type==='text')console.log(block.text.length>16000?block.text.slice(0,16000)+'\n[输出截断，完整内容见调用记录]':block.text);else if(block.type==='image')console.log('截图：'+block.path)}
  if(result.isError)process.exitCode=1;
}
export async function main(args=process.argv.slice(2)){
  const [command,value,file]=args,config=settings();
  if(command==='doctor')return doctor();
  if(command==='serve'){
    return serve(config);
  }
  if(!['tools','open','snapshot','call'].includes(command)){
    console.log('用法：\n  node browser.mjs doctor\n  node browser.mjs serve\n  node browser.mjs tools\n  node browser.mjs open https://www.douyin.com/jingxuan\n  node browser.mjs snapshot [保存快照的相对路径]\n  node browser.mjs call 工具名 [参数JSON文件]\n不同终端的调用复用同一个浏览器会话；动作依据最新快照，不复用旧ref。');return;
  }
  const {client,transport}=await connect(config);
  try{
    const listing=await client.listTools();
    if(command==='tools'){await mkdir(config.output,{recursive:true});await writeFile(resolve(config.output,'tools.json'),JSON.stringify(listing,null,2),'utf8');console.log(JSON.stringify(listing,null,2));return}
    const request=command==='open'?{name:'browser_navigate',arguments:{url:value}}:
      command==='snapshot'?{name:'browser_snapshot',arguments:value?{filename:value}:{}}:
      {name:value,arguments:file?JSON.parse(await readFile(resolve(file),'utf8')):{}};
    if(!listing.tools.some(tool=>tool.name===request.name))throw Error('服务器未提供工具：'+request.name+'；先运行tools读取实际定义');
    const result=await client.callTool(request,undefined,{timeout:45000});await saveResult(config,request,result);
  }finally{await transport.terminateSession().catch(()=>{});await client.close()}
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(error=>{console.error(error.message);process.exitCode=1});
