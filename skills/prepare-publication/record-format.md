# 发布包接口

保存JSON到data/observations，再执行 `python demo.py publication 操作 文件.json`。数据为workspace.json的publication_jobs，按project_id隔离，沿用备份和原子保存。

## 创建与编辑

- create输入asset_id和platform（xiaohongshu/douyin，默认小红书）；或plan_id/action_id引用当前项目content行动。同平台、同来源、同素材版本的未结束任务复用。跨平台仅关联事实依据，文案先留空等待单独准备，禁止自动照搬。
- edit必填id、expected_revision（上次读到的current.number）。可写title/body/tags（#开头数组）、account_name/account_url（必须为对应平台公开主页）、scheduled_at（可选，带时区ISO）、cover_id。
- title_candidates是少量title/method/reason/tradeoff对象；brief是内容简报字典；editorial_review是check/note数组。只写实际依据和未知，不伪造平台自检通过。
- platform_evidence记录对应平台原始创作中心地址url（creator.xiaohongshu.com或creator.douyin.com）、read_at、excerpt、max_video_seconds/max_video_bytes及scope_note/screenshot；限制只能来自实际读取，拒绝跨平台复用。
- checks为用户对media/rights/history/copy/platform的核对布尔值，Agent不得代填。实质变化会清除核对并使确认失效；版本冲突拒绝覆盖。

## 封面

cover必填id、expected_revision、frame_seconds、headline（24字内，可换行）、subtitle（40字内）。小红书模板1080×1440、抖音模板1080×1920，输出PNG和原帧，记录源版本、时间点与哈希；形成新版本，不改写原片。模板不代表官方要求。先实际读画面，再选时点。

## 确认与回执

用户在界面核对并确认。CLI不提供代替用户确认的命令。确认范围仅是发布包检查，不等于正式发布或未来授权。

“保存给Codex的草稿填写任务”生成task_id与revision_hash，execution=waiting_codex；网页不会自行操作浏览器。待用户要求执行且授权匹配后继续Skill。

execution输入id/expected_revision/kind/note：

- draft_filled：实际平台核查后，evidence需source:platform_ui、匹配account_url、真实screenshot本机文件。测试夹具不得进入业务记录。
- draft_blocked/draft_unknown：记录真实阻塞/不明结果，未知不盲目重试。
- published_reported：人工登记小红书已发笔记url，保留manual_report来源并回写素材历史。
- unknown：发布结果不明，先查平台记录。

## 导出

data/发布准备.csv与data/publications/包id/的publication.json、发布包说明.md、title.txt、body.txt便于查看。ZIP按需包含原片、PNG、文案及版本清单，并校验真实文件哈希，不反复在工作目录复制大视频。
