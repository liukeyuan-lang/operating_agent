let state, currentTab=workspaceKind==='publishing'?"publishing":"opportunities", currentFilter="all", currentDetail=null, currentAction=null, searchText="";
let requestPickedAssets=[],registeredPickedAssets=[];
const $=s=>document.querySelector(s);
const escape=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const time=value=>value?new Date(value).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false,timeZone:"Asia/Shanghai"}):"尚未检查";
const role={peer:"创作同行",organizer:"主办机构",information:"信息来源"};
const reviewName={new:"未标记",saved:"已保留",skipped:"暂不考虑"};
const runName={running:"收集中",completed:"本轮已完成",blocked:"访问受阻",interrupted:"已暂停",partial:"探索未充分",imported:"历史已读记录"};
const factName={eligibility:"报名资格",ai_policy:"AI作品政策",deadline:"截止时间",attendance:"到场要求",fees:"费用",formats:"作品规格",rights:"首发与授权",rewards:"奖励与资源",entry_url:"报名入口",open_status:"当前开放状态"};
const safeURL=value=>{try{
  let u=new URL(value);if(!['http:','https:'].includes(u.protocol))return '#';
  if(u.hostname==='xiaohongshu.com'||u.hostname.endsWith('.xiaohongshu.com')){
    const note=u.pathname.match(/\/(?:explore|search_result|discovery\/item)\/([a-f0-9]{24})\/?$/i)||u.pathname.match(/\/user\/profile\/[a-f0-9]{24}\/([a-f0-9]{24})\/?$/i);
    const key=note?'https://www.xiaohongshu.com/explore/'+note[1].toLowerCase():'https://www.xiaohongshu.com'+u.pathname.replace(/\/$/,'');
    const visit=state?.access_urls?.[key];if(visit)u=new URL(visit);
  }
  return ['http:','https:'].includes(u.protocol)?u.href:'#';
}catch{return '#'}};
const link=(url,label,cls="")=>'<a class="'+cls+'" href="'+escape(safeURL(url))+'" target="_blank" rel="noopener noreferrer">'+escape(label)+'</a>';
const badge=(text,tone="")=>'<span class="badge '+tone+'">'+escape(text)+'</span>';
const platformName=id=>state.platform_catalog.find(p=>p.id===id)?.name||"网页";
let platformFilter="all";
const onPlatform=row=>platformFilter==="all"||row.platform===platformFilter;
function platformPicker(){return '<label>平台 <select id="platform-filter"><option value="all">全部平台</option>'+state.platform_catalog.map(p=>'<option value="'+p.id+'" '+(platformFilter===p.id?'selected':'')+'>'+escape(p.name)+'</option>').join("")+'<option value="web" '+(platformFilter==="web"?'selected':'')+'>网页</option></select></label>'}
function platforms(){
  return hero("每个平台，分别观察与核验。","项目与素材共用；搜索证据、同行基线、文案、账号和发布记录区分平台。这里显示真实检查结果。","PLATFORMS / 平台与观察")
    +'<section class="panel"><h2>统一浏览器：Playwright MCP</h2><p>小红书、抖音和后续平台都通过独立 Chrome 收集；各平台需要在这个浏览器里分别登录。页面仍由 Agent 阅读和操作，工作台保存任务与结果。</p><p>启动“启动浏览器.py”，安装步骤见项目“部署与安装.md”。通道已接入和各平台实际验收状态分别记录。</p></section>'
    +'<div class="list-grid">'+state.platform_catalog.map(p=>'<section class="panel"><h2>'+escape(p.name)+'</h2><p>本地支持：探索记录、同行积累、内容发布包、账号与回执校验。</p><p>'+escape(p.copy_guidance)+'</p><p>封面模板 '+p.cover_width+'×'+p.cover_height+'；文案 '+p.title_budget+'/'+p.body_budget+' 字符为自定工作阈值，非官方限制。</p>'+p.checks.map(c=>'<div class="pub-check-row">'+badge({verified:"已实测",blocked:"受阻",untested:"待实测"}[c.status],c.status==="verified"?"green":"orange")+'<div><strong>'+escape(c.label)+'</strong><p>'+escape(c.note)+'</p>'+(c.checked_at?'<small>'+time(c.checked_at)+'</small>':'')+'</div></div>').join("")+'<p>'+link(p.home_url,"打开平台 ↗")+' · '+link(p.creator_url,"创作中心 ↗")+'</p></section>').join("")+'</div>'
    +'<section class="panel"><h2>观察样本与采样限制</h2><p>搜索摘要与实际原帖阅读分开。未知互动量留空；一次采样不能证明热度上升，不跨平台比较绝对点赞量。</p>'+(state.research_snapshots.length?[...state.research_snapshots].reverse().map(s=>'<details><summary>'+escape(platformName(s.platform)+' · '+s.query)+' · '+s.items.length+'条 · '+escape(s.source_type)+'</summary><p>'+escape(s.scope_note)+'</p><p>'+escape(s.sort+' · '+s.time_window)+' · '+time(s.observed_at)+'</p>'+s.items.map(i=>'<div class="evidence">'+link(i.url,i.title)+'<p>正文：'+(i.body_read?'已读':'未读')+' · 点赞 '+escape(i.metrics.likes??"未知")+' · 评论 '+escape(i.metrics.comments??"未知")+' · 分享 '+escape(i.metrics.shares??"未知")+'</p></div>').join("")+'</details>').join(""):'<p>还没有采集快照。</p>')+'</section>';
}

