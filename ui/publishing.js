// Scene A uses the same project memory and file store as the weekly planner.
const publicationFromURL=new URLSearchParams(window.location.search).get("publication")||"";
let selectedPublication=/^[a-f0-9]{12}$/.test(publicationFromURL)?publicationFromURL:null, publicationDirty=false, publicationEditRevision=null;
const publicationImage=(job,cover,type="cover")=>apiURL('/api/publication-image?job_id='+encodeURIComponent(job.id)+'&cover_id='+encodeURIComponent(cover.id)+'&type='+type);
function activePublication(){return state.publications.find(j=>j.id===selectedPublication)}
function publicationCard(j){
  return '<article class="source-card"><div class="card-top">'+badge(j.platform_config.name)+" "+badge(j.status_label,j.approval_valid?"green":"orange")+'<small>v'+j.current.number+'</small></div><h3>'+escape(j.current.title||j.asset?.title||"新发布准备任务")+'</h3><p>'+escape(j.preparation)+'</p><p>'+escape(j.asset?.title||"素材已移除")+' · '+escape(j.current.account_name||"账号未指定")+'</p><button class="button small" data-open-publication="'+j.id+'">打开发布包 →</button></article>';
}
function publishing(){
  const job=activePublication();
  if(job)return publicationEditor(job);
  const assets=state.assets.filter(a=>a.file_available&&a.type==='video'&&(a.specs.container==='mp4'||a.locator.toLowerCase().endsWith('.mp4')));
  return hero("已有成片，准备成可检查的发布包。","选用已有素材，准备文案与封面，核对版本和账号；本地发布包、平台草稿与实际发布分别记录。","SCENARIO A / 已有素材，需要发布")
    +understandingPanel()+'<section class="panel"><h2>开始准备</h2>'+(assets.length?'<form id="publication-start"><label for="publication-asset">选用已登记的本地成片</label><select id="publication-asset" name="asset_id">'+assets.map(a=>'<option value="'+a.id+'">'+escape(a.title)+' · '+a.specs.duration_seconds+'秒</option>').join("")+'</select><label for="publication-platform">目标平台</label><select id="publication-platform" name="platform">'+state.platform_catalog.map(p=>'<option value="'+p.id+'">'+escape(p.name)+'</option>').join("")+'</select><p>选择平台后单独准备文案与封面。同一素材可建立不同平台的包；平台规则与草稿须实际核验。素材理解已由Gemini完成；发布文案与封面仍由Agent准备。</p><button type="submit" class="button primary">为这条成片建立发布包</button></form>':'<p>创建发布项目时选择包含MP4成片的素材目录。图片、音频和文档也可参与整组素材理解；当前视频发布包选用MP4成片。</p><button class="button small" data-tab="assets">登记素材</button>')+'</section>'
    +'<div class="section-heading"><h2>已积累的发布准备</h2><small>'+state.publications.length+' 个</small></div><div class="list-grid">'+(state.publications.length?state.publications.map(publicationCard).join(""):'<div class="empty">暂无发布包。先创建发布项目，理解素材后再选择成片和目标平台。</div>')+'</div>';
}
function publicationEditor(job){
  const config=job.platform_config,r=job.current,cover=job.covers.find(c=>c.id===r.cover_id);
  publicationEditRevision=r.number;
  const stages=[[!!job.asset?.file_available,"素材"],[!!r.body,"文案"],[!!cover,"封面"],[job.approval_valid,"确认"],[job.status==="draft_filled","平台草稿"]];
  const checks=job.preflight.map(c=>'<div class="pub-check-row">'+badge({pass:"通过",blocked:"缺项",pending:"待核对",warning:"提醒"}[c.status],c.status==="pass"?"green":"orange")+'<div><strong>'+escape(c.label)+'</strong><p>'+escape(c.note)+'</p></div></div>').join("");
  return '<div class="pub-heading"><button class="link-button" id="publication-back">← 全部发布准备</button><div class="eyebrow">SCENARIO A / 发布前检查</div><h1>'+escape(job.asset?.title||"素材已移除")+'</h1><div>'+badge(config.name)+' '+badge(job.status_label,"green")+' <small>v'+r.number+' · '+time(job.updated_at)+'</small></div></div>'
    +'<div class="pub-stages">'+stages.map(([done,label])=>'<span class="'+(done?'complete':'')+'">'+(done?'✓':'○')+' '+label+'</span>').join("")+'</div>'
    +'<div class="pub-toolbar">'+(job.local_package_ready?'<a class="button primary" href="'+apiURL('/api/publication-package?id='+job.id)+'" download>下载完整发布包 ZIP ↓</a>':'<span class="origin">封面、文案和素材齐全后可下载完整 ZIP</span>')+'<a class="button small" href="'+apiURL('/api/publication-package?id='+job.id+'&format=md')+'" download="发布包说明.md">下载说明</a><span class="origin">ZIP含原片、PNG封面、文案与版本清单</span></div>'
    +(job.request_status==="waiting_codex"?'<div class="request-box">准备任务已保存。回到 Codex 请求“准备发布包 '+job.id+'”，由 Agent 读取项目与成片后写作。当前尚未自动生成文案。</div>':"")
    +'<div id="pub-stale-note" class="pub-stale" role="status"></div>'
    +'<div class="pub-grid"><section class="panel pub-preview"><div class="section-heading"><h2>本地成品预览</h2><small>非平台草稿</small></div>'
    +(cover?'<img class="pub-cover-preview" id="pub-live-cover" src="'+publicationImage(job,cover)+'" alt="由原片截帧制作的封面：'+escape(cover.headline)+'">':'<div class="empty"><strong>封面尚未出图</strong>下方可从原片取帧生成 PNG。</div>')
    +'<div class="pub-note-preview"><h3 id="pub-live-title">'+escape(r.title||"标题待准备")+'</h3><div id="pub-live-body" class="pub-live-copy">'+escape(r.body||"正文待准备")+'</div><p id="pub-live-tags" class="pub-tags">'+escape(r.tags.join(" "))+'</p></div>'
    +(job.asset?.file_available?'<details><summary>播放本次选定的完整原片</summary><video class="asset-video" controls preload="metadata" src="'+apiURL('/api/media/'+job.asset_id)+'"></video><p>'+escape(job.asset.locator)+'</p><small>原片 '+job.asset.specs.width+'×'+job.asset.specs.height+'；未转码或改写。</small></details>':"")+'</section>'
    +'<div><section class="panel"><div class="section-heading"><h2>文案与目标账号</h2><small>修改后保存新版本</small></div>'
    +(job.title_candidates.length?'<details class="pub-title-options"><summary>比较 '+job.title_candidates.length+' 个标题方向</summary>'+job.title_candidates.map((t,n)=>'<div class="pub-title-option"><button type="button" class="link-button" data-publication-title="'+n+'">选用：'+escape(t.title)+'</button><small>'+escape(t.method)+' · '+[...t.title].length+'字</small><p>'+escape(t.reason)+'</p><p class="origin">取舍：'+escape(t.tradeoff)+'</p></div>').join("")+'</details>':"")
    +'<form id="publication-copy"><label for="pub-title">发布标题</label><input id="pub-title" name="title" maxlength="80" value="'+escape(r.title)+'"><span class="pub-count" id="pub-title-count"></span>'
    +'<label for="pub-body">正文</label><textarea id="pub-body" name="body" rows="11" maxlength="8000">'+escape(r.body)+'</textarea>'
    +'<label for="pub-tags">标签建议（空格分隔，平台话题需另核）</label><input id="pub-tags" name="tags" value="'+escape(r.tags.join(" "))+'"><span class="pub-count" id="pub-body-count"></span>'
    +'<label for="pub-account">本次发布账号昵称</label><input id="pub-account" name="account_name" value="'+escape(r.account_name)+'" placeholder="尚未指定，不会代选账号">'
    +'<label for="pub-account-url">'+escape(config.name)+'账号公开主页</label><input id="pub-account-url" type="url" name="account_url" value="'+escape(r.account_url)+'" placeholder="'+escape(config.profile_example)+'">'
    +'<p class="origin">这是目标账号记录；实际填写草稿时还须核对登录身份。</p><div class="pub-buttons"><button class="button primary" type="submit">保存文案与账号</button><button class="button small" type="button" id="pub-reload">重新载入，放弃未保存修改</button></div></form>'
    +'<div class="pub-buttons"><button class="button small" data-pub-copy="title">复制标题</button><button class="button small" data-pub-copy="body">复制正文与标签</button></div></section>'
    +'<section class="panel"><h2>封面成图</h2><p>'+(cover?.style==="frame"?'直接使用原片截图，'+cover.width+'×'+cover.height+'，未添加文字、裁切或排版。':'从这版原片截取完整画面，配项目标题。'+config.cover_width+'×'+config.cover_height+'封面画布不会重剪原视频，也不恢复原片缺失的清晰度。')+'</p>'
    +'<div class="pub-cover-options">'+job.covers.map(c=>'<button type="button" class="pub-cover-option '+(c.id===r.cover_id?'selected':'')+'" data-select-cover="'+c.id+'"><img src="'+publicationImage(job,c)+'" alt="封面候选 '+c.frame_seconds+'秒"><span>'+c.frame_seconds+'秒'+(c.id===r.cover_id?' · 已选':' · 选用')+'</span></button>').join("")+'</div>'
    +'<details><summary>从其他时点制作一张封面</summary><form id="publication-cover"><label for="pub-frame">原片时间点（秒）</label><input id="pub-frame" name="frame_seconds" type="number" step="0.1" min="0" max="'+(job.asset?.specs.duration_seconds||0)+'" value="'+(cover?.frame_seconds||0)+'" required>'
    +'<label for="pub-headline">封面主标题（24字内，可换行）</label><textarea id="pub-headline" name="headline" maxlength="26" rows="2" required>'+escape(cover?.headline||"请写与作品一致的主标题")+'</textarea>'
    +'<label for="pub-subtitle">副标题</label><input id="pub-subtitle" name="subtitle" maxlength="40" value="'+escape(cover?.subtitle||state.current_project.name+"｜作品预告")+'"><button type="submit" class="button small">从原片生成封面 PNG</button></form></details></section></div></div>'
    +'<section class="panel"><div class="section-heading"><h2>自检与人工核对</h2><small>保存文案后再核对；修改内容会清除勾选</small></div>'+checks
    +'<form id="publication-checks"><div class="pub-human-checks">'+Object.entries(job.checks_catalog).map(([k,label])=>'<label><input type="checkbox" name="'+k+'" '+(r.checks[k]?'checked':'')+'> '+escape(label)+'</label>').join("")+'</div><button class="button small" type="submit">保存本版核对结果</button></form>'
    +'<div class="pub-confirm"><p>确认绑定本次账号、文案、原片和封面。这里只记录发布包确认，正式发布仍须单独确认。</p><button class="button primary" id="publication-approve" '+(!job.can_confirm||job.approval_valid?'disabled':'')+'>'+(job.approval_valid?'本版发布包已确认':'确认当前版本发布包')+'</button></div></section>'
    +'<section class="panel"><h2>平台草稿与发布记录</h2><p><strong>草稿状态：</strong>'+escape({not_filled:"尚未填写",requested:"已保存任务，等待Codex执行",filled:"实际界面已核查",blocked:"访问受阻",unknown:"结果未知，先核查"}[job.draft.status]||job.draft.status)+'</p><p>'+escape(job.draft.note||"本地包与平台编辑器分别验收。当前网页没有后台自动填写功能。")+'</p>'
    +'<button class="button small" id="publication-request-draft" '+(!job.approval_valid||["filled","unknown","requested"].includes(job.draft.status)||job.receipts.length?'disabled':'')+'>保存给 Codex 的草稿填写任务</button>'
    +(job.draft.task_id?'<p class="hint">在当前对话请求“执行草稿任务 '+escape(job.draft.task_id)+'”。仅填写指定账号的此版草稿；核对上传授权后执行，正式发布另行确认。</p>':"")
    +'<details class="pub-receipt"><summary>登记已在外部发布的结果或未知状态</summary><p>仅保存人工反馈，不会触发发布。链接尚未回查时明确标记人工登记。</p><form id="publication-receipt"><label for="pub-result">结果</label><select id="pub-result" name="kind"><option value="published_reported">已发布，填写作品链接</option><option value="unknown">无法确认是否成功，需要核查</option></select><label for="pub-result-url">已发布作品链接</label><input id="pub-result-url" name="url" type="url" placeholder="'+escape(config.home_url)+'"><label for="pub-result-note">实际观察或说明</label><textarea id="pub-result-note" name="note" required></textarea><button type="submit" class="button small">保存结果记录</button></form></details>'
    +job.receipts.map(e=>'<div class="evidence">'+escape(e.note)+'<p>'+(e.url?link(e.url,"人工登记的发布链接 ↗"):"状态未知，不自动重复发布")+' · '+time(e.at)+'</p></div>').join("")+'</section>'
    +'<details class="panel"><summary>内容简报、自检依据与版本记录</summary><h3>内容简报</h3>'+Object.entries(job.brief).map(([k,v])=>'<p><strong>'+escape(k)+'：</strong>'+escape(Array.isArray(v)?v.join("；"):v)+'</p>').join("")
    +'<h3>Agent 写作自检（不是平台审核结果）</h3>'+job.editorial_review.map(x=>'<p>• '+escape(x.check)+'：'+escape(x.note)+'</p>').join("")
    +(job.platform_evidence?'<h3>平台原始规则</h3><p>'+link(job.platform_evidence.url,"实际读取的平台上传面板")+' · '+time(job.platform_evidence.read_at)+'</p><blockquote>'+escape(job.platform_evidence.excerpt)+'</blockquote><p>'+escape(job.platform_evidence.scope_note)+'</p>':"")
    +'<h3>方法参考</h3><p>'+link('https://github.com/SpaceZephyr/creator-buddy/tree/'+job.method.commit,job.method.name)+'。'+escape(job.method.mode)+'</p>'
    +'<h3>版本与执行记录</h3>'+job.events.map(e=>'<div class="log"><time>'+time(e.at)+'</time><p>'+escape(e.message)+'</p></div>').join("")+'</details>';
}
function publicationLivePreview(){
  if(!$("#publication-copy")||!activePublication())return;
  const title=$("#pub-title").value,body=$("#pub-body").value,tags=$("#pub-tags").value;
  $("#pub-live-title").textContent=title;$("#pub-live-body").textContent=body;$("#pub-live-tags").textContent=tags;
  $("#pub-title-count").textContent=[...title].length+" / "+activePublication().platform_config.title_budget+" 字符工作阈值";
  $("#pub-body-count").textContent=[...(body+"\n"+tags)].length+" / "+activePublication().platform_config.body_budget+" 字符工作阈值 · 平台计数另核";
}
async function publicationMutation(route,payload){
  const result=await post(route,payload);publicationDirty=false;await refresh(true);publicationLivePreview();return result;
}
document.addEventListener("input",event=>{
  if(event.target.closest("#publication-copy")){publicationDirty=true;$("#pub-stale-note").textContent="当前是未保存的编辑预览；修改后的内容不会沿用原版本的确认。";publicationLivePreview()}
});
document.addEventListener("submit",async event=>{
  const form=event.target;if(!["publication-start","publication-copy","publication-cover","publication-checks","publication-receipt"].includes(form.id))return;
  event.preventDefault();const button=form.querySelector('[type="submit"]');button.disabled=true;
  try{
    const values=Object.fromEntries(new FormData(form)),job=activePublication();
    if(form.id==="publication-start"){
      const created=await post("/api/publications",values);selectedPublication=created.id;await refresh(true);publicationLivePreview();toast("已建立准备任务；内容由Codex完成，未后台自动生成");
    }else if(form.id==="publication-copy"){
      await publicationMutation("/api/publications/edit",{...values,id:job.id,expected_revision:publicationEditRevision,tags:values.tags.trim()?values.tags.trim().split(/\s+/):[]});toast("已保存新版本；内容变化后的核对与确认需重做");
    }else{
      if(publicationDirty)throw Error("请先保存文案与账号，再操作封面、核对或结果记录，避免丢失修改");
      if(form.id==="publication-cover"){
        toast("正在从本地原片取帧并排版，尚未改写视频");await publicationMutation("/api/publications/cover",{...values,id:job.id,expected_revision:publicationEditRevision,frame_seconds:Number(values.frame_seconds)});toast("PNG封面已生成，内容版本已更新");
      }else if(form.id==="publication-checks"){
        const checks=Object.fromEntries(Object.keys(job.checks_catalog).map(k=>[k,form.elements[k].checked]));
        await publicationMutation("/api/publications/edit",{id:job.id,expected_revision:publicationEditRevision,checks});toast("本版核对已保存；未执行平台动作");
      }else{
        await publicationMutation("/api/publications/receipt",{...values,id:job.id,expected_revision:publicationEditRevision});toast("已保存人工结果，尚未回查平台");
      }
    }
  }catch(error){toast(error.message)}finally{button.disabled=false}
});
document.addEventListener("click",async event=>{
  const b=event.target.closest("button");if(!b)return;
  try{
    if(b.dataset.openPublication){selectedPublication=b.dataset.openPublication;publicationDirty=false;currentTab="publishing";render();publicationLivePreview();window.scrollTo(0,0)}
    if(b.dataset.prepareAction){
      const j=await post("/api/publications",{plan_id:state.weekly_plan.id,action_id:b.dataset.prepareAction});
      selectedPublication=j.id;publicationDirty=false;currentTab="publishing";$("#detail-dialog").close();await refresh(true);publicationLivePreview();window.scrollTo(0,0);
    }
    if(b.id==="publication-back"){if(publicationDirty)throw Error("请先保存，或点击“重新载入”放弃当前修改");selectedPublication=null;render();window.scrollTo(0,0)}
    if(b.id==="pub-reload"){publicationDirty=false;await refresh(true);publicationLivePreview()}
    if(b.dataset.publicationTitle){$("#pub-title").value=activePublication().title_candidates[Number(b.dataset.publicationTitle)].title;publicationDirty=true;$("#pub-stale-note").textContent="标题候选已放入编辑器，保存后形成新版本；尚未改变平台内容。";publicationLivePreview()}
    if(b.dataset.pubCopy){
      const text=b.dataset.pubCopy==="title"?$("#pub-title").value:$("#pub-body").value+"\n\n"+$("#pub-tags").value;
      await navigator.clipboard.writeText(text);toast("已复制当前编辑内容");
    }
    if(b.dataset.selectCover||["publication-approve","publication-request-draft"].includes(b.id)){
      if(publicationDirty)throw Error("请先保存文案与账号，当前修改还未写入版本");
      b.disabled=true;const job=activePublication(),base={id:job.id,expected_revision:publicationEditRevision};
      if(b.dataset.selectCover){await publicationMutation("/api/publications/edit",{...base,cover_id:b.dataset.selectCover});toast("已选用封面；本版需重新核对")}
      else if(b.id==="publication-approve"){await publicationMutation("/api/publications/approve",{...base,revision_hash:job.current.hash});toast("本版发布包确认已保存；未上传或发布")}
      else{await publicationMutation("/api/publications/request-draft",base);toast("草稿任务已保存等待Codex，未自动操作平台")}
      b.disabled=false;
    }
  }catch(error){b.disabled=false;toast(error.message)}
});
