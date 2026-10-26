"""阶段7（生产观测与告警）quickstart 演示数据集；可重复运行（幂等）。

种子围绕一位客户（赵文博 / 蓝海水产）与两个演示 Agent（全链路 / 精简注入），
让 quickstart 启动后「可观测性 → 记忆」页的 7 个指标组与「记忆告警」列表
立即有真实形状的数据可看：

- 任务健康：memory_tasks 覆盖全部四种 kind（conversation_summary /
  memory_extract / event_write / reinforce）——多条 done 带 duration_ms
  （55–900ms 梯度，avg/P95 有区分度）、两条最近 failed（带 duration_ms 与
  error，updated_at 在 15 分钟之前，因此不触发 R1）、以及一条 created_at
  回拨约 70 分钟的 pending memory_extract。
- **刻意的 R2 触发设计（FEATURE）**：那条 pending 任务的 run_after 被设在
  未来 24 小时（attempts=1、带 retry 错误，形如"重试退避中卡住的队列"），
  而不是回拨到过去——若 run_after<=now()，内嵌 worker 会在启动后第一个
  claim 循环就把它领走执行，pending 状态消失，R2 永远不会触发。保持
  "pending 且不可领取"，内嵌告警扫描器启动后第一个扫描周期就会因
  oldest_pending_age（约 70 分钟 > 默认阈值 60 分钟）真实触发一条
  memory.alert.pending_task_age 告警，端到端演示告警管线。
- 维护健康：ttl_purge / injection_log_purge / decay / embedding_retry /
  rule_scan 的 memory.maintenance.completed 审计，时间错开且都在各自
  cadence 内（maintenance.overdue 为空，展示"全绿"卡片）；embedding_retry
  另有一条 3 天前的记录，喂 7 天重试汇总（scanned=16, succeeded=15）。
  heartbeat 不种——quickstart 是内嵌拓扑，heartbeat 记录只属于独立 worker。
- embedding 积压：4 条 embedding_failed=true 的 memory_items（backlog 卡
  非零；quickstart 默认无向量库，重试跳过，积压稳定保持）。
- 检索：30 条 memory_search.completed 运行时事件分布在 12 次 run 上，
  vector/text 为主、keyword_fallback 恰好 10%（低于 R4 的 20% 阈值，且
  调用量 30 超过 R4 最小样本 20——规则真实评估但不误报）；含 5 次 0 命中
  调用，returned 有梯度。
- Agent 维度：两个不同 Agent 快照（config->'agent'->>'id'），客户绑定 run
  数与注入率不同（全链路 8 次 run 注入 6 次 = 0.75；精简注入 4 次 run
  注入 1 次 = 0.25）。
- 注入：memory_injection_log 明细行覆盖 flag/profile/preference/event 四段，
  挂在上述带注入的 7 次 run 上（21 行 / 7 run，avg_items=3.0）。
- 质量：7 天窗口内 memory.item.confirmed x8 / memory.item.rejected x2
  （确认率 80%）；已确认合并/已拒绝删除的条目行本身已不存在，审计资源
  悬空属真实形态。
- 告警历史：3 条历史 memory.alert.* 审计（task_failed 20 小时前、
  pending_backlog 3 天前、vector_fallback 5 天前），出现在告警列表中；
  均远超 60 分钟冷却窗口，不影响 quickstart 实时扫描的冷却判定。

所有行租户为 settings.tenant_id，id 为 ns("phase7") 下的确定性 uuid5；
身份绑定存在即整块跳过，重复运行不会再插入任何行。系统审计行 actor 用
"memory"（与 Task 1/2 的 worker/alerting 一致），人工确认/拒绝审计用
current_audit_actor（本地管理员存在时为 enterprise:<user_id>，否则 seed）。

显示文案走 seed_memory_i18n（AGENT_SEED_LOCALE）；身份键保持恒定，
locale 只影响首次入库的展示字符串。
"""

import json
from datetime import timedelta

from sqlalchemy import text

from agent_platform.apps.seed_memory_common import (
    current_audit_actor,
    default_reply,
    ensure_agent,
    identity_bound,
    insert_audit,
    insert_conversation,
    insert_customer,
    insert_identity,
    insert_item,
    insert_run,
    item,
    ns,
    pairs,
    run_standalone,
    ts,
    uid,
)
from agent_platform.apps.seed_memory_i18n import T
from agent_platform.modules.agent_config.service import AgentConfig

NS = ns("phase7")
EXT = "demo-p7-zhaowenbo"
TTL_DAYS = 180  # memory_event_ttl_days default，与 phase3 一致
# R2 演示：pending 任务龄期约 70 分钟（默认阈值 memory_alert_pending_task_max_age_minutes=60）。
STUCK_CREATED_H = 7 / 6  # 70 分钟
STUCK_UPDATED_H = 13 / 12  # 65 分钟（失败尝试落库时刻）
STUCK_RUN_AFTER_H = -24  # ts(-24) = NOW+24h：不可领取，详见模块 docstring


