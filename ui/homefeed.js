const $=selector=>document.querySelector(selector);
let state=null,currentTab='opportunities',lastRevision=null,sessionMaterialDirectory=null,sessionFormVersion=0,sessionProjectLoading=false;
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'—';
const defaultWeights={traffic:30,cash:25,commercial:20,exposure:15,preferences:10};
const labels={queued:'等待 Codex 执行',running:'探索中',stopping:'等待停止',completed:'本轮已结束',partial:'本轮已暂停',blocked:'浏览受阻',interrupted:'已停止'};
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,3500)}
function link(url,label){try{const u=new URL(url);if(!['http:','https:'].includes(u.protocol))return ''}catch{return ''}return '<a href="'+escape(url)+'" target="_blank" rel="noopener noreferrer">'+escape(label)+' ↗</a>'}
async function post(path,payload){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Token':state.csrf},body:JSON.stringify(payload)});const value=await r.json();if(!r.ok)throw Error(value.error||'保存失败');return value}
function receipt(row){const names={performed:'已完成',already_done:'原先已完成',failed:'失败',unknown:'未确认',skipped:'未操作'};return ['like','collect'].map(k=>(k==='like'?'点赞':'收藏')+'：'+(names[row.interactions?.[k]?.status]||'未操作')).join(' · ')}
function progress(){
  const s=state.active_session||state.latest_session;if(!s)return '';
  const c=s.counts;
  return '<section class="progress"><div class="progress-top"><strong>'+escape(labels[s.status])+'</strong><span>'+escape(time(s.updated_at))+'</span>'
    +(state.active_session?'<button class="button small" data-show-prompt="'+escape(s.id)+'">执行提示词</button><button class="button small" data-stop="'+escape(s.id)+'" '+(s.status==='stopping'?'disabled':'')+'>停止</button>':'')+'</div>'
    +'<p>刷新 '+c.refreshes+' · 浏览 '+c.cards+' · 原帖 '+c.details+' · 保留 '+c.kept+' · 点赞 '+c.likes+' · 收藏 '+c.collects+'</p>'
    +'<details><summary>探索进度</summary><p>'+escape(s.summary||s.last_message||'复制执行提示词到 Codex 中开始。')+'</p>'
    +'</details></section>';
}
function card(row){
  const r=row.ranking,status={open:'正在开放',unknown:'条件待确认',closed:'已截止 / 关闭'}[r.status];
  return '<article class="candidate"><div class="card-top"><span class="badge '+r.status+'">'+status+'</span><strong class="score">'+r.total+'<small> / 100</small></strong></div>'
    +'<h2>'+escape(row.title)+'</h2><p class="brief">'+escape(row.summary)+'</p><div class="card-meta"><span>截止：'+escape(row.deadline?.label||'未确认')+'</span>'+link(row.url,'原帖')+'</div>'
    +'<details><summary>评分、证据与参与条件</summary><p class="muted">'+escape(receipt(row))+' · 评估于 '+escape(time(row.assessed_at))+'</p>'
    +'<div class="score-list">'+r.components.map(c=>'<div><strong>'+escape(c.label)+' '+(c.score===null?'未知':c.points+' / '+c.weight)+'</strong><p>'+escape(c.reason)+'</p>'+(c.evidence?'<blockquote>'+escape(c.evidence.quote)+'</blockquote>':'')+'</div>').join('')+'</div>'
    +'<h3>参与条件</h3><p>'+escape(row.requirements||'未确认')+'</p><p>授权：'+escape(row.rights)+'</p>'+(row.entry_url?link(row.entry_url,'参与入口'):'')
    +(row.uncertainties.length?'<h3>待确认</h3><ul>'+row.uncertainties.map(s=>'<li>'+escape(s)+'</li>').join('')+'</ul>':'')
    +'<h3>原文证据</h3>'+row.evidence.map(d=>'<section class="evidence">'+link(d.url,d.official?'官方原文':'发现来源')+'<p class="muted">'+escape(time(d.read_at))+'</p><blockquote>'+escape(d.excerpt)+'</blockquote></section>').join('')+'</details></article>';
}
function opportunities(){
  const active=state.opportunities.filter(o=>o.ranking.status!=='closed'),closed=state.opportunities.filter(o=>o.ranking.status==='closed');
  return progress()+(active.length?'<div class="candidate-grid">'+active.map(card).join('')+'</div>':'<div class="empty">暂无候选机会</div>')
    +(closed.length?'<details class="archive"><summary>已截止 / 关闭（'+closed.length+'）</summary><div class="candidate-grid">'+closed.map(card).join('')+'</div></details>':'');
}
function materials(){
  return '<div class="section-heading"><p class="muted">当前项目的素材</p><button class="button primary" id="add-material-pack" '+(!state.current_project?'disabled':'')+'>添加素材包</button></div>'
    +(state.material_packs.length?state.material_packs.map(p=>'<article class="candidate"><div class="section-heading"><h2>'+escape(p.name)+'</h2><button class="button small" data-delete-pack="'+escape(p.id)+'">删除</button></div><p class="muted">'+escape(p.directory)+'</p><p>'+escape(p.understanding?.description||'暂无理解记录')+'</p><details><summary>查看素材（'+p.assets.length+'）</summary>'+p.assets.map(a=>'<section class="evidence"><h3>'+escape(a.title)+'</h3>'+materialPreview(a,p.id)+'</section>').join('')+'</details></article>').join(''):'<div class="empty">当前项目没有素材，也能探索机会</div>')
    +'<details class="catalog"><summary>素材理解缓存</summary><div id="material-catalog"></div></details>';
}
function render(){
  $('#page-title').textContent=currentTab==='assets'?'素材库':'候选机会';
  document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===currentTab);if(b.dataset.tab===currentTab)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  $('#candidate-count').textContent=state.stats.opportunities;$('#new-session').textContent='开始探索';
  $('#project-picker').innerHTML=state.projects.length?state.projects.map(p=>'<option value="'+escape(p.id)+'">'+escape(p.name)+'</option>').join(''):'<option value="">尚无项目</option>';
  $('#project-picker').value=state.current_project?.id||'';$('#project-picker').disabled=!state.projects.length;
  $('#export-report').href='/api/homefeed/report'+(pageProjectId?'?project_id='+encodeURIComponent(pageProjectId):'');
  $('#export-html').href='/api/homefeed/html'+(pageProjectId?'?project_id='+encodeURIComponent(pageProjectId):'');
  $('#export-html').hidden=!state.current_project;
  $('#content').innerHTML=currentTab==='assets'?materials():opportunities();if(currentTab==='assets')loadMaterialCatalog();
}
async function refresh(force=false){
  try{
    const requestedProject=pageProjectId;
    const response=await fetch('/api/homefeed'+(requestedProject?'?project_id='+encodeURIComponent(requestedProject):''));const value=await response.json();if(!response.ok)throw Error(value.error||'读取失败');
    if(requestedProject!==pageProjectId)return;pageProjectId=value.current_project?.id||null;
    const signature=JSON.stringify([value.current_project?.id,value.projects,value.revision,value.material_packs,value.opportunities.map(o=>[o.id,o.ranking])]);state=value;
    $('#connection').textContent='已连接 · 小红书';$('#load-error').hidden=true;
    if(force||signature!==lastRevision){const opened=Array.from(document.querySelectorAll('.candidate details[open]')).map(el=>el.closest('.candidate').querySelector('h2').textContent);render();document.querySelectorAll('.candidate').forEach(el=>{if(opened.includes(el.querySelector('h2').textContent))el.querySelector('details').open=true});lastRevision=signature}
    if(currentTab==='assets')loadMaterialCatalog();
  }catch(error){$('#connection').textContent='连接中断';$('#load-error').textContent=error.message;$('#load-error').hidden=false}
}
function showPrompt(id){$('#execution-prompt').value=state.execution_prompt||('请执行小红书首页探索任务 '+id+'。先读取项目 AGENTS.md 和 skills/search-opportunity/SKILL.md，执行 python homefeed.py task '+id+' --begin。使用已登录的 Playwright MCP 浏览器反复刷新小红书首页，阅读相关原帖、评分并记录好机会；按项目偏好及权重判断，不读取素材，点赞收藏合适的原帖，不关注任何作者。不要使用站内搜索替代首页探索。');$('#copy-status').textContent='';$('#prompt-dialog').showModal()}
document.addEventListener('click',async event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.dataset.close){document.getElementById(b.dataset.close).close();return}
  if(b.dataset.tab){currentTab=b.dataset.tab;render();return}
  if(b.id==='new-session')openSessionDialog();
  if(b.dataset.showPrompt)showPrompt(b.dataset.showPrompt);
  if(b.dataset.stop){b.disabled=true;try{await post('/api/homefeed/stop',{id:b.dataset.stop});await refresh(true)}catch(e){toast(e.message)}finally{b.disabled=false}}
  if(b.id==='add-material-pack'){cancelMaterialForm($('#library-form'));$('#library-form').reset();selectedMaterialDirectory=null;setMaterialRetryState($('#library-form'),false);$('#library-status').textContent='';$('#library-dialog').showModal();chooseDirectoryLabel()}
  if(b.dataset.deletePack){b.disabled=true;try{await post('/api/homefeed/library/delete',{id:b.dataset.deletePack,project_id:state.current_project.id});await refresh(true)}catch(e){toast(e.message)}finally{b.disabled=false}}
});
function setSessionDirectory(directory){
  sessionMaterialDirectory=directory;$('#session-directory').textContent=directory||'';
  $('#clear-session-directory').hidden=!directory;setMaterialRetryState($('#session-form'),false);
}
async function fillSessionProject(){
  const version=++sessionFormVersion,form=$('#session-form'),mode=form.elements.mode.value;
  cancelMaterialForm(form);setSessionDirectory(null);$('#session-error').textContent='';
  $('#session-existing-field').hidden=mode!=='continue';form.elements.project_id.required=mode==='continue';
  const p=mode==='continue'?state.projects.find(p=>p.id===form.elements.project_id.value):null;
  form.elements.name.value=p?.name||'新探索';form.elements.preferences.value=p?.preferences||'';
  for(const key of Object.keys(defaultWeights))form.elements['weight_'+key].value=(p?.weights||defaultWeights)[key];
  updateWeightTotal();
  $('#session-pack-list').innerHTML='';sessionProjectLoading=false;
  const submit=form.querySelector('[data-material-start]');submit.disabled=false;
  if(!p)return;
  sessionProjectLoading=true;submit.disabled=true;let loaded=false;
  try{
    const r=await fetch('/api/homefeed?project_id='+encodeURIComponent(p.id)),view=await r.json();if(!r.ok)throw Error(view.error||'读取项目失败');
    if(version!==sessionFormVersion)return;
    loaded=true;$('#session-pack-list').innerHTML=view.material_packs.length?'<label>项目素材</label>'+view.material_packs.map(pack=>'<label class="check"><input type="checkbox" name="material_pack_ids" value="'+escape(pack.id)+'" checked>'+escape(pack.name)+'</label>').join(''):'';
  }catch(error){if(version===sessionFormVersion){$('#session-error').textContent=error.message;return}}
  finally{if(version===sessionFormVersion){sessionProjectLoading=false;submit.disabled=!loaded}}
}
function updateWeightTotal(){
  const form=$('#session-form'),sum=Object.keys(defaultWeights).reduce((total,key)=>total+Number(form.elements['weight_'+key].value),0);
  $('#session-weight-total').textContent='总和 '+sum+' / 100';form.elements.weight_traffic.setCustomValidity(sum===100?'':'权重总和须为100');
}
$('#session-form').addEventListener('input',e=>{if(e.target.name?.startsWith('weight_'))updateWeightTotal()});
function openSessionDialog(){
  const form=$('#session-form');cancelMaterialForm(form);form.reset();
  form.elements.project_id.innerHTML=state.projects.map(p=>'<option value="'+escape(p.id)+'">'+escape(p.name)+'</option>').join('');
  form.elements.project_id.value=state.current_project?.id||state.projects[0]?.id||'';
  form.querySelector('[value="continue"]').disabled=!state.projects.length;
  form.elements.mode.value=state.projects.length?'continue':'new';
  fillSessionProject();$('#session-dialog').showModal();
}
$('#session-dialog').addEventListener('close',()=>{sessionFormVersion++;sessionProjectLoading=false;cancelMaterialForm($('#session-form'))});
$('#session-form').addEventListener('change',e=>{if(e.target.name==='mode'||e.target.name==='project_id')fillSessionProject()});
$('#pick-session-directory').addEventListener('click',async()=>{
  const b=$('#pick-session-directory');b.disabled=true;
  try{const directory=await pickMaterialDirectory(sessionMaterialDirectory);if(directory)setSessionDirectory(directory)}catch(error){$('#session-error').textContent=error.message}finally{b.disabled=false}
});
$('#clear-session-directory').addEventListener('click',()=>setSessionDirectory(null));
$('#project-picker').addEventListener('change',async e=>{
  const previous=pageProjectId;pageProjectId=e.target.value;e.target.disabled=true;
  try{await post('/api/homefeed/project/select',{id:pageProjectId});lastRevision=null;await refresh(true)}catch(error){pageProjectId=previous;toast(error.message);await refresh(true)}finally{e.target.disabled=false}
});
$('#session-form').addEventListener('submit',async e=>{
  e.preventDefault();if(sessionProjectLoading)return;
  const form=e.target,values=new FormData(form),directory=sessionMaterialDirectory,session=beginMaterialForm(form),status=$('#session-error');
  const retry=e.submitter?.dataset.materialRetry==='true';setMaterialRetryState(form,false);status.textContent='';
  try{
    const binding=directory?await understandDirectory(directory,status,session.current,retry):{};
    if(!session.current()||!$('#session-dialog').open)return;
    const r=await post('/api/homefeed/start',{...Object.fromEntries(values),login_confirmed:values.has('login_confirmed'),material_pack_ids:values.getAll('material_pack_ids'),weights:Object.fromEntries(Object.keys(defaultWeights).map(key=>[key,Number(values.get('weight_'+key))])),...binding});
    pageProjectId=r.project_id;$('#session-dialog').close();await refresh(true);showPrompt(r.id);$('#execution-prompt').value=r.execution_prompt;
  }catch(error){if(session.current()){status.textContent=error.message;setMaterialRetryState(form,error.materialRetryable===true)}}finally{session.finish()}
});
$('#copy-prompt').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#execution-prompt').value);$('#copy-status').textContent='已复制'}catch{$('#execution-prompt').select();$('#copy-status').textContent='请按 Ctrl+C（Mac：⌘C）复制'}});
$('#library-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target,values=Object.fromEntries(new FormData(form)),session=beginMaterialForm(form),directory=selectedMaterialDirectory,statusElement=$('#library-status');
  const retry=event.submitter?.dataset.materialRetry==='true';setMaterialRetryState(form,false);
  try{const binding=await understandDirectory(directory,statusElement,session.current,retry);if(!session.current()||!$('#library-dialog').open||selectedMaterialDirectory!==directory)return;await post('/api/homefeed/library/add',{...values,...binding,project_id:state.current_project.id});$('#library-dialog').close();await refresh(true)}catch(error){if(session.current()){statusElement.textContent=error.message;setMaterialRetryState(form,error.materialRetryable===true)}}finally{session.finish()}
});
refresh();setInterval(()=>refresh(),2500);
