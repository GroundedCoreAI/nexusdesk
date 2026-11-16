"""Fixed demo data for the mock business API.

Every identifier here is stable on purpose: service-application connection and
skill tests use these values, so a reset must reproduce exactly the same
records.

Field names are the ones described by the application skill contracts. Result
mappings can select a field such as ``status`` directly, so the response keeps
stable business field names instead of wrapping every value in a display label.
"""

from __future__ import annotations

from typing import Any

# purchase_order: order_no, status, paid_amount, placed_at, recipient
ORDERS: dict[str, dict[str, Any]] = {
    "PO20261110001": {
        "order_no": "PO20261110001",
        "customer_id": "C1001",
        "status": "已发货",
        "paid_amount": 299.0,
        "placed_at": "2026-11-08T10:12:00+08:00",
        "recipient": "张女士",
        "items": [{"sku": "SKU-8891", "title": "轻量羽绒服", "quantity": 1}],
    },
    "PO20261110002": {
        "order_no": "PO20261110002",
        "customer_id": "C1001",
        "status": "待付款",
        "paid_amount": 0.0,
        "placed_at": "2026-11-09T21:40:00+08:00",
        "recipient": "张女士",
        "items": [{"sku": "SKU-2203", "title": "保温杯", "quantity": 2}],
    },
    "PO20261110003": {
        "order_no": "PO20261110003",
        "customer_id": "C1002",
        "status": "已签收",
        "paid_amount": 58.0,
        "placed_at": "2026-11-05T09:03:00+08:00",
        "recipient": "李先生",
        "items": [{"sku": "SKU-4410", "title": "猫粮 2kg", "quantity": 1}],
    },
}

# shipment: tracking_no, carrier, status, current_node, eta
SHIPMENTS: dict[str, dict[str, Any]] = {
    "SF7788990011": {
        "tracking_no": "SF7788990011",
        "order_no": "PO20261110001",
        "carrier": "顺丰速运",
        "status": "运输中",
        "current_node": "上海转运中心",
        "eta": "2026-11-11",
    },
    "YT6600120033": {
        "tracking_no": "YT6600120033",
        "order_no": "PO20261110003",
        "carrier": "圆通速递",
        "status": "已签收",
        "current_node": "杭州余杭网点",
        "eta": "2026-11-07",
    },
}

# after_sale_ticket: ticket_no, status, reason, submitted_at, resolution
AFTER_SALES: dict[str, dict[str, Any]] = {
    "AS20261110001": {
        "ticket_no": "AS20261110001",
        "order_no": "PO20261110001",
        "status": "处理中",
        "reason": "尺码不合适，申请换货",
        "submitted_at": "2026-11-09T14:20:00+08:00",
        "resolution": "待商家确认换货",
    },
    "AS20261110002": {
        "ticket_no": "AS20261110002",
        "order_no": "PO20261110003",
        "status": "已完成",
        "reason": "外包装破损",
        "submitted_at": "2026-11-06T11:05:00+08:00",
        "resolution": "已退款 58.00 元",
    },
}

# game_role: role_name, server, role_level, status, restriction, account_id
GAME_ROLES: dict[str, dict[str, Any]] = {
    "ROLE-1001": {
        "role_id": "ROLE-1001",
        "role_name": "影歌",
        "server": "电信一区",
        "role_level": 87,
        "status": "正常",
        "restriction": "",
        "account_id": "ACC-7001",
    },
    "ROLE-1002": {
        "role_id": "ROLE-1002",
        "role_name": "夜航",
        "server": "联通三区",
        "role_level": 42,
        "status": "受限",
        "restriction": "禁言中",
        "account_id": "ACC-7002",
    },
}

# recharge_order: order_no, amount, paid_at, status, pay_channel
RECHARGES: dict[str, dict[str, Any]] = {
    "RC20261110001": {
        "order_no": "RC20261110001",
        "account_id": "ACC-7001",
        "amount": 648.0,
        "paid_at": "2026-11-09T19:02:00+08:00",
        "status": "已到账",
        "pay_channel": "微信支付",
    },
    "RC20261110002": {
        "order_no": "RC20261110002",
        "account_id": "ACC-7001",
        "amount": 128.0,
        "paid_at": "2026-11-10T08:31:00+08:00",
        "status": "未到账",
        "pay_channel": "支付宝",
    },
}