def _agents():
    """Demo agent specs; built per call so T() sees the active locale."""
    return [
        {
            "key": "fullchain",
            "name": T(
                zh="观测演示助手·全链路",
                en="Observability Demo Assistant · Full-chain",
                zh_tw="觀測演示助手·全鏈路",
                hi="ऑब्ज़र्वेबिलिटी डेमो असिस्टेंट · फुल-चेन",
            ),
            "description": T(
                zh="阶段7观测演示（全链路）：记忆配置全开，客户会话带检索（memory_search.completed，vector/text 为主、少量 keyword_fallback）与全段注入。预期：观测页 Agent 维度客户 run 8 次、注入率 0.75。",
                en="Phase 7 observability demo (full-chain): all memory config on; customer runs carry search telemetry (memory_search.completed, mostly vector/text with a little keyword_fallback) and full-section injection. Expected: 8 customer runs and a 0.75 injection rate on the observability page's per-agent card.",
                zh_tw="階段7觀測演示（全鏈路）：記憶配置全開，客戶會話帶檢索（memory_search.completed，vector/text 為主、少量 keyword_fallback）與全段注入。預期：觀測頁 Agent 維度客戶 run 8 次、注入率 0.75。",
                hi="चरण 7 ऑब्ज़र्वेबिलिटी डेमो (फुल-चेन): मेमोरी कॉन्फ़िग पूरी तरह चालू; ग्राहक रन में सर्च टेलीमेट्री (memory_search.completed, ज़्यादातर vector/text, थोड़ा keyword_fallback) और फुल-सेक्शन इंजेक्शन होता है। अपेक्षित: ऑब्ज़र्वेबिलिटी पेज के प्रति-एजेंट कार्ड पर 8 ग्राहक रन और 0.75 इंजेक्शन दर।",
            ),
            "config": {},
        },
        {
            "key": "lean",
            "name": T(
                zh="观测演示助手·精简注入",
                en="Observability Demo Assistant · Compact Injection",
                zh_tw="觀測演示助手·精簡注入",
                hi="ऑब्ज़र्वेबिलिटी डेमो असिस्टेंट · कॉम्पैक्ट इंजेक्शन",
            ),
            "description": T(
                zh="阶段7观测演示（对照组）：memory_inject_max_items=1，且部分早期会话运行在客户记忆建立之前。预期：观测页 Agent 维度客户 run 4 次、注入率 0.25，与全链路助手形成对比。",
                en="Phase 7 observability demo (control group): memory_inject_max_items=1, and some earlier sessions ran before the customer had any memory. Expected: 4 customer runs and a 0.25 injection rate on the per-agent card, in contrast to the full-chain assistant.",
                zh_tw="階段7觀測演示（對照組）：memory_inject_max_items=1，且部分早期會話運行在客戶記憶建立之前。預期：觀測頁 Agent 維度客戶 run 4 次、注入率 0.25，與全鏈路助手形成對比。",
                hi="चरण 7 ऑब्ज़र्वेबिलिटी डेमो (कंट्रोल समूह): memory_inject_max_items=1, और कुछ शुरुआती सत्र ग्राहक की मेमोरी बनने से पहले चले थे। अपेक्षित: प्रति-एजेंट कार्ड पर 4 ग्राहक रन और 0.25 इंजेक्शन दर, फुल-चेन असिस्टेंट के विपरीत।",
            ),
            "config": {"memory_inject_max_items": 1},
        },
    ]


def _system_prompt() -> str:
    return T(
        zh="你是一名企业客服助手。优先关注客户的在途工单与冷链投诉进展，回答时引用历史处理结论。",
        en="You are an enterprise customer-support assistant. Prioritize the customer's in-flight tickets and cold-chain complaint progress; cite historical resolutions when answering.",
        zh_tw="你是一名企業客服助手。優先關注客戶的在途工單與冷鏈投訴進展，回答時引用歷史處理結論。",
        hi="आप एक एंटरप्राइज़ कस्टमर-सपोर्ट असिस्टेंट हैं। ग्राहक के लंबित टिकटों और कोल्ड-चेन शिकायत की प्रगति को प्राथमिकता दें; जवाब देते समय पुराने समाधानों का हवाला दें।",
    )


