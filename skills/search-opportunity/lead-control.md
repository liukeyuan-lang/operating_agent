# 维护待探索线索

线索是帮助发现机会的入口，不是需要人工逐条核验的机会列表。`frontier` 是常用待探索项，`lead_library` 还包含其他状态；展示顺序不决定下一步。由你结合探索要求、已读证据、新颖性、时效和潜在价值选择分支，素材只用于最后的机会排序。

任务入口 `python demo.py task TASK_ID --begin` 已选中正确项目。线索写操作带本轮 `run_id`；若网页切换了项目，先重新打开原任务，不要换ID绕过项目检查。

```text
python demo.py lead list
python demo.py lead add --file data/observations/新线索.json
python demo.py lead update --file data/observations/线索调整.json
python demo.py lead delete --file data/observations/线索剪枝.json
python demo.py lead restore --file data/observations/恢复线索.json
```

## 添加入口

JSON包含 `title/kind/target/reason`，可加 `run_id/next_step/parent_url`。目标可为名字、关键词或HTTP(S)链接；写清为何有助于找到好机会、下一步查哪里。保存入口不等于已阅读，也不增加搜索次数。

| `kind` | 入口 |
|---|---|
| `creator` | 创作者或工作室 |
| `organization` | 主办方、平台、品牌或机构 |
| `topic` | 话题或搜索词 |
| `website` | 网站、社区或聚合入口 |
| `work` | 作品或案例 |
| `opportunity` | 活动或合作线索，包括可引出新来源的旧活动 |
| `other` | 其他有搜索价值的入口 |

`config/initial-leads.json` 保存全局默认网站入口，项目创建或开始时自动补入；`lead seed` 可补当前项目尚未加入的项。种子不是强制任务，不带“已读/已核验”证明，不覆盖判断或复活删除项。不要把某项目的一次取舍写回全局配置。

## 调整、剪枝和恢复

`update` 需要 `id/decision`，可更新 `title/kind/reason/next_step/status`，其中 `decision` 说明这次取舍。改成另一个搜索对象时新增入口，不改写旧目标。ID可能随汇总变化，后续使用返回的新ID或重读列表。

状态为：`new`（待探索）、`watching`（持续观察）、`explored`（已探索）、`blocked`（访问受阻）、`observed`（已有观察）、`historical`（历史入口）。只有实际读过或受阻才写对应状态。

`delete/restore` 需要 `id/decision`，可附 `run_id`。AI删除是可逆剪枝，不破坏原始证据；可以根据新证据恢复自己的剪枝。**用户删除只由用户恢复**，不能通过重新发现或补种子绕过。一次加载失败可先标受阻，不必删除整个来源。

每次切换或剪枝写具体理由，不必虚构优先级分数。保留有价值但未读完的分支，下一轮继续。只受本轮最大搜索次数约束，不按时间、阅读量或来源数结束；是否继续由线索价值决定。
