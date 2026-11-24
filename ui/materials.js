const workspaceKind=(window.location.pathname||'').startsWith('/publish')?'publishing':'exploration';
let pageProjectId=null,selectedMaterialDirectory=null;
const materialFormSessions=new WeakMap();
function apiURL(path){
  const params=new URLSearchParams();params.set('workspace',workspaceKind);
  const pid=pageProjectId||state?.current_project?.id;
  if(pid&&pid!=='__empty_publishing__')params.set('project_id',pid);
  return path+(path.includes('?')?'&':'?')+params.toString();
}
function chooseDirectoryLabel(){
  const el=document.querySelector(document.querySelector('#library-dialog')?.open?'#library-directory':'#publishing-directory');
  if(el)el.textContent=selectedMaterialDirectory||'尚未选择素材目录';
}
let directoryPickerPromise=null;
function pickMaterialDirectory(initialDirectory=null){
  if(directoryPickerPromise)return directoryPickerPromise;
  directoryPickerPromise=new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.id='directory-picker-dialog';dialog.className='directory-picker';
    dialog.setAttribute('aria-labelledby','directory-picker-title');
    dialog.innerHTML='<div class="dialog-head"><h2 id="directory-picker-title">选择素材目录</h2><button type="button" class="icon-button" data-directory-cancel aria-label="取消选择">×</button></div>'
      +'<p class="directory-picker-help">只浏览本机文件夹，不会上传或移动文件。</p><div class="directory-locations" aria-label="快捷位置"></div>'
      +'<div class="directory-path" aria-live="polite"></div><div class="directory-list" role="group" aria-label="子文件夹"></div>'
      +'<div class="directory-picker-error" role="alert"></div><div class="directory-picker-footer"><button type="button" class="button" data-directory-cancel>取消</button><button type="button" class="button primary" data-directory-select disabled>选择此文件夹</button></div>';
    const path=dialog.querySelector('.directory-path'),list=dialog.querySelector('.directory-list'),locations=dialog.querySelector('.directory-locations');
    const error=dialog.querySelector('.directory-picker-error'),select=dialog.querySelector('[data-directory-select]');
    let current=null,finished=false,requestVersion=0;
    const finish=value=>{
      if(finished)return;finished=true;directoryPickerPromise=null;
      if(dialog.open)dialog.close();dialog.remove();resolve(value);
    };
    async function load(directory){
      const version=++requestVersion;error.textContent='';select.disabled=true;list.setAttribute('aria-busy','true');
      list.innerHTML='<p class="directory-loading">正在读取文件夹…</p>';
      try{
        const result=await post('/api/materials/browse',{directory:directory||null});if(version!==requestVersion||finished)return;
        current=result.directory;path.textContent=result.directory;path.title=result.directory;select.disabled=false;
        locations.innerHTML=result.locations.map(row=>'<button type="button" class="button small" data-directory-path="'+escape(row.path)+'">'+escape(row.name)+'</button>').join('');
        const up=result.parent?'<button type="button" class="directory-row directory-up" data-directory-path="'+escape(result.parent)+'"><span aria-hidden="true">↑</span><span>上一级</span></button>':'';
        list.innerHTML=up+result.directories.map(row=>'<button type="button" class="directory-row" data-directory-path="'+escape(row.path)+'"><span aria-hidden="true">📁</span><span>'+escape(row.name)+'</span><span aria-hidden="true">›</span></button>').join('')
          +(result.directories.length?'':'<p class="directory-empty">没有子文件夹</p>');
      }catch(reason){if(version===requestVersion&&!finished){current=null;path.textContent='';list.innerHTML='';error.textContent=reason.message}}
      finally{if(version===requestVersion)list.removeAttribute('aria-busy')}
    }
    dialog.addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button)return;
      if(button.hasAttribute('data-directory-cancel'))finish(null);
      else if(button.hasAttribute('data-directory-select')&&current)finish(current);
      else if(button.dataset.directoryPath)load(button.dataset.directoryPath);
    });
    dialog.addEventListener('cancel',event=>{event.preventDefault();finish(null)});
    document.body.append(dialog);dialog.showModal();load(initialDirectory);
  });
  return directoryPickerPromise;
}
function openPublishingProjectDialog(){
  cancelMaterialForm(document.querySelector('#publishing-project-form'));
  document.querySelector('#publishing-project-form').reset();selectedMaterialDirectory=null;
  setMaterialRetryState(document.querySelector('#publishing-project-form'),false);
  chooseDirectoryLabel();document.querySelector('#publishing-project-status').textContent='';
  document.querySelector('#publishing-project-dialog').showModal();
}
function lockMaterialForm(form){
  const rows=Array.from(form.querySelectorAll('input,textarea,select,button')).filter(e=>!e.dataset.close).map(e=>[e,e.disabled]);
  rows.forEach(([e])=>e.disabled=true);form.setAttribute('aria-busy','true');
  return ()=>{rows.forEach(([e,disabled])=>e.disabled=disabled);form.removeAttribute('aria-busy')};
}
function cancelMaterialForm(form){
  const session=materialFormSessions.get(form);
  if(session){materialFormSessions.delete(form);session.unlock()}
}
function beginMaterialForm(form){
  cancelMaterialForm(form);
  const session={unlock:lockMaterialForm(form)};materialFormSessions.set(form,session);
  return {current:()=>materialFormSessions.get(form)===session,
    finish:()=>{if(materialFormSessions.get(form)===session)cancelMaterialForm(form)}};
}
function setMaterialRetryState(form,allowed){
  const normal=form?.querySelector('[data-material-start]'),retry=form?.querySelector('[data-material-retry]');
  if(retry){retry.hidden=!allowed;if(normal)normal.hidden=allowed}
}
for(const [dialog,form] of [['#publishing-project-dialog','#publishing-project-form'],['#new-dialog','#request-form'],['#library-dialog','#library-form']]){
  document.querySelector(dialog)?.addEventListener('close',()=>cancelMaterialForm(document.querySelector(form)));
}
function materialElapsed(start,end=Date.now()){
  const seconds=Math.max(0,Math.floor((end-Date.parse(start))/1000));
  return Number.isFinite(seconds)?(seconds>=60?Math.floor(seconds/60)+'分':'')+seconds%60+'秒':'未知';
}
function materialProgressText(result,footer=true){
  const p=result.progress;
  if(!p)return result.status==='queued'?'素材已登记，等待逐文件理解…':'Gemini正在理解素材…';
  const stages={file:'读取素材并准备理解请求',preparing:'在本机准备素材，保留原片',cutting:'在本机生成切片',resplitting:'切片仍过大，正在本机继续细分',file_summary:'汇总这个文件的分段',group_summary:'综合整组素材',complete:'素材理解完成'};
  let text=(stages[p.stage]||'理解素材')+' · 已完成 '+p.files_complete+'/'+p.files_total+' 份不同素材';
  if(p.file_name)text+='\n当前：'+p.file_name;
  if(p.segments_total>1)text+=' · '+(['text','page'].includes(p.segment_kind)?'分段':'切片')+' '+p.segment_index+'/'+p.segments_total+'（已理解 '+p.segments_complete+' 段）';
  const active=['queued','running'].includes(result.status),end=active?Date.now():Date.parse(result.updated_at);
  if(p.started_at)text+='\n本轮已用时 '+materialElapsed(p.started_at,end);
  const request=p.request;
  if(request){
    const phases={encoding_request:'整理请求数据',connecting:'连接模型服务',uploading:'正在上传请求数据',waiting_response:'本机已发送完毕，等待服务响应',waiting_output:'已收到响应头，等待模型输出',receiving:'正在接收模型回答',read_response:'正在读取模型结果',response_complete:'回答已接收，校验理解结果',http_error:'服务拒绝请求（HTTP '+request.http_status+'）'};
    text+='\n'+(active?'当前步骤：':'中断时步骤：')+(phases[request.phase]||'请求处理中');
    if(request.request_started_at)text+=' · 此次请求已用时 '+materialElapsed(request.request_started_at,end);
    if(request.request_bytes>0){
      const sent=Math.min(request.uploaded_bytes||0,request.request_bytes);
      text+='\n本机已发送 '+(sent/1048576).toFixed(2)+' / '+(request.request_bytes/1048576).toFixed(2)+' MiB（'+Math.floor(sent/request.request_bytes*100)+'%）';
    }
    if(request.received_characters>0)text+='\n已接收 '+request.received_characters+' 字，等待完整回答及校验';
    if(['waiting_response','waiting_output'].includes(request.phase))text+='\n服务端未提供处理百分比，等待时间会持续更新。';
  }
  const finished=(result.file_results||[]).filter(f=>f.status==='complete');
  if(finished.length)text+='\n'+finished.map(f=>'✓ '+f.filename+(f.reused?'（复用已有理解）':'')).join('\n');
  return text+(footer?'\n关闭窗口后处理仍会继续，可在素材目录与理解对应表查看进度。':'');
}
async function understandDirectory(directory,statusElement,isCurrent=()=>true,retry=false){
  const checkCurrent=()=>{if(!isCurrent()){const error=Error('已关闭素材表单，后台理解仍保留');error.name='AbortError';throw error}};
  checkCurrent();
  if(!directory)throw Error('请先选择整组素材所在目录');
  statusElement.textContent='正在扫描目录并检查已有理解记录…';
  const initial=await post('/api/materials/analyze',{directory,retry});
  checkCurrent();
  let result=initial;
  while(['queued','running'].includes(result.status)){
    statusElement.textContent=materialProgressText(result);
    await new Promise(resolve=>setTimeout(resolve,900));
    checkCurrent();
    const response=await fetch('/api/materials/status?id='+encodeURIComponent(result.id));
    const next=await response.json();if(!response.ok)throw Error(next.error||'读取理解进度失败');result=next;
    checkCurrent();
  }
  if(result.status!=='complete'){
    const previous=['failed','unknown'].includes(initial.status);
    const header=previous?'这是上次未完成的记录，本次没有重新发送素材。':'本次素材理解尚未完成。';
    const when=result.updated_at?'\n记录时间：'+time(result.updated_at):'';
    const error=Error(header+when+(result.progress?'\n'+materialProgressText(result,false):'')+'\n'+(result.error||'尚未取得完整素材理解')+'\n如需重新发送，请点击“重试素材理解”，已完成部分会复用。');
    error.materialRetryable=['failed','unknown'].includes(result.status);throw error;
  }
  statusElement.textContent=initial.cached?'已复用同组素材的理解，没有再次调用模型。':'Gemini理解完成，正在保存项目…';
  return {material_directory:directory,material_analysis_id:result.id};
}
function resetExplorationPrompt(){
  const panel=document.querySelector('#request-prompt-panel');if(panel)panel.hidden=true;
  const text=document.querySelector('#request-prompt');if(text)text.value='';
  const hint=document.querySelector('#request-copy-status');if(hint)hint.textContent='';
  const button=document.querySelector('#copy-exploration-prompt');if(button)button.textContent='复制提示词';
  const status=document.querySelector('#request-success');if(status)status.textContent='';
}
function showExplorationPrompt(request){
  const text=document.querySelector('#request-prompt');
  text.value=request.execution_prompt||('请执行探索任务 '+request.id+'。在包含 demo.py 的项目目录读取 AGENTS.md 和 skills/search-opportunity/SKILL.md，运行 python demo.py task '+request.id+' --begin，再按记录的要求实际探索并持续保存结果。不要重新创建任务。');
  document.querySelector('#request-prompt-panel').hidden=false;
}
async function copyExplorationPrompt(){
  const text=document.querySelector('#request-prompt'),hint=document.querySelector('#request-copy-status'),button=document.querySelector('#copy-exploration-prompt');
  if(!text?.value)return;
  button.disabled=true;
  try{
    await navigator.clipboard.writeText(text.value);button.textContent='已复制';hint.textContent='已复制，到 Codex 中粘贴并发送即可。';
  }catch(error){
    button.textContent='复制提示词';text.focus();text.select();hint.textContent='自动复制不可用，已选中提示词。请按 Ctrl+C（Mac：⌘C）手动复制。';
  }finally{button.disabled=false}
}
document.querySelector('#copy-exploration-prompt')?.addEventListener('click',copyExplorationPrompt);
async function submitExplorationForm(event){
  event.preventDefault();const form=event.target,values=new FormData(form),session=beginMaterialForm(form);
  const statusElement=document.querySelector('#request-success');
  resetExplorationPrompt();
  try{
    const request=await post('/api/exploration/requests',{...Object.fromEntries(values),platforms:values.getAll('platforms'),auto_verify:true});
    if(!session.current())return;
    pageProjectId=request.project_id;
    statusElement.textContent='探索任务 '+request.id+' 已保存。复制下方提示词，到 Codex 中开始探索。';
    showExplorationPrompt(request);
    currentTab='opportunities';await refresh(true);toast('探索任务已保存');
    if(session.current())document.querySelector('#request-prompt-panel').scrollIntoView({block:'nearest',behavior:'smooth'});
  }catch(error){if(session.current()){statusElement.textContent=error.message;toast(error.message)}}finally{session.finish()}
}
document.querySelector('#publishing-project-form')?.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target,values=Object.fromEntries(new FormData(form)),session=beginMaterialForm(form);
  const directory=selectedMaterialDirectory,statusElement=document.querySelector('#publishing-project-status');
  const retry=event.submitter?.dataset.materialRetry==='true';setMaterialRetryState(form,false);
  try{
    const binding=await understandDirectory(directory,statusElement,session.current,retry);
    if(!session.current()||!document.querySelector('#publishing-project-dialog').open||selectedMaterialDirectory!==directory)return;
    const created=await post('/api/publishing/projects',{...values,...binding});
    pageProjectId=created.id;selectedPublication=null;document.querySelector('#publishing-project-dialog').close();
    currentTab='publishing';await refresh(true);toast('发布项目已创建；空白名称和描述已根据素材补齐');
  }catch(error){if(session.current()){statusElement.textContent=error.message;setMaterialRetryState(form,error.materialRetryable===true);loadMaterialCatalog();toast(error.message)}}finally{session.finish()}
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||!['pick-library-directory','pick-publishing-directory'].includes(button.id))return;
  button.disabled=true;
  try{
    const directory=await pickMaterialDirectory(selectedMaterialDirectory);
    if(directory){selectedMaterialDirectory=directory;setMaterialRetryState(button.closest('form'),false);chooseDirectoryLabel()}
  }catch(error){toast(error.message)}finally{button.disabled=false}
});
function understandingPanel(){
  const record=state.material_understanding,description=record?.description,materials=state.current_project.materials;
  if(!description)return '<section class="panel"><h2>素材理解</h2><p>创建项目时选择素材目录，由Gemini理解后保存。同组素材可在两个工作空间复用。</p></section>';
  return '<section class="panel material-understanding"><div class="section-heading"><h2>整组素材的理解</h2>'+badge(record.model,'green')+'</div><p class="file-locator">'+escape(materials.directory)+'</p><h3>'+escape(description.title)+'</h3><p>'+escape(description.description)+'</p><p>'+[...(description.themes||[]),...(description.styles||[])].map(t=>badge(t)).join(' ')+'</p>'
    +((description.uncertainties||[]).length?'<details><summary>仍需确认的事项</summary>'+description.uncertainties.map(t=>'<p>'+escape(t)+'</p>').join('')+'</details>':'')
    +'<details class="material-file-details"><summary>逐份素材的理解（'+(description.files||[]).length+'份）</summary>'+(description.files||[]).map(f=>{
      const source=(record.file_results||[]).find(r=>r.file_id===f.file_id),segments=source?.segments||[];
      return '<article class="evidence"><h4>'+escape(source?.filename||f.file_id.slice(0,12))+(source?.reused?' · 已复用':'')+'</h4><p>'+escape(f.description)+'</p>'
        +(segments.length>1?'<p>分成 '+segments.length+' 段理解：'+segments.map(s=>s.kind==='text'?'字符 '+s.text_start+'–'+s.text_end:s.kind==='page'?'第 '+(s.page_index+1)+' 页':Math.round(s.start_seconds)+'–'+Math.round(s.end_seconds)+'秒').join('、')+'</p>':'')
        +(f.uncertainties||[]).map(s=>'<p>待确认：'+escape(s)+'</p>').join('')+'</article>';
    }).join('')+'</details>'
    +'<div class="origin">理解记录 '+escape(record.id)+' · '+time(record.completed_at)+' · 按文件缓存；音视频按时长与体积切片，长文本分段、TIFF逐页理解，再综合素材。</div></section>';
}
function materialPreview(asset,packId=null){
  const url=apiURL('/api/media/'+encodeURIComponent(asset.id)+(packId?'?library_pack='+encodeURIComponent(packId):''));
  const original='<a class="link-button" href="'+url+'" target="_blank" rel="noopener">打开原素材（预览取决于浏览器格式支持） ↗</a>';
  if(asset.type==='image')return (asset.mime==='image/tiff'?'':'<img class="asset-video" src="'+url+'" alt="'+escape(asset.title)+'">')+original;
  if(asset.type==='audio')return '<audio controls preload="metadata" src="'+url+'"></audio>'+original;
  if(asset.type==='video')return '<video class="asset-video" controls preload="metadata" src="'+url+'"></video>'+original;
  return '<a class="link-button" href="'+url+'" target="_blank" rel="noopener">打开本机素材 ↗</a>';
}
async function loadMaterialCatalog(){
  const container=document.querySelector('#material-catalog');if(!container)return;
  try{
    const response=await fetch('/api/materials/catalog'),data=await response.json();if(!response.ok)return;
    container.innerHTML=data.directories.length?data.directories.map(d=>{
      const a=data.analyses.find(a=>a.id===d.analysis_id);
      const progress=a?.progress?' · 已理解 '+a.progress.files_complete+'/'+a.progress.files_total+' 份':'';
      return '<div class="evidence"><strong>'+escape(a?.description?.title||d.name)+'</strong><p class="file-locator">'+escape(d.directory)+'</p><p>'+escape({complete:'已理解，可复用',running:'理解中',queued:'等待理解',failed:'理解失败',unknown:'上次请求中断，尚未完成'}[a?.status]||'待理解')+' · '+d.files.length+'份素材'+progress+'</p>'
        +(a?.progress&&a.status!=='complete'?'<div class="material-status">'+escape(materialProgressText(a,false))+'</div>':'')
        +(a?.updated_at?'<p>最近处理：'+time(a.updated_at)+'</p>':'')
        +(a?.error?'<details><summary>查看未完成原因</summary><p class="material-error-detail">'+escape(a.error)+'</p></details>':'')+'</div>';
    }).join(''):'<p>尚未保存素材目录。两个页面将共用这里的理解记录。</p>';
  }catch(error){container.textContent='暂时无法读取素材理解记录'}
}