def _items():
    """赵文博的记忆条目；built per call so T() sees the active locale."""
    sr = f"{EXT}:fullchain"
    return [
        item(
            "flag",
            "vip",
            T(
                zh="重点客户：出口订单账期 60 天，投诉升级需 2 小时内响应",
                en="Key account: 60-day payment terms on export orders; escalated complaints require a response within 2 hours",
                zh_tw="重點客戶：出口訂單賬期 60 天，投訴升級需 2 小時內響應",
                hi="मुख्य खाता: एक्सपोर्ट ऑर्डर पर 60-दिन की भुगतान अवधि; एस्केलेटेड शिकायतों पर 2 घंटे के भीतर जवाब ज़रूरी है",
            ),
            1.0,
            st="human",
            prot=True,
            ch=30 * 24,
            uh=30,
        ),
        item(
            "profile",
            "company",
            T(
                zh="蓝海水产食品股份有限公司",
                en="Lanhai Aquatic Foods Co., Ltd.",
                zh_tw="藍海水產食品股份有限公司",
                hi="Lanhai Aquatic Foods Co., Ltd.",
            ),
            0.97,
            st="manual",
            rc=8,
            ch=30 * 24,
            uh=25,
        ),
        item(
            "profile",
            "industry",
            T(
                zh="水产加工与冷链出口（舟山，自有冷库 2 座）",
                en="Aquatic processing and cold-chain export (Zhoushan, 2 self-operated cold storages)",
                zh_tw="水產加工與冷鏈出口（舟山，自有冷庫 2 座）",
                hi="एक्वाटिक प्रोसेसिंग और कोल्ड-चेन एक्सपोर्ट (Zhoushan, 2 स्व-संचालित कोल्ड स्टोरेज)",
            ),
            0.93,
            sr=sr,
            rc=5,
            ch=28 * 24,
            uh=72,
        ),
        # embedding_failed 积压条目（4 条）：向量嵌入重试队列的演示。
        item(
            "profile",
            "region",
            T(
                zh="主要市场：华东内销 + 日韩出口",
                en="Main markets: East China domestic plus Japan/Korea export",
                zh_tw="主要市場：華東內銷 + 日韓出口",
                hi="मुख्य बाज़ार: पूर्वी चीन घरेलू + जापान/कोरिया एक्सपोर्ट",
            ),
            0.9,
            sr=sr,
            rc=2,
            ch=26 * 24,
            uh=96,
        ),
        item(
            "profile",
            "scale",
            T(
                zh="年产能约 1.2 万吨，旺季 9-11 月",
                en="Annual capacity about 12,000 tonnes; peak season Sep-Nov",
                zh_tw="年產能約 1.2 萬噸，旺季 9-11 月",
                hi="वार्षिक क्षमता लगभग 12,000 टन; पीक सीज़न सितंबर-नवंबर",
            ),
            0.88,
            sr=sr,
            rc=1,
            ch=26 * 24,
            uh=120,
        ),
        item(
            "preference",
            "contact_channel",
            T(
                zh="工作日优先邮件沟通，紧急事项电话",
                en="Prefers email on workdays; phone for urgent matters",
                zh_tw="工作日優先郵件溝通，緊急事項電話",
                hi="कार्यदिवसों पर ईमेल को प्राथमिकता; ज़रूरी मामलों के लिए फ़ोन",
            ),
            0.9,
            sr=sr,
            rc=4,
            ch=20 * 24,
            uh=48,
        ),
        item(
            "preference",
            "report_format",
            T(
                zh="对账报表偏好 Excel 附件发送",
                en="Prefers reconciliation reports sent as Excel attachments",
                zh_tw="對賬報表偏好 Excel 附件發送",
                hi="रीकंसिलिएशन रिपोर्ट Excel अटैचमेंट के रूप में पसंद करते हैं",
            ),
            0.85,
            sr=sr,
            rc=1,
            ch=15 * 24,
            uh=90,
        ),
        # 待确认条目：与 memory.extract.applied 审计的 pending=1 呼应。
        item(
            "preference",
            "contact_time",
            T(
                zh="偏好下午 2 点后电话联系（待确认）",
                en="Prefers phone contact after 2 PM (unconfirmed)",
                zh_tw="偏好下午 2 點後電話聯繫（待確認）",
                hi="दोपहर 2 बजे के बाद फ़ोन संपर्क पसंद (पुष्टि लंबित)",
            ),
            0.6,
            status="pending",
            sr=sr,
            ch=6,
            uh=6,
        ),
        item(
            "event",
            "evt-202609-quality",
            T(
                zh="2026-09 批次抽检合格率 99.2%，客户认可质检报告格式",
                en="2026-09 batch sampling pass rate 99.2%; customer approved the QC report format",
                zh_tw="2026-09 批次抽檢合格率 99.2%，客戶認可質檢報告格式",
                hi="2026-09 बैच सैंपलिंग पास दर 99.2%; ग्राहक ने QC रिपोर्ट फ़ॉर्मैट मंज़ूर किया",
            ),
            0.85,
            sr=sr,
            rc=1,
            ch=35 * 24,
            uh=35 * 24,
        ),
    ]


# embedding_failed=true 的条目键（向量重试积压演示）。
EMBEDDING_FAILED_KEYS = (
    "profile:region",
    "profile:scale",
    "preference:report_format",
    "event:evt-202609-quality",
)

TICKET_KEY = "TK-20261025"