# sanction_record: record_no, violation, penalty, duration, status, appeal_deadline
SANCTIONS: dict[str, dict[str, Any]] = {
    "SN20261110001": {
        "record_no": "SN20261110001",
        "account_id": "ACC-7002",
        "violation": "聊天频道发布违规言论",
        "penalty": "禁言 7 天",
        "duration": "7 天",
        "status": "生效中",
        "appeal_deadline": "2026-11-17",
    },
    "SN20261110002": {
        "record_no": "SN20261110002",
        "account_id": "ACC-7001",
        "violation": "异常登录风控",
        "penalty": "临时冻结 24 小时",
        "duration": "24 小时",
        "status": "已解除",
        "appeal_deadline": "2026-11-12",
    },
}

# creator_account: creator_name, creator_id, level, status, verification
CREATOR_ACCOUNTS: dict[str, dict[str, Any]] = {
    "CR-2001": {
        "creator_id": "CR-2001",
        "creator_name": "林小满",
        "level": "L3",
        "status": "正常",
        "verification": "已实名",
    },
    "CR-2002": {
        "creator_id": "CR-2002",
        "creator_name": "陈拾",
        "level": "L1",
        "status": "限流中",
        "verification": "未实名",
    },
}

# content_work: work_title, work_type, status, publish_status, published_at
WORKS: dict[str, dict[str, Any]] = {
    "WK20261110001": {
        "work_id": "WK20261110001",
        "creator_id": "CR-2001",
        "title": "秋日胶片 vlog",
        "work_type": "视频",
        "status": "审核不通过",
        "publish_status": "未发布",
        "published_at": None,
    },
    "WK20261110002": {
        "work_id": "WK20261110002",
        "creator_id": "CR-2001",
        "title": "城市夜景合集",
        "work_type": "图文",
        "status": "审核通过",
        "publish_status": "已发布",
        "published_at": "2026-11-04T18:20:00+08:00",
    },
}

# review_record: record_no, reject_reason, status, reviewed_at, appeal_deadline
REVIEW_RECORDS: dict[str, dict[str, Any]] = {
    "RV20261110001": {
        "record_no": "RV20261110001",
        "work_id": "WK20261110001",
        "reject_reason": "封面含疑似违规元素",
        "status": "审核不通过",
        "reviewed_at": "2026-11-09T16:45:00+08:00",
        "appeal_deadline": "2026-11-16",
    }
}

# revenue_statement: period, amount, status, settled_at
REVENUE: list[dict[str, Any]] = [
    {
        "statement_no": "RS202610CR2001",
        "creator_id": "CR-2001",
        "period": "2026-10",
        "amount": 3280.5,
        "status": "待结算",
        "settled_at": None,
    },
    {
        "statement_no": "RS202609CR2001",
        "creator_id": "CR-2001",
        "period": "2026-09",
        "amount": 2914.0,
        "status": "已结算",
        "settled_at": "2026-10-08T10:00:00+08:00",
    },
]

# trip_order: trip_no, origin, destination, status, started_at, driver_name, plate_no
TRIPS: dict[str, dict[str, Any]] = {
    "TR20261110001": {
        "trip_no": "TR20261110001",
        "passenger_id": "C1001",
        "origin": "虹桥火车站",
        "destination": "浦东国际机场",
        "status": "已完成",
        "started_at": "2026-11-09T06:40:00+08:00",
        "driver_name": "王师傅",
        "plate_no": "沪A·12345",
    },
    "TR20261110002": {
        "trip_no": "TR20261110002",
        "passenger_id": "C1002",
        "origin": "静安寺",
        "destination": "陆家嘴",
        "status": "进行中",
        "started_at": "2026-11-10T20:05:00+08:00",
        "driver_name": "李师傅",
        "plate_no": "沪B·88866",
    },
}

