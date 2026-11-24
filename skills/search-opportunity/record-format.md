# 首页观察包

保存 UTF-8 JSON，再执行 `python homefeed.py record 文件.json`。`packet_id` 每一批唯一，重传同一批沿用 ID。计数必须来自真实操作；示例是假数据，不能写入真实任务。

```json
{
  "packet_id": "本批唯一ID",
  "session_id": "真实任务ID",
  "refreshes": 1,
  "cards": 18,
  "message": "本批真实进度和判断",
  "notes": [{
    "url": "真实完整原帖链接，含原有访问参数",
    "title": "原帖标题",
    "read_at": "2026-11-21T14:00:00+08:00",
    "decision": "keep",
    "reason": "保留原因",
    "opportunity": {
      "title": "统一的活动/计划名称（重复公告沿用名称）",
      "kind": "共创计划",
      "summary": "值得了解的价值，一两句",
      "evidence": [{"id":"notice","url":"实际原文链接","excerpt":"实际读取的必要原文片段","read_at":"2026-11-21T14:00:00+08:00","official":true,"authority_basis":"从主页认证/主办关系等实际看到的身份依据"}],
      "open_status": {"value":"open","evidence":{"source_id":"notice","quote":"原文中的开放说明"}},
      "deadline": {"label":"原公告的日期说明；年份/时区不明则写明"},
      "benefits": {
        "traffic":{"score":null,"reason":"未确认流量支持"},
        "cash":{"score":null,"reason":"未确认现金激励"},
        "commercial":{"score":null,"reason":"未确认商业合作"},
        "exposure":{"score":null,"reason":"未确认曝光安排"}
      },
      "preference_match": {"score":null,"reason":"未填写偏好或尚未评估"},
      "requirements":"实际条件；未写的写未知",
      "rights":"实际授权条款；未知则写未知",
      "entry_url":null,
      "uncertainties":["待确认事项"]
    }
  }]
}
```

`benefits` 必须恰好有四项。非 null 的 `score` 是0至5的整数，另加 `evidence: {"source_id":"notice","quote":"该正文中的短证据"}`。没有证据时 null，不用0代替未知。`open_status.value` 可为 `open/unknown/closed`，open/closed 需要官方引用；未知不冒充正在开放。

确切截止时间加 `deadline.at`（含时区）、`deadline.evidence`（同样引用原文）。没写年份或结束时刻不能猜。只有日期的用 label，保留不确定性。读取时间取实际当前时间。

观察包属于 `session_id` 绑定的探索项目，不再接受 `author`，也不建立作者档案。官方正文的 `authority_basis` 仍用于说明机会证据来源。

先保存候选，再执行明确授权的点赞收藏。保存回执时保持同一 read_at、原帖和机会字段，换一个 packet_id，不重复计算刷新或浏览卡片。

```json
"interactions": {
  "like": {"status":"performed","before":false,"after":true,"evidence":"按钮由未点赞变为已点赞的实际可见状态"},
  "collect": {"status":"already_done","before":true,"after":true,"evidence":"打开原帖时已显示已收藏"}
}
```

允许 `performed/already_done/failed/unknown/skipped`。成功必须有布尔前后状态和实际证据。只有当前开放且有正向官方价值依据的机会才能登记 performed。不允许 follow 字段。不能为了确认状态再点一次。

跳过内容仅需 url、title、read_at、decision: skip、reason，不加 opportunity 或已执行互动。历史观察在下一轮可读，避免反复打开已过期/不相关笔记。

用户偏好评分用 `preference_match`，score为0至5整数或null，说明与当前项目偏好具体如何匹配。没有偏好时只能为null。程序记录偏好版本，偏好改变后旧评分不再加分。

五项权重从任务的 `project.weights` 读取，总和100。默认 traffic=30、cash=25、commercial=20、exposure=15、preferences=10；用户可按项目修改，不能固定套用默认值。权益分仍引用官方证据。

不提交 asset_matches，不读取或理解素材，不将素材与项目的关联用于探索或评分。