async def insert_open_ticket(conn, tenant, iid, cid, content):
    """在途工单事件条目：沿用 phase3 的真实写入形状（source_type=ticket + TTL）。"""
    created_h = 30
    await conn.execute(
        text("""INSERT INTO memory_items(id,tenant_id,customer_id,type,key,content,confidence,status,
                source_type,source_ref,revision,last_referenced_at,reference_count,
                created_at,updated_at,protected,expires_at)
                VALUES(:id,:t,:c,'event',:k,:co,1.0,'active','ticket',:sr,1,:lra,3,:ca,:ua,false,:exp)
                ON CONFLICT DO NOTHING"""),
        {
            "id": iid,
            "t": tenant,
            "c": cid,
            "k": f"open_ticket:{TICKET_KEY}",
            "co": content,
            "sr": uid(NS, "ticket", TICKET_KEY),
            "lra": ts(5),
            "ca": ts(created_h),
            "ua": ts(5),
            "exp": ts(created_h) + timedelta(days=TTL_DAYS),
        },
    )


async def insert_task(
    conn,
    tenant,
    key,
    kind,
    status,
    payload,
    *,
    duration_ms=None,
    created_h,
    updated_h=None,
    error=None,
    attempts=1,
    max_attempts=2,
    run_after_h=None,
):
    """One memory_tasks row in the worker's genuine shape (Task 1 duration_ms included)."""
    await conn.execute(
        text("""INSERT INTO memory_tasks(id,tenant_id,kind,status,payload,attempts,max_attempts,
                error,run_after,created_at,updated_at,duration_ms)
                VALUES(:id,:t,:k,:s,CAST(:p AS jsonb),:a,:m,:e,:ra,:ca,:ua,:d)
                ON CONFLICT DO NOTHING"""),
        {
            "id": uid(NS, "task", key),
            "t": tenant,
            "k": kind,
            "s": status,
            "p": json.dumps(payload, ensure_ascii=False),
            "a": attempts,
            "m": max_attempts,
            "e": error,
            "ra": ts(run_after_h) if run_after_h is not None else ts(created_h),
            "ca": ts(created_h),
            "ua": ts(updated_h if updated_h is not None else created_h),
            "d": duration_ms,
        },
    )


def search_events(run_key, cid, injected, searches):
    """Genuine run-event sequence with memory_search.completed events mid-loop.

    形状与 agent_runtime 一致：检索工具在 ReAct 循环内（model.started 之后、
    最终 model.completed 之前）发出 memory_search.completed；payload 为
    {mode, hits, returned}（hits 是 returned 的向后兼容别名）。
    """
    run_id = uid(NS, "run", run_key)
    evs = [
        (1, "run.queued", {}),
        (2, "run.started", {}),
        (3, "model.started", {"round": 1}),
    ]
    seq = 4
    for mode, hits in searches:
        evs.append((seq, "memory_search.completed", {"mode": mode, "hits": hits, "returned": hits}))
        seq += 1
    evs.append(
        (
            seq,
            "model.completed",
            {
                "round": 1,
                "usage": {},
                "tool_calls": 0,
                "duration_ms": 141,
                "first_token_ms": 38,
                "gateway_call_id": uid(NS, "gw", run_id),
            },
        )
    )
    seq += 1
    if cid:
        evs.append((seq, "memory_extract.queued", {"customer_id": cid}))
        seq += 1
    if injected:
        counts = {
            "flags": sum(1 for _, s, _ in injected if s == "flag"),
            "items": sum(1 for _, s, _ in injected if s in ("profile", "preference")),
            "events": sum(1 for _, s, _ in injected if s == "event"),
        }
        evs.append(
            (seq, "memory.injected", {**counts, "item_ids": [iid for iid, _, _ in injected]})
        )
        seq += 1
    evs.append((seq, "run.completed", {"output": default_reply(), "error_code": None}))
    return evs


