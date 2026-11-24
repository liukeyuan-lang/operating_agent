// Component smoke test, deliberately without a browser/network. Not visual QA.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const fixture=JSON.parse(fs.readFileSync(0,'utf8')),elements=new Map();
const element=selector=>{
  if(!elements.has(selector))elements.set(selector,{value:'',innerHTML:'',textContent:'',className:'',addEventListener(){},classList:{toggle(){}}});
  return elements.get(selector);
};
const context=vm.createContext({fixture,assert,URL,URLSearchParams,window:{location:{search:''}},
  document:{addEventListener(){},querySelector:element,querySelectorAll(){return []}},setTimeout(){},setInterval(){}});
vm.runInContext(fs.readFileSync('ui/publishing.js','utf8'),context);
vm.runInContext(fs.readFileSync('ui/materials.js','utf8'),context);
vm.runInContext(fs.readFileSync('ui/discovery.js','utf8'),context);
vm.runInContext(fs.readFileSync('ui/app.js','utf8').replace('refresh();setInterval(()=>refresh(),3000);',''),context);
vm.runInContext(`
  state=fixture;
  const visitURLs=state.access_urls;
  state.access_urls={...visitURLs,'https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa':'https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=fixture-signed&xsec_source=pc_search'};
  assert.equal(new URL(safeURL('https://www.xiaohongshu.com/search_result/aaaaaaaaaaaaaaaaaaaaaaaa')).searchParams.get('xsec_token'),'fixture-signed');
  assert(!safeURL('https://www.xiaohongshu.com/explore/bbbbbbbbbbbbbbbbbbbbbbbb').includes('fixture-signed'));
  state.access_urls=visitURLs;
  for(const tab of ['publishing','platforms','assets','opportunities','leads','sources','history']){currentTab=tab;render();assert(document.querySelector('#content').innerHTML.length>100,tab)}
  currentTab='opportunities';render();const opportunitiesHtml=document.querySelector('#content').innerHTML;
  assert(opportunitiesHtml.includes('候选机会'));assert(opportunitiesHtml.includes('现金激励 25'));
  assert.equal(document.querySelector('#page-name').textContent,'候选机会');
  currentTab='assets';render();assert(document.querySelector('#content').innerHTML.includes('添加素材包'));
  assert(!document.querySelector('#content').innerHTML.includes('登记本地素材'));
  for(const item of [...state.results,...state.pending_opportunities]){
    const html=card(item);assert(html.includes(item.bucket==='result'?'已验证机会':'待验证机会'));
    for(const row of item.related_links)assert(html.includes('href="'+escape(safeURL(row.url))+'"'));
  }
  selectedPublication=null;if(state.assets.some(a=>a.file_available)){assert(publishing().includes('value="douyin"'));assert(publishing().includes('value="xiaohongshu"'));}else{assert(publishing().includes('登记素材'));}
  const dy=state.publications.find(j=>j.platform==='douyin');if(dy){selectedPublication=dy.id;currentTab='publishing';render();
  const html=document.querySelector('#content').innerHTML;
  const chosenCover=dy.covers.find(c=>c.id===dy.current.cover_id);
  const expectedSize=chosenCover?.style==='frame'?chosenCover.width+'×'+chosenCover.height:'1080×1920';
  assert(html.includes('抖音账号公开主页'));assert(!html.includes('小红书账号公开主页'));assert(html.includes(expectedSize));
  publicationLivePreview();assert(document.querySelector('#pub-title-count').textContent.includes('/ 30'));assert(document.querySelector('#pub-body-count').textContent.includes('/ 500'));
  }
  document.querySelector('input[name="mode"]:checked').value='new';fillProjectForm();assert(document.querySelector('#request-platforms').innerHTML.includes('value="douyin"'));
  assert(document.querySelector('#request-platforms').innerHTML.includes('value="web"'));
  assert(document.querySelector('#request-platforms').innerHTML.includes('网页搜索'));
  assert.equal(document.querySelector('#project-name-input').value,'新探索');
  assert.equal(document.querySelector('#request-max-searches').value,50);
  assert.equal(document.querySelector('#project-requirements').value,DEFAULT_EXPLORATION_REQUIREMENTS);
  assert.equal(document.querySelector('#request-seeds').value,DEFAULT_SEARCH_SEEDS.join(String.fromCharCode(10)));
  const control={disabled:false,dataset:{}},close={disabled:false,dataset:{close:'dialog'}};
  const form={querySelectorAll:()=>[control,close],setAttribute(){},removeAttribute(){}};
  const oldSession=beginMaterialForm(form);assert(control.disabled);assert(!close.disabled);
  cancelMaterialForm(form);assert(!control.disabled);assert(!oldSession.current());
  const newSession=beginMaterialForm(form);oldSession.finish();assert(control.disabled);assert(newSession.current());
  newSession.finish();assert(!control.disabled);
  const progressSample={status:'running',progress:{stage:'file',files_complete:0,files_total:2,file_name:'视频.mp4',segment_index:2,segments_total:3,segments_complete:1,started_at:new Date(Date.now()-62000).toISOString(),request:{phase:'uploading',request_bytes:1048576,uploaded_bytes:524288,request_started_at:new Date(Date.now()-2000).toISOString()}}};
  let progressText=materialProgressText(progressSample);
  assert(progressText.includes('当前：视频.mp4'));assert(progressText.includes('切片 2/3'));assert(progressText.includes('0.50 / 1.00 MiB（50%）'));assert(progressText.includes('1分'));
  progressSample.progress.request.phase='waiting_output';progressText=materialProgressText(progressSample);
  assert(progressText.includes('等待模型输出'));assert(progressText.includes('未提供处理百分比'));
  progressSample.status='unknown';progressSample.updated_at=new Date().toISOString();
  assert(materialProgressText(progressSample).includes('中断时步骤'));
`,context);
process.stdout.write('All view render checks passed; browser visual QA not performed.\n');