# fare_breakdown: base_fare, distance_fare, extra_fare, total_amount, status,
# and the fact ``fare_trip_no <- trip_no`` needs ``trip_no`` in the response.
FARES: dict[str, dict[str, Any]] = {
    "TR20261110001": {
        "trip_no": "TR20261110001",
        "base_fare": 14.0,
        "distance_fare": 86.5,
        "extra_fare": 0.0,
        "total_amount": 100.5,
        "status": "已支付",
    },
    "TR20261110002": {
        "trip_no": "TR20261110002",
        "base_fare": 14.0,
        "distance_fare": 23.0,
        "extra_fare": 5.0,
        "total_amount": 42.0,
        "status": "待支付",
    },
}

# membership_entitlement: level, status, effective_at, expires_at, benefits
MEMBERSHIPS: dict[str, dict[str, Any]] = {
    "ACC-3001": {
        "account_id": "ACC-3001",
        "level": "黄金会员",
        "status": "生效中",
        "effective_at": "2026-01-01T00:00:00+08:00",
        "expires_at": "2027-01-01T00:00:00+08:00",
        "benefits": ["免运费", "专属客服", "生日礼包"],
    },
    "ACC-3002": {
        "account_id": "ACC-3002",
        "level": "白银会员",
        "status": "已过期",
        "effective_at": "2025-05-01T00:00:00+08:00",
        "expires_at": "2026-05-01T00:00:00+08:00",
        "benefits": ["免运费"],
    },
}

# community_account: status, security_state, created_at, realname_summary, restriction_reason
COMMUNITY_ACCOUNTS: dict[str, dict[str, Any]] = {
    "ACC-3001": {
        "account_id": "ACC-3001",
        "status": "正常",
        "security_state": "安全",
        "created_at": "2024-03-18T09:00:00+08:00",
        "realname_summary": "已实名（张**）",
        "restriction_reason": "",
    },
    "ACC-3003": {
        "account_id": "ACC-3003",
        "status": "受限",
        "security_state": "存在异常登录",
        "created_at": "2025-08-02T12:30:00+08:00",
        "realname_summary": "未实名",
        "restriction_reason": "异地频繁登录，暂时限制发帖",
    },
}

# community_content: title, content_type, publish_status, review_status,
# visibility, published_at, content_summary
COMMUNITY_CONTENTS: dict[str, dict[str, Any]] = {
    "CT20261110001": {
        "content_id": "CT20261110001",
        "account_id": "ACC-3001",
        "title": "城市夜景合集",
        "content_type": "图文",
        "publish_status": "已发布",
        "review_status": "审核通过",
        "visibility": "公开",
        "published_at": "2026-11-04T18:20:00+08:00",
        "content_summary": "外滩、陆家嘴、武康路三处夜景合集。",
    },
    "CT20261110002": {
        "content_id": "CT20261110002",
        "account_id": "ACC-3003",
        "title": "兼职招募（待审核）",
        "content_type": "图文",
        "publish_status": "未发布",
        "review_status": "审核中",
        "visibility": "仅自己可见",
        "published_at": None,
        "content_summary": "包含外部联系方式，等待人工复核。",
    },
}

# Anything not listed resolves to a 404 so the console can exercise the
# "missing upstream object" branch of the tool bridge.
KNOWN_IDS: dict[str, list[str]] = {
    "purchase_order": sorted(ORDERS),
    "shipment": sorted(SHIPMENTS),
    "after_sale_ticket": sorted(AFTER_SALES),
    "game_role": sorted(GAME_ROLES),
    "recharge_order": sorted(RECHARGES),
    "sanction_record": sorted(SANCTIONS),
    "creator_account": sorted(CREATOR_ACCOUNTS),
    "content_work": sorted(WORKS),
    "review_record": sorted(REVIEW_RECORDS),
    "trip_order": sorted(TRIPS),
    "fare_breakdown": sorted(FARES),
    "membership_entitlement": sorted(MEMBERSHIPS),
    "community_account": sorted(COMMUNITY_ACCOUNTS),
    "community_content": sorted(COMMUNITY_CONTENTS),
}