def _run_specs():
    """12 次客户 run 的规格；built per call so T() sees the active locale.

    每条：(run_key, hours_ago, agent_key, 用户消息, searches[(mode,hits)], 注入标签)。
    检索总量：vector 19 / text 8 / keyword_fallback 3（10%，低于 R4 阈值 20%），
    0 命中 5 次，returned 合计 57（avg 1.9）。
    """
    return [
        (
            "a0",
            1,
            "fullchain",
            T(
                zh="你好，我是蓝海水产的赵文博，TK-20261025 那批冷链货温控异常的投诉进展如何？",
                en="Hi, this is Zhao Wenbo from Lanhai Aquatic Foods. What's the progress on the temperature-control complaint for shipment TK-20261025?",
                zh_tw="你好，我是藍海水產的趙文博，TK-20261025 那批冷鏈貨溫控異常的投訴進展如何？",
                hi="नमस्ते, मैं Lanhai Aquatic Foods का Zhao Wenbo हूँ। शिपमेंट TK-20261025 के तापमान-नियंत्रण शिकायत की क्या प्रगति है?",
            ),
            [("vector", 3), ("vector", 0), ("text", 2)],
            [
                "flag:vip",
                "profile:company",
                "profile:industry",
                "preference:contact_channel",
                f"event:open_ticket:{TICKET_KEY}",
            ],
        ),
        (
            "a1",
            3,
            "fullchain",
            T(
                zh="温控异常那批货客户催得紧，今天能给个处理时限吗？",
                en="The customer is pressing hard on the temperature-control shipment — can you give a resolution deadline today?",
                zh_tw="溫控異常那批貨客戶催得緊，今天能給個處理時限嗎？",
                hi="तापमान-नियंत्रण वाली शिपमेंट के लिए ग्राहक बहुत दबाव डाल रहा है — क्या आज कोई समाधान समय-सीमा मिल सकती है?",
            ),
            [("vector", 5), ("vector", 1)],
            ["flag:vip", "profile:company", "preference:contact_channel"],
        ),
        (
            "a2",
            5,
            "fullchain",
            T(
                zh="顺便查下我们 9 月份那批抽检的合格率记录。",
                en="By the way, please look up the sampling pass-rate record for our September batch.",
                zh_tw="順便查下我們 9 月份那批抽檢的合格率記錄。",
                hi="वैसे, कृपया हमारे सितंबर बैच के सैंपलिंग पास-दर रिकॉर्ड को देखिए।",
            ),
            [("vector", 2), ("keyword_fallback", 1)],
            ["profile:company", f"event:open_ticket:{TICKET_KEY}"],
        ),
        (
            "a3",
            7,
            "fullchain",
            T(
                zh="上周说的冷库扩容报价出来了吗？",
                en="Is the cold-storage expansion quote we discussed last week ready?",
                zh_tw="上週說的冷庫擴容報價出來了嗎？",
                hi="क्या पिछले हफ़्ते चर्चा की गई कोल्ड-स्टोरेज विस्तार की कोटेशन तैयार है?",
            ),
            [("text", 0), ("vector", 4)],
            [
                "flag:vip",
                "profile:industry",
                "preference:contact_channel",
                f"event:open_ticket:{TICKET_KEY}",
            ],
        ),
        (
            "a4",
            9,
            "fullchain",
            T(
                zh="对账报表以后都按 Excel 附件发我邮箱。",
                en="From now on, please send all reconciliation reports to my email as Excel attachments.",
                zh_tw="對賬報表以後都按 Excel 附件發我郵箱。",
                hi="अब से सभी रीकंसिलिएशन रिपोर्ट मुझे Excel अटैचमेंट के रूप में ईमेल पर भेजें।",
            ),
            [("vector", 3), ("vector", 2), ("text", 1)],
            ["profile:company", "profile:industry"],
        ),
        (
            "a5",
            12,
            "fullchain",
            T(
                zh="帮我看看历史上有没有类似的温控投诉记录。",
                en="Please check whether there are similar temperature-control complaints on record.",
                zh_tw="幫我看看歷史上有沒有類似的溫控投訴記錄。",
                hi="कृपया देखें कि रिकॉर्ड में ऐसी ही तापमान-नियंत्रण शिकायतें पहले भी हैं या नहीं।",
            ),
            [("keyword_fallback", 0), ("vector", 6)],
            [
                "flag:vip",
                "profile:company",
                "preference:contact_channel",
                f"event:open_ticket:{TICKET_KEY}",
            ],
        ),
        (
            "a6",
            16,
            "fullchain",
            T(
                zh="这个月出口订单的账期还是 60 天对吧？",
                en="The payment terms for this month's export orders are still 60 days, right?",
                zh_tw="這個月出口訂單的賬期還是 60 天對吧？",
                hi="इस महीने के एक्सपोर्ट ऑर्डर की भुगतान अवधि अब भी 60 दिन है, है ना?",
            ),
            [("vector", 1), ("text", 3), ("vector", 1)],
            [],
        ),
        (
            "a7",
            20,
            "fullchain",
            T(
                zh="下周三年度审核，需要你们提供上一季度的服务报告。",
                en="Next Wednesday is the annual audit; we need last quarter's service report from you.",
                zh_tw="下週三年度審核，需要你們提供上一季度的服務報告。",
                hi="अगले बुधवार वार्षिक ऑडिट है; हमें आपसे पिछली तिमाही की सर्विस रिपोर्ट चाहिए।",
            ),
            [("vector", 2), ("text", 0)],
            [],
        ),
        (
            "b0",
            2,
            "lean",
            T(
                zh="我是赵文博，想确认下我们公司档案里的联系邮箱是不是最新的。",
                en="This is Zhao Wenbo — I'd like to confirm the contact email in our company profile is up to date.",
                zh_tw="我是趙文博，想確認下我們公司檔案裡的聯繫郵箱是不是最新的。",
                hi="मैं Zhao Wenbo हूँ — मुझे पुष्टि करनी है कि हमारी कंपनी प्रोफ़ाइल का संपर्क ईमेल अप-टू-डेट है या नहीं।",
            ),
            [("vector", 2), ("vector", 1)],
            ["profile:company"],
        ),
        (
            "b1",
            8,
            "lean",
            T(
                zh="冷库扩容的报价如果出来了，发邮件给我。",
                en="If the cold-storage expansion quote is ready, email it to me.",
                zh_tw="冷庫擴容的報價如果出來了，發郵件給我。",
                hi="अगर कोल्ड-स्टोरेज विस्तार की कोटेशन तैयार है, तो मुझे ईमेल कर दें।",
            ),
            [("text", 2), ("vector", 0)],
            [],
        ),
        (
            "b2",
            14,
            "lean",
            T(
                zh="查一下我们历史工单里和冷链相关的处理结论。",
                en="Look up the resolutions of cold-chain-related tickets in our history.",
                zh_tw="查一下我們歷史工單裡和冷鏈相關的處理結論。",
                hi="हमारे इतिहास में कोल्ड-चेन से जुड़े टिकटों के समाधान देखिए।",
            ),
            [("vector", 4), ("keyword_fallback", 2), ("text", 2)],
            [],
        ),
        (
            "b3",
            21,
            "lean",
            T(
                zh="年产能数据需要更新，回头我把最新报表发你们。",
                en="The annual capacity figures need updating — I'll send you the latest report later.",
                zh_tw="年產能數據需要更新，回頭我把最新報表發你們。",
                hi="वार्षिक क्षमता के आंकड़े अपडेट करने हैं — मैं बाद में नवीनतम रिपोर्ट भेज दूँगा।",
            ),
            [("vector", 3), ("text", 1), ("vector", 2), ("vector", 1)],
            [],
        ),
    ]


