# Playwright MCP 浏览器

当前首页探索使用用户已登录的小红书账号。操作普通可见网页，不读取 Cookie、不调用平台私有接口、不复制登录资料。项目 profile 在 data/browser-profile，不能与第二个浏览器实例同时使用。

## 连接

先执行 `node browser.mjs tools` 和 `node browser.mjs snapshot`。已连接就复用当前会话；没连接再运行 `python 启动浏览器.py` 或 `node browser.mjs serve`，缺依赖看部署与安装.md。服务在 127.0.0.1:8931/mcp，保持窗口运行。浏览器登录与 Codex 内置浏览器分别管理。

客户端命令：

- `node browser.mjs tools`：实际工具及参数，不能假定旧版本参数名。
- `node browser.mjs open URL`：打开网页；首页使用 https://www.xiaohongshu.com/explore 。
- `node browser.mjs snapshot data/browser-output/current.yml`：保存最新可访问性快照。
- `node browser.mjs call 工具名 参数.json`：按实际 schema 编写 JSON 参数。浏览器动作依据当前快照或已观察到的 DOM。

项目通过真实 Microsoft MCP SDK 串行复用一个浏览器会话；不要同时让多个 Agent 操作。HTTP/CLI 客户端复用该会话和 ref，不另建抓取器，不搬运登录。

## 首页和原帖

先列出现有标签，确认所需账号仍已登录。登录、协议和验证码由用户处理；不要自动切换账号或绕过平台限制。

首页初次快照可能是骨架，等实际推荐卡片出现再读。刷新要保持正常阅读节奏，不能快速高频刷新。标题仅帮助筛选，必须进入原帖阅读正文和必要海报，记录实际已读范围；看到视频页面不代表已看完整片或听过音轨。

首页入口按 search-opportunity Skill，不使用旧站内搜索和 Frontier。只有直接官方正文的跟进用于核验，不用页面里的“猜你想搜”替代推荐探索。

## 点赞收藏

是否可以操作由本轮业务任务授权决定。首页探索任务明确允许时：先核对笔记 ID 和当前按钮状态，只对筛选出的好机会点赞、收藏；已完成则跳过。每次点击后重新读取成功状态，再写回执。状态不明或网络中断不自动重试。绝不点击任何关注、回关或互关按钮。

本次实测小红书原帖点赞图标未选中为 #like_b、已选中为 #liked；收藏未选中为 #collect、已选中为 #collected。这里只是已观察到的当前版本例子，操作时仍需检查 DOM/截图；class 中 like-active 本身不代表已点赞。数字必须先核对标签，不能按位置猜含义或为了读取计数而点击。

报名、上传、发布、评论、私信、支付另需授权。可点击不代表可执行所有对外动作。

## 真实链接和恢复

小红书实际原帖链接带 xsec_token、xsec_source 等访问参数。业务去重只按笔记 ID，保存入口要保留真实完整链接，不能用另一篇笔记的 token 拼接，也不能使用日志中的 <redacted> 占位符导航。来源链接来自首页实际 href 或当前 location。

如果 MCP 输出已脱敏，在当前已加载的页面通过普通 DOM 读取 location 的 origin、pathname 与 searchParams 条目，在本机重组成同一链接，存入不随源码交付的 data。保持日志脱敏，不读取 Cookie。签名可能失效，届时重新从实际首页卡片获取，裸链接失败不证明笔记已删除。

连接失败先检查现有服务； ref 失效重新快照；电脑休眠或网络断开后先核对页面和已保存的互动回执，不能盲目重发。只做少量有依据的重试，不修改证书、代理或安全设置。

真实调用、快照和截图在 data/browser-output，仅作为本机记录，不随源码交付。发现与核验记录保存实际读取时间、短原文、来源和未知事项，不能用测试夹具代替真实浏览。