function toast(text){
  $("#toast").textContent=text; $("#toast").hidden=false;
  setTimeout(()=>{$("#toast").hidden=true},3500);
}
async function post(path,body){
  const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Demo-Token":state.csrf},body:JSON.stringify({workspace:workspaceKind,project_id:state?.current_project?.id,...body})});
  const data=await response.json(); if(!response.ok) throw Error(data.error||"保存失败"); return data;
}
async function refresh(force=false){
  try{
    const response=await fetch(apiURL("/api/state"));
    if(!response.ok) throw Error("无法读取记录");
    const data=await response.json(), changed=!state||data.revision!==state.revision||data.active_project_id!==state.active_project_id||JSON.stringify(data.stats)!==JSON.stringify(state.stats)||JSON.stringify(data.weekly_plan)!==JSON.stringify(state.weekly_plan);
    state=data;
    $("#connection").textContent="本地记录已连接";
    if(changed||force){
      if(!force&&currentTab==="publishing"&&publicationDirty){if($("#pub-stale-note"))$("#pub-stale-note").textContent="记录有新变化。当前未保存的输入已保留；保存时会检查版本，防止覆盖其他修改。"}
      else render();
    }
    else if(document.querySelector('#material-catalog'))loadMaterialCatalog();
  }catch(error){
    $("#connection").textContent="连接已断开，可重新启动本地界面";
    if(!state)$("#content").innerHTML='<div class="error-banner">无法读取本地记录，请确认服务已启动。</div>';
  }
}
function hero(title,description,eyebrow="FOLLOW A CLUE. FIND A POSSIBILITY."){
  return '<section class="hero"><div><div class="eyebrow">'+escape(eyebrow)+'</div>'+(title?'<h1>'+escape(title)+'</h1>':'')+(description?'<p>'+escape(description)+'</p>':'')+'</div></section>';
}
function stats(){
  return '<div class="stats">'+[
    [state.stats.results,"已验证机会","条"],
    [state.stats.library_leads,"搜索线索","条"],
    [state.stats.peers,"创作同行","位"],
    [state.stats.followups,"待继续的线索","条"]
  ].map(([n,l,unit])=>'<div class="stat"><div class="label">'+l+'</div><strong>'+n+'</strong><small>'+unit+'</small></div>').join("")+'</div>';
}
function runPanel(){
  const run=state.runs.at(-1);
  if(!run)return '<div class="empty"><strong>这个项目还没有探索记录</strong>填写探索要求后，Agent会自主选择检索词并沿线索继续搜索。</div>';
  const done=run.status!=="running";
  const readLabel=run.platforms.includes('web')?'正文':'原帖';
  const actual=[run.counts.searches>0,run.counts.post_reads>0||run.counts.source_checks>0,run.counts.official_reads>0,done];
  const searchLimit=run.limits?.searches??50,remaining=Math.max(0,searchLimit-run.counts.searches);
  const note=run.status==="partial"||run.status==="blocked"||run.status==="interrupted"?"本轮已停止，已保存进度和未完成事项。":run.status==="running"?"根据新线索继续探索，页面同步已保存进度。":"本轮已结束，搜索记录与核验结论已保存。";
  return '<section class="panel run-panel"><div class="run-title"><div><div class="eyebrow">LATEST EXPLORATION / 最近一轮</div><h3>'+escape(run.query)+'</h3><div class="run-meta">'+time(run.started_at)+' · 最多搜索 '+searchLimit+' 次 · 还可搜索 '+remaining+' 次</div></div>'+badge(runName[run.status]||run.status,run.status==="completed"?"green dot":"orange dot")+'</div>'
    +'<div class="steps">'+["自主选择检索词","沿线索深入","追溯原始公告","整理机会与评分"].map((n,i)=>'<div class="step '+(actual[i]?"complete":"")+'"><span>'+(actual[i]?"✓":"0"+(i+1))+'</span>'+n+(done&&!actual[i]?" · 未执行":"")+'</div>').join("")+'</div>'
    +'<div class="run-bottom"><span>搜索 '+run.counts.searches+' 次 · '+readLabel+' '+run.counts.post_reads+' 篇 · 同行/来源 '+run.counts.source_checks+' 个 · 官方正文 '+run.counts.official_reads+' 份</span><span>活动笔记新增 '+run.new_items+' / 补充 '+run.updated_items+' · 新增内容观察 '+(run.new_signals||0)+'</span></div>'
    +'<div class="run-summary">'+escape(note)+(run.summary?'<p>'+escape(run.summary)+'</p>':"")+'</div></section>';
}
function sortedItems(){
  const rank={strong:0,possible:1,weak:2};
  return [...state.items].filter(onPlatform).sort((a,b)=>(rank[a.fit]??3)-(rank[b.fit]??3)||b.updated_at.localeCompare(a.updated_at));
}
function card(item){
  const deadline=item.facts?.deadline?.value;
  const verified=item.bucket==='result',issues=item.qualification_issues||[],verification=item.verification||{};
  return '<article class="opportunity opportunity-card"><div class="card-top">'+badge(platformName(item.platform))+badge(verified?'已验证机会':'待验证机会',verified?'green':'orange')+(verification.status==='blocked'?badge('访问受阻','gray'):'')+'</div><h3>'+escape(item.title)+'</h3><p>'+escape(item.fit_reason)+'</p>'
    +(!verified?'<details class="opportunity-progress"><summary>核验进展与未确认事项'+(issues.length?' · '+issues.length+'项':'')+'</summary><p>'+escape(verification.attempt_note||'等待Agent查证官方条件')+'</p><ul>'+issues.map(issue=>'<li>'+escape(issue)+'</li>').join('')+'</ul></details>':'')
    +(item.next_action&&!verified?'<p class="opportunity-next"><strong>下一步：</strong>'+escape(item.next_action)+'</p>':'')
    +opportunityLinks(item)
    +'<div class="card-bottom"><span class="deadline">'+escape(deadline?'截止说明：'+deadline:'截止时间待核实')+'</span><button class="link-button" data-detail="'+escape(item.id)+'">查看详情与证据 ↗</button></div></article>';
}
function opportunityLinks(item){
  const rows=item.related_links||[];
  return '<div class="opportunity-links"><h4>相关链接</h4>'+(rows.length?'<ul>'+rows.map(row=>'<li><span class="origin">'+escape(row.kinds.join(' · '))+'</span>'+link(row.url,row.title+' ↗')+'<small>'+escape(row.host)+(row.access_status==='needs_refresh'?' · 完整访问链接待重新获取':'')+'</small></li>').join('')+'</ul>':'<p class="origin">尚未保存相关链接。</p>')+'</div>';
}
function pathPanel(){
  const item=[...state.items].sort((a,b)=>(b.discovery_path?.length||0)-(a.discovery_path?.length||0))[0];
  const paths=item?.discovery_path||[];
  return '<section class="panel"><div class="section-heading"><h2>一条线索如何展开</h2><small>实际发现路径</small></div>'+(paths.length?paths.map((node,i)=>'<div class="path-node"><div class="path-dot">'+(i+1)+'</div><div><h4>'+(node.url?link(node.url,node.label):escape(node.label))+'</h4><p>'+escape(node.reason||"")+'</p></div></div>').join(""):'<p class="origin">读到帖子、同行或机构后，新发现的关系会保存在这里。</p>')+'</section>';
}
function followupsPanel(){
  const follows=state.frontier.slice(0,3);
  return '<section class="panel"><div class="section-heading"><h2>可探索的入口</h2><small>候选示例 · AI自主选择</small></div>'+(follows.length?follows.map(f=>'<div class="followup"><strong>'+escape(f.title)+'</strong><p>'+escape(f.reason)+'</p><button class="link-button" data-lead="'+escape(f.id)+'">查看搜索入口 ↗</button></div>').join(""):'<p class="origin">还没有留下待追踪的线索。</p>')+'</section>';
}
function pendingRequests(){
  const requests=state.requests.filter(r=>r.status==="waiting_codex");
  if(!requests.length)return "";
  return '<div class="request-box"><strong>'+requests.length+' 个收集任务等待 Codex 执行</strong><p>'+requests.map(r=>escape(r.query)+" · "+escape(r.id)).join("<br>")+'</p><p>任务已保存。请在当前 Codex 对话中说“执行待处理收集任务”；此页面不自动操作外部平台。</p></div>';
}
function overview(){
  const p=state.weekly_plan;
  return hero("","","WEEKLY ACTIONS / 决定下一周做什么")
    +(p?'<div class="section-heading"><h2>'+escape(p.week_start)+' 起的一周</h2><a class="link-button" href="/api/actions.csv" download="每周行动卡.csv">导出行动卡 ↓</a></div>'
      +(p.issues.length?'<div class="error-banner">'+escape(p.issues.join("；"))+'</div>':"")
      +(p.scope_note?'<details class="quiet-note plan-scope"><summary>'+escape(p.assessment.topics.status==="insufficient"?"初版计划 · 当周话题探索未完成":"查看本轮计划范围与缺口")+'</summary><p>'+escape(p.scope_note)+'</p></details>':"")
      +p.actions.map(actionCard).join("")
      +(!p.actions.length?'<div class="empty"><strong>本轮没有值得新增投入的任务</strong>'+escape(p.no_action_reason)+'</div>':"")
      +'<details class="panel plan-assessment"><summary>为什么选这些事，以及暂时不做什么</summary><p>'+escape(p.summary)+'</p>'
      +Object.entries(p.assessment).map(([k,v])=>'<div class="assessment-row"><strong>'+({topics:"话题与时效",peers:"同行观察",opportunities:"资源机会",assets:"素材复用与缺口"}[k])+'</strong>'+badge(v.status==="reviewed"?"已评估":"证据不足",v.status==="reviewed"?"green":"orange")+'<p>'+escape(v.note)+'</p></div>').join("")
      +'<p>建议任务合计约 '+p.estimated_hours.min+'–'+p.estimated_hours.max+' 小时。'+escape(p.capacity_note)+'</p></details>'
      :'<div class="empty"><strong>还没有形成下周行动卡</strong>活动结果为 0 不代表没有内容可做。完成话题、同行、机会和素材判断后，Codex 会准备具体任务与材料。</div>')
    +pendingRequests()+'<details class="exploration-details panel"><summary>查看收集进度、线索与发现路径</summary>'+stats()+runPanel()+'<div class="columns">'+pathPanel()+followupsPanel()+'</div></details>';
}
function opportunities(){
  return hero('机会','已验证的机会与尚待判断的候选分开查看。相关链接保留来源，访问状态和条件以核验记录为准。','OPPORTUNITIES / 机会')
    +'<section class="opportunity-group" aria-labelledby="verified-heading"><div class="section-heading"><h2 id="verified-heading">已验证机会 · '+state.results.length+'</h2><a class="link-button" href="/api/export.csv?bucket=result" download="已验证机会.csv">导出已验证机会 ↓</a></div><p class="group-description">已核实当前开放、官方条件与项目适配。</p><div class="list-grid">'
    +(state.results.length?state.results.map(card).join(''):'<div class="empty">当前没有已验证机会。</div>')+'</div></section>'
    +'<section class="opportunity-group" aria-labelledby="pending-heading"><div class="section-heading"><h2 id="pending-heading">待验证机会 · '+state.pending_opportunities.length+'</h2></div><p class="group-description">目前还无法确认是否构成适合本项目的机会，等待继续查证。</p><div class="list-grid">'
    +(state.pending_opportunities.length?state.pending_opportunities.map(card).join(''):'<div class="empty">当前没有待验证机会。</div>')+'</div></section>';
}
function leads(){
  return hero("从这里，发现下一个好机会。","创作者、机构、话题、网站、作品和活动都可以成为搜索入口。Agent继续探索，你可以补充或删除线索。","DISCOVERY LIBRARY / 线索库")
    +'<div class="section-heading"><h2>'+state.lead_library.length+' 条搜索入口</h2><div class="detail-actions"><a class="link-button" href="/api/leads.csv" download="搜索线索.csv">导出线索 ↓</a><button class="button small" id="add-lead">＋ 手动添加</button></div></div>'
    +'<div class="toolbar">'+platformPicker()+[["all","全部线索"],...Object.entries(state.lead_kinds),["deleted","已删除"]].map(([k,l])=>'<button class="filter '+(currentFilter===k?"active":"")+'" data-filter="'+k+'">'+escape(l)+'</button>').join("")
    +'<input id="item-search" class="search-input" aria-label="搜索线索" placeholder="搜索名称、对象、搜索价值" value="'+escape(searchText)+'"></div><div id="item-list" class="list-grid"></div>';
}
function drawItems(){
  const all=(currentFilter==="deleted"?state.deleted_leads:state.lead_library).filter(onPlatform).filter(i=>{
    const match=["all","deleted"].includes(currentFilter)||i.kind===currentFilter;
    return match&&[i.title,i.target,i.reason,i.next_step].join(" ").toLowerCase().includes(searchText.toLowerCase());
  });
  $("#item-list").innerHTML=all.length?all.map(leadCard).join(""):'<div class="empty">当前筛选下没有线索。可以手动添加名字、链接或关键词。</div>';
}
const leadProgress={new:"待探索",explored:"已探索，可续搜",blocked:"访问受阻",watching:"持续观察",observed:"已发现内容",historical:"历史入口"};
const leadOrigin={manual:"手动添加",seed:"初始线索",agent:"AI探索积累"};
function leadButtons(row){return '<button class="button small" data-'+(row.deleted_at?'restore':'delete')+'-lead="'+escape(row.id)+'">'+(row.deleted_at?'恢复线索':'删除线索')+'</button>'}
function leadCard(row){
  return '<article class="opportunity lead-card"><div class="card-top">'+badge(row.kind_label)+badge(platformName(row.platform))+'<span class="origin">'+escape(leadOrigin[row.origin]||'探索积累')+'</span></div><h3>'+escape(row.title)+'</h3><p>'+escape(row.reason)+'</p><div class="lead-next"><strong>继续搜索</strong><p>'+escape(row.next_step)+'</p></div><div class="origin">'+escape(leadProgress[row.status]||row.status)+'</div><div class="card-bottom"><button class="link-button" data-lead="'+escape(row.id)+'">查看入口与发现路径 ↗</button>'+leadButtons(row)+'</div></article>';
}
function showLead(id){
  const row=[...state.lead_library,...state.deleted_leads].find(r=>r.id===id);if(!row)return;
  $('#detail-content').innerHTML='<div class="dialog-head">'+badge(row.kind_label)+'<button class="icon-button" data-close="detail-dialog" aria-label="关闭">×</button></div><h2>'+escape(row.title)+'</h2><dl class="facts"><dt>搜索对象</dt><dd>'+(row.url?link(row.url,row.target):escape(row.target))+'</dd><dt>搜索价值</dt><dd>'+escape(row.reason)+'</dd><dt>继续搜索</dt><dd>'+escape(row.next_step)+'</dd><dt>探索进度</dt><dd>'+escape(leadProgress[row.status]||row.status)+'</dd></dl>'
    +(row.summary?'<p>'+escape(row.summary)+'</p>':'')+(row.additional_reasons||[]).map(r=>'<p>'+escape(r)+'</p>').join('')
    +(row.decision_note?'<section class="detail-section"><h3>AI最近的取舍</h3><p>'+escape(row.decision_note)+'</p><small>'+time(row.decision_at)+'</small></section>':'')
    +'<section class="detail-section"><h3>发现路径</h3>'+(row.discovery_path.length?row.discovery_path.map(n=>'<div class="evidence">'+(n.url?link(n.url,n.label||n.url):escape(n.label))+'<p>'+escape(n.reason)+'</p></div>').join(''):'<p>手动提供或历史记录尚未附带路径。</p>')+'</section><div class="detail-actions">'+leadButtons(row)+'</div>';
  if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
}
function sources(){
  const peers=state.sources.filter(onPlatform).filter(s=>s.role==="peer");
  return hero("从同行的下一步，发现新的入口。","分清创作同行、主办机构与信息来源；记录为什么关注、读过什么，以及下一次是否出现新内容。","PEERS & SOURCES / 内部观察清单")
    +'<div class="section-heading"><h2>'+peers.length+' 位创作同行 · '+(state.sources.filter(onPlatform).length-peers.length)+' 个其他来源</h2><button class="button small" id="add-source">＋ 添加观察对象</button></div>'
    +'<div class="toolbar">'+platformPicker()+'</div><div class="quiet-note">观察清单不会自动关注任何平台账号。团队规模和发展阶段没有证据时，保留“尚未确认”。</div>'
    +'<div class="list-grid">'+(state.sources.filter(onPlatform).length?state.sources.filter(onPlatform).map(s=>'<article class="source-card">'+badge(platformName(s.platform))+' '+badge(role[s.role],s.role==="peer"?"green":"gray")+'<h3>'+escape(s.name)+'</h3><p>'+escape(s.reason)+'</p><p>阶段与规模：'+escape(s.similarity_note||"尚未确认")+'</p>'+link(s.url,"打开公开主页 ↗")+'<div class="source-info">最近检查 '+time(s.last_checked_at)+'<span class="source-count">积累 '+(s.seen_posts?.length||0)+' 篇</span></div>'+(s.latest_observation?'<p>'+escape(s.latest_observation)+'</p>':"")+'</article>').join(""):'<div class="empty">尚未登记观察来源。探索中发现的合适创作者会保存到这里。</div>')+'</div>';
}
function history(){
  return hero("每一步，都有来处。","保存读到了什么、为什么继续、哪里无法核实。新一轮不会清空已有积累。","EXPLORATION LOG / 可追溯的过程")
    +pendingRequests()+[...state.runs].reverse().map(run=>'<section class="panel history-run"><div class="section-heading">'+badge(runName[run.status]||run.status,run.status==="completed"?"green":"gray")+'<small>'+time(run.started_at)+' · '+escape(run.id)+'</small></div><h3>'+escape(run.query)+'</h3><p>'+escape(run.summary||"本轮进行中")+'</p>'
    +state.events.filter(e=>e.run_id===run.id).map(e=>'<div class="log"><time>'+time(e.at)+'</time><p>'+escape(e.message)+(e.url?' '+link(e.url,"↗"):"")+'</p></div>').join("")+'</section>').join("")
    +'<section class="panel"><div class="section-heading"><h2>人工备注与任务</h2></div>'+state.events.filter(e=>!e.run_id).slice(-12).reverse().map(e=>'<div class="log"><time>'+time(e.at)+'</time><p>'+escape(e.message)+'</p></div>').join("")+'</section>';
}
function render(){
  document.querySelectorAll('.material-timeout-note').forEach(e=>e.textContent=state.llm?.material_timeout_seconds?'当前素材请求网络超时阈值：'+state.llm.material_timeout_seconds+'秒。失败不会自动重发。':'重启工作台后可查看当前网络超时阈值。');
  document.querySelectorAll('.material-compression-note').forEach(e=>e.textContent=(state.llm?.compress_videos?'当前：大视频额外压缩已开启。':'当前：大视频额外压缩已关闭。')+'音视频按最长5分钟与单段体积上限切片；体积超限时，短视频也会切片。切片和格式转换会转码，原文件保留。');
  $("#sidebar-project").textContent=state.current_project.name;
  const options=state.projects.map(p=>'<option value="'+escape(p.id)+'" '+(p.id===state.current_project.id?"selected":"")+'>'+escape(p.name)+'</option>').join("");
  $("#project-picker").innerHTML=options;
  $("#project-run-count").textContent=workspaceKind==='publishing'?state.publications.length+" 个发布包":state.runs.length+" 轮历史 · "+state.items.length+" 条积累";

  $("#page-name").textContent={publishing:"发布准备",assets:workspaceKind==='publishing'?"素材与理解":"素材库",opportunities:"候选机会",leads:"线索库",sources:"同行与来源",platforms:"平台与观察",history:"探索记录"}[currentTab]||'探索记录';
  document.querySelectorAll("nav .nav").forEach(b=>b.classList.toggle("active",b.dataset.tab===currentTab));
  for(const [id,value] of [['#nav-items',state.stats.opportunities],['#nav-leads',state.stats.library_leads],['#nav-peers',state.stats.peers],['#nav-publications',state.stats.publications]]){if($(id))$(id).textContent=value}
  if($('#running-dot'))$('#running-dot').className=state.runs.some(r=>r.status==='running')?'running':'';
  $("#updated-at").textContent="最近保存 "+time(state.updated_at)+" · 北京时间";
  $("#content").innerHTML=({publishing,assets:workspaceKind==='publishing'?assets:materialLibraryView,opportunities:candidateView,leads,sources,platforms,history}[currentTab]||candidateView)();
  if(currentTab==="leads")drawItems();
  if(currentTab==='assets'&&workspaceKind==='publishing')loadMaterialCatalog();
  if(currentTab==="publishing")publicationLivePreview();
  document.querySelectorAll('a[href^="/api/"]').forEach(a=>{const path=a.getAttribute('href');if(!path.includes('workspace='))a.setAttribute('href',apiURL(path))});
}
function showDetail(id){
  const item=state.items.find(i=>i.id===id); if(!item)return; currentDetail=id;
  const html='<div class="dialog-head"><span class="eyebrow">OPPORTUNITY NOTE / 机会笔记</span><button class="icon-button" data-close="detail-dialog" aria-label="关闭详情">×</button></div><h2>'+escape(item.title)+'</h2>'
    +badge(platformName(item.platform))+" "+badge(candidateStatus[item.ranking.status],item.ranking.status==="matched"?"green":"orange")+' <span class="origin">'+escape(item.author||platformName(item.platform))+' · '+time(item.first_seen_at)+'</span>'
    +'<p>'+escape(item.summary||"尚未读取原帖全文；搜索结果只作为线索。")+'</p>'
    +candidateScoreDetails(item)
    +'<section class="detail-section"><h3>与探索要求的关系</h3><p>'+escape(item.fit_reason)+'</p><p>素材只影响排序。候选机会的具体资格、授权与提交条件仍需确认；不自动报名。</p></section>'
    +'<section class="detail-section"><h3>条件与证据</h3><dl class="facts">'+Object.entries(factName).map(([key,name])=>{const f=item.facts?.[key];return '<dt>'+name+'</dt><dd>'+escape(f?.value||"未核实")+'<small>'+escape(f?.status==="confirmed"?"有原始公告依据":f?"仍需核验":"暂不作假设")+'</small></dd>'}).join("")+'</dl></section>'
    +'<section class="detail-section"><h3>仍然不确定的事项</h3>'+[...new Set([...item.unknowns,...(item.qualification_issues||[])])].map(q=>'<p>• '+escape(q)+'</p>').join("")+'</section>'
    +'<section class="detail-section"><h3>原帖与原始公告</h3><p>'+link(item.url,platformName(item.platform)+"原帖 ↗")+'</p>'+(item.official_sources||[]).map(s=>'<div class="evidence">'+link(s.url,s.title||"原始公告 ↗")+'<blockquote>'+escape(s.excerpt)+'</blockquote><div>'+escape(s.authority_basis)+'</div><small>实际读取 '+time(s.read_at)+'</small></div>').join("")+'</section>'
    +'<section class="detail-section"><h3>发现路径</h3>'+(item.discovery_path||[]).map((p,i)=>'<div class="path-node"><div class="path-dot">'+(i+1)+'</div><div><h4>'+(p.url?link(p.url,p.label):escape(p.label))+'</h4><p>'+escape(p.reason||"")+'</p></div></div>').join("")+'</section>'
    +'<section class="detail-section"><h3>你的判断</h3><div class="detail-actions">'+[["saved","保留这条"],["skipped","暂不考虑"],["new","取消标记"]].map(([s,l])=>'<button class="button small '+(item.review.status===s?"saved":"")+'" data-review="'+s+'">'+l+'</button>').join("")+'</div><label for="review-note">备注（会随记录保存）</label><textarea id="review-note" maxlength="2000" placeholder="例如：这轮先不做，后续可复用静帧系列">'+escape(item.review.note||"")+'</textarea><button class="button small" id="save-note">保存备注</button></section>';
  $("#detail-content").innerHTML=html;
  if(!$("#detail-dialog").open)$("#detail-dialog").showModal();
}
document.addEventListener("click",async event=>{
  const target=event.target.closest("button"); if(!target)return;
  if(target.dataset.tab){
    if(currentTab==="publishing"&&publicationDirty){if(target.dataset.tab!=="publishing")toast("文案尚未保存。请先保存，或点击“重新载入”放弃修改后再切换。");return}
    currentTab=target.dataset.tab;render();window.scrollTo(0,0);
  }
  if(target.dataset.filter){currentFilter=target.dataset.filter;render()}
  if(target.dataset.detail)showDetail(target.dataset.detail);
  if(target.dataset.lead)showLead(target.dataset.lead);
  if(target.id==='add-lead'){
    $('#lead-kind').innerHTML=Object.entries(state.lead_kinds).map(([k,l])=>'<option value="'+k+'">'+escape(l)+'</option>').join('');
    $('#lead-dialog').showModal();
  }
  if(target.dataset.deleteLead||target.dataset.restoreLead){
    try{
      const restore=!!target.dataset.restoreLead;
      await post('/api/leads/'+(restore?'restore':'delete'),{id:target.dataset.restoreLead||target.dataset.deleteLead});
      if($('#detail-dialog').open)$('#detail-dialog').close();
      await refresh(true);toast(restore?'已恢复，可继续探索':'已删除，后续探索将跳过；可在已删除中恢复');
    }catch(error){toast(error.message)}
  }
  if(target.dataset.action)showAction(target.dataset.action);
  if(target.dataset.close)$("#"+target.dataset.close).close();
  if(target.id==="new-run"){
    if(workspaceKind==='publishing'){if(publicationDirty){toast("请先保存或放弃当前修改");return}openPublishingProjectDialog();return}
    if(currentTab==="publishing"&&publicationDirty){toast("请先保存或放弃当前发布包修改，再开始新探索");return}
    $("#request-success").textContent="";
    $("#request-project").innerHTML=state.projects.map(p=>'<option value="'+escape(p.id)+'">'+escape(p.name)+'</option>').join("");
    $("#request-project").value=state.current_project.id;
    document.querySelector('input[name="mode"][value="continue"]').checked=true;
    fillProjectForm();$("#new-dialog").showModal();
  }
  if(target.id==="add-source")$("#source-dialog").showModal();
  if(target.id==="add-asset"){registeredPickedAssets=[];$('#asset-picked-file').textContent='尚未选择文件';$('#asset-form').reset();$("#asset-dialog").showModal()}
  if(target.id==='pick-asset-file'){
    target.disabled=true;
    try{
      const result=await post('/api/assets/pick',{});
      if(result.files.length){
        if(target.id==='pick-request-assets'){
          for(const file of result.files)if(!requestPickedAssets.some(f=>f.path===file.path))requestPickedAssets.push(file);
          drawPickedAssets();
        }else{registeredPickedAssets=result.files;$('#asset-picked-file').textContent=result.files.map(f=>f.name).join('、')}
      }
    }catch(error){toast(error.message)}finally{target.disabled=false}
  }
  if(target.dataset.removePicked!==undefined){requestPickedAssets.splice(Number(target.dataset.removePicked),1);drawPickedAssets()}
  if(target.dataset.actionReview||target.id==="save-action-note"){
    try{
      const a=state.weekly_plan.actions.find(a=>a.id===currentAction);
      await post("/api/action-review",{plan_id:state.weekly_plan.id,action_id:a.id,status:target.dataset.actionReview||a.review.status,note:$("#action-note").value});
      await refresh(true);showAction(a.id);toast("已保存内部计划标记；未发布或报名");
    }catch(error){toast(error.message)}
  }
  if(target.dataset.review||target.id==="save-note"){
    try{
      const item=state.items.find(i=>i.id===currentDetail);
      await post("/api/review",{id:currentDetail,status:target.dataset.review||item.review.status,note:$("#review-note").value});
      await refresh(true);showDetail(currentDetail);toast("已保存到机会笔记");
    }catch(error){toast(error.message)}
  }
});
document.addEventListener("input",event=>{if(event.target.id==="item-search"){searchText=event.target.value;drawItems()}});
$('#lead-form')?.addEventListener('submit',async event=>{
  event.preventDefault();const button=event.target.querySelector('[type="submit"]');button.disabled=true;
  try{await post('/api/leads',Object.fromEntries(new FormData(event.target)));$('#lead-dialog').close();event.target.reset();currentFilter='all';await refresh(true);toast('已添加，下轮探索将读取这条入口')}
  catch(error){toast(error.message)}finally{button.disabled=false}
});
$('#request-form')?.addEventListener('submit',submitExplorationForm);
$("#source-form")?.addEventListener("submit",async event=>{
  event.preventDefault();const button=event.target.querySelector('[type="submit"]');button.disabled=true;
  try{await post("/api/sources",Object.fromEntries(new FormData(event.target)));$("#source-dialog").close();event.target.reset();await refresh(true);toast("已加入内部观察清单")}
  catch(error){toast(error.message)}finally{button.disabled=false}
});
function fillProjectForm(){
  resetExplorationPrompt();
  const mode=document.querySelector('input[name="mode"]:checked').value;
  $("#existing-project-field").hidden=mode==="new";
  const p=mode==="new"?{}:state.projects.find(p=>p.id===$("#request-project").value)||{};
  $("#project-name-input").value=p.name||"新探索";
  $("#project-requirements").value=p.exploration_requirements||DEFAULT_EXPLORATION_REQUIREMENTS;
  $("#request-seeds").value=(p.seed_keywords||DEFAULT_SEARCH_SEEDS).join('\n');
  $("#request-max-searches").value=p.max_searches??50;
  const team=p.team_profile||{};
  for(const key of ['name','country','city','nationality','applicant_type','minimum_age','budget_cny','can_travel','notes']){
    const el=document.querySelector('[name="team_'+key+'"]');if(el)el.value=team[key]??'';
  }
  const channels=state.discovery_platform_catalog||[...state.platform_catalog,{id:'web',name:'网页搜索'}];
  $("#request-platforms").innerHTML=channels.map(item=>'<label><input type="checkbox" name="platforms" value="'+item.id+'" '+((p.discovery_platforms||["xiaohongshu","douyin","web"]).includes(item.id)?'checked':'')+'> '+escape(item.name)+'</label>').join("");
}
function drawPickedAssets(){
  $('#request-picked-assets').innerHTML=requestPickedAssets.map((f,i)=>'<div class="picked-file"><span>'+escape(f.name)+'</span><button type="button" class="link-button" data-remove-picked="'+i+'" aria-label="移除'+escape(f.name)+'">移除</button></div>').join('');
}
document.addEventListener("change",async event=>{
  if(event.target.id==="platform-filter"){platformFilter=event.target.value;render()}
  if(event.target.name==="mode"||event.target.id==="request-project")fillProjectForm();
  if(event.target.id==="project-picker"){
    if(currentTab==="publishing"&&publicationDirty){event.target.value=state.active_project_id;toast("请先保存或放弃当前发布包的修改，再切换项目");return}
    try{await post("/api/project/select",{project_id:event.target.value});pageProjectId=event.target.value;selectedPublication=null;currentTab=workspaceKind==='publishing'?'publishing':'opportunities';currentFilter="all";searchText="";await refresh(true)}
    catch(error){toast(error.message)}
  }
});
const actionKind={content:"内容准备",opportunity:"机会准备",prepare:"素材补充/复用",verify:"机会核验"};
const actionReview={pending:"建议待看",kept:"本周保留",deferred:"已暂缓"};
const list=rows=>'<ul class="plain-list">'+(rows||[]).map(t=>'<li>'+escape(t)+'</li>').join("")+'</ul>';
function actionCard(a,index){
  return '<article class="action-card '+(a.review.status==="deferred"?"deferred":"")+'"><div class="card-top"><span>'+badge(index===0?"主推荐 · "+actionKind[a.kind]:actionKind[a.kind],"green")+'</span>'+badge(actionReview[a.review.status],"gray")+'</div>'
    +'<h2>'+escape(a.title)+'</h2>'
    +(a.issues.length?'<div class="error-banner">'+escape(a.issues.join("；"))+'</div>':"")
    +'<dl class="action-fields"><dt>何时处理</dt><dd>'+time(a.scheduled_at)+' <small>北京时间 · 建议排期</small></dd><dt>准备状态</dt><dd>'+escape(a.preparation)+'</dd><dt>需要确认</dt><dd>'+escape(a.confirmations.join("；"))+'</dd></dl>'
    +'<div class="action-foot"><span>预计 '+a.effort_hours.min+'–'+a.effort_hours.max+' 小时</span><div class="pub-buttons">'+(a.kind==='content'?'<a class="button primary small" href="/publish">到发布页面准备 →</a>':'')+'<button class="button small" data-action="'+a.id+'">查看任务与依据</button></div></div></article>';
}
function assetCard(a){
  const s=a.specs||{};
  return '<article class="source-card">'+badge(a.file_available?"本地文件已读取":a.availability==="local"?"文件需重新定位":"网页参考",a.file_available?"green":"orange")+'<h3>'+escape(a.title)+'</h3>'
    +(a.file_available?materialPreview(a):'')
    +'<p class="file-locator">'+escape(a.locator)+'</p><p>'+(s.duration_seconds!=null?s.duration_seconds+' 秒 · ':"")+(s.width&&s.height?s.width+' × '+s.height+' · ':"")+(a.file_signature?(a.file_signature.size/1000000).toFixed(1)+' MB':"")+'</p>'
    +'<p>权属：'+(a.rights==="cleared"?"已记录授权":"待确认")+' · 发布历史：'+(a.published===true?"已公开":a.published===false?"未公开":"待确认")+'</p><details><summary>文件版本与读取说明</summary><p class="file-locator">'+escape(a.version)+'</p><p>'+escape(a.notes)+'</p></details></article>';
}
function assets(){
  return hero("素材与理解","查看整组素材及共享的目录理解记录。文件内容未变时，探索与发布直接复用。","MATERIALS / 素材目录")
    +understandingPanel()+'<div class="section-heading"><h2>'+state.assets.length+' 份项目素材</h2></div><div class="list-grid">'+state.assets.map(assetCard).join('')+'</div>'
    +'<section class="panel material-catalog"><h2>素材目录与理解对应表</h2><div id="material-catalog">读取记录中…</div></section>';
}
function showAction(id){
  const p=state.weekly_plan,a=p?.actions.find(a=>a.id===id);if(!a)return;currentAction=id;
  const pack=a.package;
  $("#detail-content").innerHTML='<div class="dialog-head"><span class="eyebrow">WEEKLY ACTION / 可检查的准备内容</span><button class="icon-button" data-close="detail-dialog" aria-label="关闭行动详情">×</button></div><h2>'+escape(a.title)+'</h2>'
    +badge(actionKind[a.kind],"green")+' '+badge(actionReview[a.review.status],"gray")+'<p>建议 '+time(a.scheduled_at)+' 处理；约 '+a.effort_hours.min+'–'+a.effort_hours.max+' 小时。'+escape(a.preparation)+'</p>'
    +(a.issues.length?'<div class="error-banner">'+escape(a.issues.join("；"))+'</div>':"")
    +'<section class="detail-section"><h3>为什么值得做</h3><p>'+escape(a.reason)+'</p></section>'
    +'<section class="detail-section"><div class="section-heading"><h3>已准备的文案与任务材料</h3><a class="button small" href="/api/action-package?plan_id='+p.id+'&action_id='+a.id+'" download="'+escape(a.key)+'.md">下载完整准备包 ↓</a></div>'
    +[["title","标题"],["body","正文草稿"],["cover_brief","封面方案（尚未出图）"],["brief","核验/制作说明"]].filter(([k])=>pack[k]).map(([k,label])=>'<h4>'+label+'</h4><div class="prepared-copy">'+escape(pack[k])+'</div>').join("")
    +(pack.tags?'<p>标签建议：'+escape(pack.tags.join(" "))+'（未声明热度）</p>':"")+'<p>平台草稿：尚未填写。账号：'+escape(pack.account||"尚未确定")+'。本页标记不会发布或提交。</p></section>'
    +'<section class="detail-section"><h3>要用哪些素材</h3>'+(a.material_details.length?a.material_details.map(assetCard).join(""):'<p>这是内部核验任务，暂不制作新媒体。</p>')+'</section>'
    +'<section class="detail-section"><h3>一份素材还能做什么</h3>'+list(a.reuse)+'</section>'
    +'<section class="detail-section"><h3>执行步骤</h3>'+list(a.steps)+'<h3>剩余工作与人工操作</h3>'+list(a.remaining_work)+'</section>'
    +'<section class="detail-section"><h3>需要确认</h3>'+list(a.confirmations)+'<h3>风险与不确定性</h3>'+list(a.risks)+'</section>'
    +'<section class="detail-section"><h3>推荐依据与原始入口</h3>'+a.sources.map(s=>'<div class="evidence"><strong>'+(s.url?link(s.url,s.title):escape(s.title))+'</strong><p>'+escape(s.note)+'</p>'+(s.evidence||[]).map(e=>'<p>'+link(e.url,e.title)+' · 读取 '+time(e.read_at)+'</p><blockquote>'+escape(e.excerpt)+'</blockquote>').join("")+(s.type==="item"?'<button class="link-button" data-detail="'+s.id+'">展开机会核验记录 ↗</button>':"")+'</div>').join("")+'</section>'
    +'<section class="detail-section"><h3>内部计划标记</h3><p>只影响后续推荐，不构成发布、报名或联系的授权。相同任务的暂缓理由会保留。</p><div class="detail-actions">'+[["kept","本周保留"],["deferred","暂缓"],["pending","取消标记"]].map(([s,l])=>'<button class="button small" data-action-review="'+s+'">'+l+'</button>').join("")+'</div><label for="action-note">备注</label><textarea id="action-note" maxlength="2000">'+escape(a.review.note)+'</textarea><button class="button small" id="save-action-note">保存行动备注</button></section>';
  if(!$("#detail-dialog").open)$("#detail-dialog").showModal();
}
$("#asset-form")?.addEventListener("submit",async event=>{
  event.preventDefault();const button=event.target.querySelector('[type="submit"]');button.disabled=true;
  try{
    if(!registeredPickedAssets.length)throw Error('请先选择素材文件');
    await post('/api/assets/batch',{...Object.fromEntries(new FormData(event.target)),paths:registeredPickedAssets.map(f=>f.path),project_id:state.active_project_id});
    $("#asset-dialog").close();event.target.reset();registeredPickedAssets=[];await refresh(true);toast('素材已登记；原文件保留在原位');
  }
  catch(error){toast(error.message)}finally{button.disabled=false}
});
refresh();setInterval(()=>refresh(),3000);