def _maintenance_audits():
    """维护审计：(job, hours_ago, stats)。时间错开且均在各自 cadence 内。"""
    return [
        ("ttl_purge", 3, {"expired": 2}),
        ("injection_log_purge", 3, {"purged": 15}),
        ("decay", 5, {"profile_pending": 1, "preference_expired": 2, "evicted": 0}),
        ("embedding_retry", 6, {"scanned": 12, "succeeded": 11, "failed": 1}),
        # 3 天前的第二次重试：喂 embedding 段的 7 天汇总（合计 16/15）。
        ("embedding_retry", 72, {"scanned": 4, "succeeded": 4, "failed": 0}),
        ("rule_scan", 1 / 3, {"scanned": 2, "marked": 1, "flags_removed": 0}),
    ]


def _quality_audits(cid):
    """pending 质量审计（7d 窗口）：8 确认 + 2 拒绝，确认率 80%。

    资源为确定性合成条目 id：已确认并合并、已拒绝并删除的条目行本身不再
    存在，审计资源悬空与真实路径一致（confirm 合并分支 / reject 删除）。
    """
    confirmed = [
        ("profile", "plant_address", 2),
        ("preference", "invoice_title", 8),
        ("profile", "contact", 20),
        ("preference", "settlement_cycle", 30),
        ("event", "evt-202608-audit", 50),
        ("profile", "cert", 70),
        ("preference", "packaging", 100),
        ("preference", "logistics", 140),
    ]
    rejected = [("preference", "contact_wechat", 10), ("profile", "short_name", 90)]
    rows = []
    for n, (t, k, h) in enumerate(confirmed):
        rows.append(
            (
                "memory.item.confirmed",
                uid(NS, "item", f"quality:c{n}"),
                {
                    "customer_id": cid,
                    "type": t,
                    "key": k,
                    "old_status": "pending",
                    "new_status": "active",
                },
                h,
            )
        )
    for n, (t, k, h) in enumerate(rejected):
        rows.append(
            (
                "memory.item.rejected",
                uid(NS, "item", f"quality:r{n}"),
                {
                    "customer_id": cid,
                    "type": t,
                    "key": k,
                    "old_status": "pending",
                    "new_status": "deleted",
                },
                h,
            )
        )
    return rows


def _alert_history():
    """历史告警（resource=rule，details={value,threshold,window}，actor=memory）。

    均远超 60 分钟冷却窗口：只充实告警列表，不影响 quickstart 实时扫描。
    """
    return [
        ("task_failed", 20, {"value": 2, "threshold": 0, "window": "15m"}),
        ("pending_backlog", 72, {"value": 530, "threshold": 500, "window": "now"}),
        ("vector_fallback", 120, {"value": 0.34, "threshold": 0.2, "window": "24h"}),
    ]


