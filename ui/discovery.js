const DEFAULT_EXPLORATION_REQUIREMENTS='1. 非排他性的共创计划\n2. 正在开放的';
const DEFAULT_SEARCH_SEEDS=['tripo 创作','即梦 创作','可灵 创作','AI创作者计划','AI创作大赛'];
const candidateStatus={matched:'符合探索要求',pending:'关键条件待确认',excluded:'已排除'};
function candidateScoreDetails(item){
  const r=item.ranking;
  return '<section class="detail-section"><h3>优先级评分 · '+(r.total===null?'待评估':r.total+' / 100')+'</h3><p>已知评分依据覆盖 '+r.known_weight+'% 权重。未知项不加分，分数不是获奖概率或预计收入。</p>'
    +r.components.map(c=>'<div class="score-row"><strong>'+escape(c.label)+' · '+(c.score===null?'未知':c.points+' / '+c.weight)+'</strong><p>'+escape(c.reason)+'</p>'+(c.evidence?'<small>官方证据：'+escape(c.evidence.quote)+'</small>':'')+'</div>').join('')
    +(r.best_material_pack?'<p>最匹配素材包：'+escape(r.best_material_pack.name)+'</p>':'')
    +'<p>'+escape(r.issues.join('；')||'探索要求已有官方证据支持；参与前仍需确认具体提交条件。')+'</p></section>';
}
function candidateCard(item){
  const r=item.ranking;
  return '<article class="panel candidate-card"><div class="card-top"><span>'+badge(platformName(item.platform))+' '+badge(candidateStatus[r.status],r.status==='matched'?'green':'orange')+'</span><strong class="candidate-score">'+(r.total===null?'待评分':r.total+'<small> / 100</small>')+'</strong></div>'
    +'<h2>'+escape(item.title)+'</h2><p>'+escape(item.summary||'尚待阅读原文')+'</p><div class="score-pills">'+r.components.map(c=>badge(c.label+' '+(c.score===null?'未知':c.points+'/'+c.weight))).join(' ')+'</div>'
    +'<p class="origin">已知依据覆盖 '+r.known_weight+'% · '+(r.assessed_at?'评估于 '+time(r.assessed_at):'尚待 Agent 评估')+'</p>'
    +(r.issues.length?'<details><summary>待确认事项（'+r.issues.length+'）</summary>'+r.issues.map(q=>'<p>'+escape(q)+'</p>').join('')+'</details>':'')
    +'<p>截止：'+escape(item.facts?.deadline?.value||'待核实')+'</p>'+opportunityLinks(item)
    +'<button class="button small" data-detail="'+escape(item.id)+'">查看评分与官方证据</button></article>';
}
function candidateView(){
  const rows=(state.candidate_opportunities||[]).filter(onPlatform),excluded=(state.excluded_candidates||[]).filter(onPlatform);
  return hero('候选机会','优先寻找流量扶持、现金激励，以及有曝光、增长或商业价值的合作。','')
    +'<section class="panel"><h2>当前探索要求</h2><p class="requirements-text">'+escape(state.current_project.exploration_requirements||DEFAULT_EXPLORATION_REQUIREMENTS)+'</p><p>初始种子词：'+(state.current_project.seed_keywords||[]).map(s=>badge(s)).join(' ')+'</p></section>'
    +pendingRequests()+runPanel()
    +'<section class="panel"><h2>按价值排序</h2><p>流量扶持 30 · 现金激励 25 · 商业合作 20 · 曝光增长 15 · 素材匹配 10。素材仅作排序加分；未知权益不计分，待确认候选不代表已经满足参与资格。</p><div class="section-heading">'+platformPicker()+'<a class="text-action" href="'+apiURL('/api/candidates.csv')+'" download="候选机会.csv">↓ 导出评分与依据</a></div></section>'
    +(rows.length?'<div class="candidate-grid">'+rows.map(candidateCard).join('')+'</div>':'<div class="empty"><strong>尚无候选机会</strong>创建探索任务后，由 Agent 执行搜索并保存证据。不会为凑数量推荐机会。</div>')
    +(excluded.length?'<details class="panel"><summary>已排除 / 已截止（'+excluded.length+'）</summary><div class="candidate-grid">'+excluded.map(candidateCard).join('')+'</div></details>':'');
}
function materialLibraryView(){
  const packs=state.material_packs||[];
  return hero('素材库','素材包可用于所有探索项目，只影响机会排序。原始文件保留在本机目录。','')
    +'<section class="panel"><div class="section-heading"><h2>'+packs.length+' 个素材包</h2><button class="button primary" id="add-material-pack">＋ 添加素材包</button></div><p>选择目录后由 Gemini 理解；同组素材复用已有理解，不重复调用。删除仅从素材库移除，保留原文件与理解缓存。</p></section>'
    +(packs.length?packs.map(p=>'<section class="panel"><div class="section-heading"><h2>'+escape(p.name)+'</h2><button class="button small" data-delete-pack="'+escape(p.id)+'">从素材库删除</button></div><p class="file-locator">'+escape(p.directory||'历史登记素材')+'</p><p>'+escape(p.understanding?.description||'历史素材，尚无完整理解；可重新添加目录来更新。')+'</p>'
      +(p.understanding?.uncertainties||[]).map(s=>'<p>待确认：'+escape(s)+'</p>').join('')
      +'<details><summary>查看素材（'+p.assets.length+'份）</summary>'+p.assets.map(a=>'<article class="evidence"><h3>'+escape(a.title)+'</h3>'+materialPreview(a,p.id)+'</article>').join('')+'</details></section>').join(''):'<div class="empty"><strong>素材库为空，也能开始探索</strong>添加素材后，Agent 可据此补充匹配评分。</div>');
}
document.addEventListener('click',async event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.id==='add-material-pack'){
    cancelMaterialForm($('#library-form'));$('#library-form').reset();selectedMaterialDirectory=null;setMaterialRetryState($('#library-form'),false);
    $('#library-status').textContent='';$('#library-dialog').showModal();chooseDirectoryLabel();
  }
  if(b.dataset.deletePack){
    b.disabled=true;try{await post('/api/library/delete',{id:b.dataset.deletePack});await refresh(true);toast('已从素材库移除，原文件保留')}catch(e){toast(e.message)}finally{b.disabled=false}
  }
});
document.querySelector('#library-form')?.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target,values=Object.fromEntries(new FormData(form)),session=beginMaterialForm(form),directory=selectedMaterialDirectory,statusElement=$('#library-status');
  const retry=event.submitter?.dataset.materialRetry==='true';setMaterialRetryState(form,false);
  try{
    const binding=await understandDirectory(directory,statusElement,session.current,retry);
    if(!session.current()||!$('#library-dialog').open||selectedMaterialDirectory!==directory)return;
    await post('/api/library/add',{...values,...binding});$('#library-dialog').close();await refresh(true);toast('素材包已加入共享素材库');
  }catch(e){if(session.current()){statusElement.textContent=e.message;setMaterialRetryState(form,e.materialRetryable===true);toast(e.message)}}finally{session.finish()}
});
