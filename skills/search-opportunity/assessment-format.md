# 候选机会评估格式

命令 `python demo.py assess --file 文件.json`，不联网或调用模型。先record/verify保存实际官方原文。下例仅说明结构：

```json
{
  "id":"当前机会ID",
  "requirements":[
    {"requirement":"非排他性的共创计划","status":"pass","reason":"公告明确共创且无独家要求","evidence":{"source_id":"official","quote":"必须是官方excerpt中的实际文字"}},
    {"requirement":"正在开放的","status":"unknown","reason":"尚未确认当届开放"}
  ],
  "benefits":{
    "traffic":{"score":null,"reason":"未找到明确流量扶持条款"},
    "cash":{"score":null,"reason":"现金机制待确认"},
    "commercial":{"score":null,"reason":"合作资源待确认"},
    "exposure":{"score":null,"reason":"曝光资源待确认"}
  },
  "asset_matches":[]
}
```

requirements按探索要求非空行顺序逐项填写，去掉数字编号后原文保持一致。status为pass/fail/unknown，pass或fail须官方证据。要求改变后旧评估失效。官方日期已过或已关闭直接排除；证据过期退回待确认。

benefits四项齐全，score为0—5整数或null，都写reason。已知分数（含0）须evidence.source_id/quote，quote是对应official_sources.excerpt的子串，实际读取在7天内且非未来。缺证据填null，不能用0冒充已确认不提供。

| 分数 | 一致尺度 |
|---|---|
| null | 未确认，暂不加分 |
| 0 | 官方明确不提供该项权益 |
| 1 | 明确但范围有限的资源，如可能转发或少量条件激励 |
| 2 | 有具体资源和规则，覆盖或确定性较有限 |
| 3 | 明确扶持机制、激励规则或合作通道，价值可说明 |
| 4 | 多项具体资源或持续支持，条件明确且价值较强 |
| 5 | 非常强的具体资源，须写出支持程度与限制，不凭名气或奖金总池 |

traffic看推荐/投流/账号扶持；cash看补贴、稿酬、奖金，区别普惠报酬、条件激励和仅获奖者奖金；commercial看付费合作/品牌/客户/商业通道；exposure看展示、传播、机构渠道及增长资源。同一权益避免多维重复放大。不把总奖金当预计收入，不推测获奖概率。

总分=traffic/5×30+cash/5×25+commercial/5×20+exposure/5×15+最佳素材匹配/5×10。未知不加分，显示已知依据覆盖比例；尚未评估为待评分。

素材匹配条目为 `{ "pack_id":"素材库ID", "analysis_id":"理解版本", "score":3, "reason":"具体内容、主题或媒介如何适配该机会" }`。可多包，仅取最高分。0为已看过但不匹配，未评估不填条目。无素材也能成为候选；删除包/理解版本变化只使匹配加分失效，不改变要求判断或权益分。权属未知另记，不擅自确认可投稿。