async def seed(runtime, settings) -> bool:
    """幂等入口：身份绑定已存在则整块跳过，仅首次返回 True。"""
    tenant = settings.tenant_id
    p = runtime.platform
    audit_actor = await current_audit_actor(p, tenant)

    # --- 演示 Agent（ensure_agent 按名称幂等） ------------------------------
    agents = {}
    for spec in _agents():
        config = AgentConfig(
            system_prompt=_system_prompt(), tool_names=[], knowledge_base_ids=[], **spec["config"]
        )
        agents[spec["key"]] = await ensure_agent(
            p, tenant, "seed", spec["name"], spec["description"], config
        )

    async with p.engine.begin() as conn:
        if await identity_bound(conn, tenant, "web", EXT):
            return False
        cid = uid(NS, "customer", "zhaowenbo")
        conv_a = uid(NS, "conversation", f"{EXT}:fullchain")
        conv_b = uid(NS, "conversation", f"{EXT}:lean")
        specs = {f"{i['t']}:{i['k']}": i for i in _items()}
        iids = {
            k: uid(NS, "item", f"zhao:{k}") for k in (*specs, f"event:open_ticket:{TICKET_KEY}")
        }

        def inj(keys):
            return [
                (
                    iids[k],
                    specs[k]["t"],
                    specs[k]["conf"] if specs[k]["t"] in ("profile", "preference") else None,
                )
                for k in keys
            ]

        # --- 客户 + 身份 + 记忆条目 --------------------------------------
        await insert_customer(conn, tenant, cid, 30 * 24, 1)
        await insert_identity(conn, tenant, uid(NS, "identity", EXT), cid, EXT, 30 * 24)
        for spec in _items():
            await insert_item(
                conn,
                tenant,
                iids[f"{spec['t']}:{spec['k']}"],
                cid,
                spec,
                last_referenced_h=5 if spec["status"] == "active" else None,
            )
        await insert_open_ticket(
            conn,
            tenant,
            iids[f"event:open_ticket:{TICKET_KEY}"],
            cid,
            T(
                zh="TK-20261025：出口冷链批次运输途中温控异常，客户要求 48 小时内给出处理方案",
                en="TK-20261025: temperature-control anomaly in transit for an export cold-chain batch; customer demands a resolution plan within 48 hours",
                zh_tw="TK-20261025：出口冷鏈批次運輸途中溫控異常，客戶要求 48 小時內給出處理方案",
                hi="TK-20261025: एक्सपोर्ट कोल्ड-चेन बैच में ट्रांज़िट के दौरान तापमान-नियंत्रण विसंगति; ग्राहक ने 48 घंटों में समाधान योजना माँगी है",
            ),
        )
        # open_ticket 条目进注入规格表（event 段 score=None，与运行时一致）。
        specs[f"event:open_ticket:{TICKET_KEY}"] = {"t": "event", "conf": None}
        # embedding 积压：4 条 active 条目打上 embedding_failed（重试队列形状）。
        for key in EMBEDDING_FAILED_KEYS:
            await conn.execute(
                text("UPDATE memory_items SET embedding_failed=true WHERE tenant_id=:t AND id=:id"),
                {"t": tenant, "id": iids[key]},
            )

        # --- 会话 + run（检索事件 / 注入 / Agent 维度） ---------------------
        run_specs = _run_specs()
        msgs_a = [r[3] for r in run_specs if r[0].startswith("a")]
        await insert_conversation(
            conn,
            tenant,
            conv_a,
            f"{EXT}:fullchain",
            pairs(msgs_a),
            20.1,
            1,
            agents["fullchain"]["id"],
            summary=T(
                zh="客户赵文博（蓝海水产，重点客户）：跟进 TK-20261025 冷链温控异常投诉；冷库扩容报价待反馈；下周三年度审核需提供上季度服务报告。",
                en="Customer Zhao Wenbo (Lanhai Aquatic Foods, key account): following up on the TK-20261025 cold-chain temperature-control complaint; cold-storage expansion quote pending; annual audit next Wednesday requires last quarter's service report.",
                zh_tw="客戶趙文博（藍海水產，重點客戶）：跟進 TK-20261025 冷鏈溫控異常投訴；冷庫擴容報價待反饋；下週三年度審核需提供上季度服務報告。",
                hi="ग्राहक Zhao Wenbo (Lanhai Aquatic Foods, मुख्य खाता): TK-20261025 कोल्ड-चेन तापमान-नियंत्रण शिकायत का फ़ॉलो-अप; कोल्ड-स्टोरेज विस्तार कोटेशन लंबित; अगले बुधवार वार्षिक ऑडिट के लिए पिछली तिमाही की सर्विस रिपोर्ट चाहिए।",
            ),
            cid=cid,
        )
        msgs_b = [r[3] for r in run_specs if r[0].startswith("b")]
        await insert_conversation(
            conn,
            tenant,
            conv_b,
            f"{EXT}:lean",
            pairs(msgs_b),
            21.1,
            2,
            agents["lean"]["id"],
            cid=cid,
        )
        for run_key, hours, agent_key, msg, searches, injected_labels in run_specs:
            conv = conv_a if agent_key == "fullchain" else conv_b
            injected = inj(injected_labels)
            await insert_run(
                conn,
                tenant,
                NS,
                f"zhao:{run_key}",
                conv,
                agents[agent_key],
                settings.model_backend,
                msg,
                hours,
                cid=cid,
                injected=injected,
                events=search_events(f"zhao:{run_key}", cid, injected, searches),
            )

        # --- 任务健康：四种 kind 的 done/failed + 一条 R2 演示 pending ------
        sum_payload = {
            "conversation_id": conv_a,
            "dropped_messages": [
                {"role": "user", "content": msgs_a[0]},
                {"role": "assistant", "content": default_reply()},
            ],
            "old_summary": None,
        }
        ext_payload = {"conversation_id": conv_a, "customer_id": cid, "write_mode": "auto"}
        ticket_id = uid(NS, "ticket", TICKET_KEY)
        tasks = [
            ("sum:0", "conversation_summary", "done", sum_payload, 55, 1.5, None, 1, None),
            ("sum:1", "conversation_summary", "done", sum_payload, 130, 6.5, None, 1, None),
            ("sum:2", "conversation_summary", "done", sum_payload, 210, 13, None, 1, None),
            (
                "sum:fail",
                "conversation_summary",
                "failed",
                sum_payload,
                180,
                5,
                "summary_model_error",
                2,
                None,
            ),
            ("ext:0", "memory_extract", "done", ext_payload, 120, 2, None, 1, None),
            ("ext:1", "memory_extract", "done", ext_payload, 240, 4.5, None, 1, None),
            ("ext:2", "memory_extract", "done", ext_payload, 480, 11, None, 1, None),
            ("ext:3", "memory_extract", "done", ext_payload, 850, 18, None, 1, None),
            (
                "ext:fail",
                "memory_extract",
                "failed",
                ext_payload,
                390,
                2.2,
                "extract_model_error",
                2,
                None,
            ),
            (
                "evt:0",
                "event_write",
                "done",
                {"ticket_id": ticket_id, "event": "created", "log_id": None},
                300,
                8,
                None,
                1,
                None,
            ),
            (
                "evt:1",
                "event_write",
                "done",
                {"ticket_id": ticket_id, "event": "commitment", "log_id": 10021},
                620,
                15,
                None,
                1,
                None,
            ),
            (
                "rf:0",
                "reinforce",
                "done",
                {
                    "hits": {
                        iids["profile:company"]: 2,
                        iids["profile:industry"]: 1,
                        iids["flag:vip"]: 1,
                    }
                },
                700,
                3.5,
                None,
                1,
                None,
            ),
            (
                "rf:1",
                "reinforce",
                "done",
                {
                    "hits": {
                        iids["preference:contact_channel"]: 1,
                        iids[f"event:open_ticket:{TICKET_KEY}"]: 1,
                    }
                },
                900,
                10,
                None,
                1,
                None,
            ),
        ]
        for key, kind, status, payload, dur, created_h, error, attempts, ra_h in tasks:
            await insert_task(
                conn,
                tenant,
                key,
                kind,
                status,
                payload,
                duration_ms=dur,
                created_h=created_h,
                error=error,
                attempts=attempts,
                run_after_h=ra_h,
            )
        # R2 演示任务：pending 约 70 分钟、run_after 在未来（不可领取），
        # quickstart 内嵌告警扫描器首个周期即真实触发 pending_task_age。
        await insert_task(
            conn,
            tenant,
            "ext:stuck",
            "memory_extract",
            "pending",
            ext_payload,
            created_h=STUCK_CREATED_H,
            updated_h=STUCK_UPDATED_H,
            error="summary_execution_error",
            attempts=1,
            run_after_h=STUCK_RUN_AFTER_H,
        )

        # --- 维护健康审计（Task 1 形状 {job,result,stats}，actor=memory） ----
        for job, hours, stats in _maintenance_audits():
            await insert_audit(
                conn,
                tenant,
                "memory",
                "memory.maintenance.completed",
                job,
                {"job": job, "result": "ok", "stats": stats},
                hours,
            )

        # --- 抽取审计（pending=1 与客户待确认条目呼应，actor=memory） --------
        await insert_audit(
            conn,
            tenant,
            "memory",
            "memory.extract.applied",
            cid,
            {
                "conversation_id": f"{EXT}:fullchain",
                "input_messages": 8,
                "added": 2,
                "updated": 1,
                "pending": 1,
                "dropped": 0,
                "pii_masked": 0,
                "usage": {},
            },
            6,
        )

        # --- pending 质量审计（操作人 actor） --------------------------------
        for action, resource, details, hours in _quality_audits(cid):
            await insert_audit(conn, tenant, audit_actor, action, resource, details, hours)

        # --- 历史告警（不影响实时扫描冷却） ----------------------------------
        for rule, hours, details in _alert_history():
            await insert_audit(conn, tenant, "memory", f"memory.alert.{rule}", rule, details, hours)
    return True


if __name__ == "__main__":
    run_standalone(
        seed,
        lambda: T(
            zh="阶段7生产观测与告警演示数据",
            en="Phase 7 production observability & alerting demo data",
            zh_tw="階段7生產觀測與告警演示數據",
            hi="चरण 7 प्रोडक्शन ऑब्ज़र्वेबिलिटी और अलर्टिंग डेमो डेटा",
        ),
    )
