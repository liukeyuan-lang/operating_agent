# 历史计划CLI的数据格式

仅供维护已有计划记录和 `demo.py plan` 使用；探索任务按 search-opportunity Skill 执行。

用 `python demo.py status` 取得当前项目id、profile_digest、next_week_start、素材id/version与已保存的机会/观察id。新计划必须绑定当前项目资料，引用其他项目会被拒绝。主数据仍是workspace.json，无新增数据库或调度器。

将JSON保存到data/observations，再运行 `python demo.py plan 路径`。代码负责字段、关联、素材版本、活动资格和日期校验，不代替Agent判断值得做什么。每次保存增加计划版本，保留过去的计划；界面显示最近一版。

顶层：

- project_id、profile_digest：当前项目；资料改变后旧计划提示重评。
- week_start：目标周一，建议用next_week_start。
- run_ids：支撑本计划的真实轮次id数组；不能伪造新搜索计数。
- scope_note：若尚未完成完整探索，直接说明实际覆盖和缺口。
- summary：为什么选这些、放弃什么、产能/预算是否未知。
- assessment：topics、peers、opportunities、assets各有status（reviewed/insufficient）和note。reviewed仅表示已经评估，不等于所有资格满足或热点已证实。
- actions：最多3项，不能为凑数增加工作。空数组需no_action_reason，说明没有值得新增投入的任务。

actions每项：

    {
      "key": "same-purpose-across-weeks",
      "kind": "content|prepare|opportunity|verify",
      "title": "具体建议做什么",
      "scheduled_at": "目标周内带时区的ISO处理时间",
      "reason": "契合、复用、价值和增量投入的取舍",
      "basis": [{"type":"project|item|signal", "id":"当前项目的真实id"}],
      "materials": [{"asset_id":"素材id", "version":"确切版本", "purpose":"用途"}],
      "effort_hours": {"min":0.5, "max":1},
      "reuse": ["一份素材的具体其他用途，条件未知要说明"],
      "steps": ["可以照做的步骤"],
      "remaining_work": ["还没有完成的工作，含复制字段/找媒体等人工步骤"],
      "confirmations": ["需要的具体决策，无需确认也如实说明"],
      "risks": ["素材、热度、时间或资格的不确定性"],
      "timely": false,
      "package": {"brief":"内部任务说明或清单", "platform_draft":"not_filled"}
    }

kind=content必须有具体素材，并在package写platform、title、body、tags数组、cover_brief，可选account。缺文件/规格而推荐先补素材时用prepare。cover_brief仅是方案，不能称成图已制作。kind=opportunity必须引用当前真正可参加的item；未知条件用verify。timely=true的选题依赖新鲜signal证据，过期后提示重查；常青作品介绍不要标时效选题。

本demo不调用发布端。内部“本周保留/暂缓”会保存反馈，不是正式发布/报名授权。绑定账号、确切素材和文案的外部确认留到实际执行时。准备包可在详情下载，也保存在data/plans/计划id/行动key.md；CSV每次保存后更新。
