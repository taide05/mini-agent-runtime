"""客服分流业务工具：意图分类 / 订单查询 / 支付查询 / 账号校验 / 知识库搜索 / FAQ搜索。

每个工具返回模拟数据，供 Agent ReAct 循环调用。
"""

from __future__ import annotations

# ─── Mock 数据库 ─────────────────────────────────────────────

MOCK_ORDERS: dict[str, dict] = {
    "ORD-001": {
        "order_id": "ORD-001", "user": "张三", "phone": "138****1234",
        "items": [{"name": "无线蓝牙耳机 Pro", "price": 299, "qty": 1}],
        "total": 299, "status": "已支付", "date": "2026-07-20",
        "payment_method": "微信支付",
    },
    "ORD-002": {
        "order_id": "ORD-002", "user": "张三", "phone": "138****1234",
        "items": [{"name": "手机壳 透明防摔", "price": 49, "qty": 2}],
        "total": 98, "status": "已发货", "date": "2026-07-22",
        "payment_method": "支付宝",
    },
    "ORD-003": {
        "order_id": "ORD-003", "user": "李四", "phone": "159****5678",
        "items": [{"name": "智能手表 S3", "price": 1299, "qty": 1}],
        "total": 1299, "status": "待发货", "date": "2026-07-23",
        "payment_method": "微信支付",
    },
}

MOCK_PAYMENTS: dict[str, list[dict]] = {
    "USR-ZS": [
        {"id": "PAY-001", "amount": 299, "method": "微信支付", "date": "2026-07-20", "status": "成功"},
        {"id": "PAY-002", "amount": 98, "method": "支付宝", "date": "2026-07-22", "status": "成功"},
        {"id": "PAY-003", "amount": 49, "method": "微信支付", "date": "2026-07-19", "status": "已退款"},
    ],
}

MOCK_ACCOUNTS: dict[str, dict] = {
    "zhangsan@example.com": {"status": "正常", "last_login": "2026-07-23 09:15", "mfa_enabled": True},
    "13800001111": {"status": "正常", "last_login": "2026-07-22 18:30", "mfa_enabled": False},
    "locked@example.com": {"status": "已锁定", "last_login": "2026-07-20 03:00", "mfa_enabled": False, "lock_reason": "多次密码错误"},
}

MOCK_KB: list[dict] = [
    {
        "id": "KB-001", "title": "App 闪退修复方案",
        "category": "技术故障",
        "symptoms": ["闪退", "崩溃", "打不开"],
        "solution": "1. 更新 App 至最新版本\n2. 清除 App 缓存（设置→通用→存储→清除缓存）\n3. 如仍闪退，卸载重装（注意：重装会清除本地草稿）",
    },
    {
        "id": "KB-002", "title": "支付失败排查步骤",
        "category": "技术故障",
        "symptoms": ["支付失败", "付不了", "扣款异常"],
        "solution": "1. 检查网络连接\n2. 确认支付方式余额充足\n3. 尝试切换支付方式（微信/支付宝）\n4. 如已扣款未到账，等待 5 分钟后刷新",
    },
    {
        "id": "KB-003", "title": "页面加载白屏处理",
        "category": "技术故障",
        "symptoms": ["白屏", "加载不出", "空白", "卡住"],
        "solution": "1. 下拉刷新页面\n2. 切换 WiFi/4G 网络\n3. 重启 App\n4. 如持续白屏，反馈给技术团队处理",
    },
]

MOCK_FAQ: list[dict] = [
    {
        "id": "FAQ-001",
        "question": "如何申请退款？",
        "answer": "在订单详情页点击「申请售后」→选择退款原因→提交。审核通过后 1-3 个工作日退回原支付方式。已发货商品需先寄回。",
    },
    {
        "id": "FAQ-002",
        "question": "商品什么时候发货？",
        "answer": "现货商品下单后 24 小时内发货，预售商品按页面标注时间发货。发货后可在订单详情查看物流信息。",
    },
    {
        "id": "FAQ-003",
        "question": "支持哪些支付方式？",
        "answer": "支持微信支付、支付宝、银联卡、Apple Pay。部分商品支持花呗分期和信用卡分期。",
    },
    {
        "id": "FAQ-004",
        "question": "如何修改收货地址？",
        "answer": "未发货订单：订单详情→修改地址。已发货订单：联系客服修改，可能产生转寄费用。",
    },
    {
        "id": "FAQ-005",
        "question": "退货运费谁承担？",
        "answer": "商品质量问题由商家承担退货运费；非质量问题（如不喜欢、买错）由买家承担。具体以售后审核结果为准。",
    },
]


# ─── 工具函数 ────────────────────────────────────────────────


async def classify_intent(query: str) -> dict:
    """对用户咨询进行意图分类，返回类别、置信度和判断依据。"""
    refund_kw = ["退款", "退钱", "退差价", "退", "扣款", "扣费", "扣了", "被扣", "重复扣", "多扣",
                  "投诉", "赔", "乱收费", "自动续费", "多付", "多收", "空包", "没到账", "买贵"]
    account_kw = ["密码", "登录不上", "登不上", "账号", "账户", "找回", "被封", "锁定", "验证码",
                   "实名", "身份", "解绑", "重置", "第三方", "换设备"]
    tech_kw = ["闪退", "崩溃", "打不开", "报错", "卡顿", "白屏", "用不了", "没反应", "加载不出",
               "加载不出来", "不显示", "卡住", "收不到", "推送", "很慢", "特别卡", "转圈", "裂了",
               "识别错误"]
    product_kw = ["多少钱", "价格", "发货", "物流", "退货", "售后", "分期", "收货", "地址",
                   "保修", "取消", "换货", "会员", "尺寸", "区别", "货到付款", "权益", "快递",
                   "颜色", "适合", "流程", "运费", "5G", "蓝牙", "防水", "材质",
                   "生产日期", "正品", "包邮"]

    scores = {
        "退款投诉": sum(1 for kw in refund_kw if kw in query),
        "账号找回": sum(1 for kw in account_kw if kw in query),
        "技术故障": sum(1 for kw in tech_kw if kw in query),
        "产品咨询": sum(1 for kw in product_kw if kw in query),
    }

    max_score = max(scores.values())
    if max_score == 0:
        return {"category": "一般疑问", "confidence": 0.75, "reasoning": "未命中任何类别关键词，归为一般疑问"}

    best = max(scores, key=scores.get)
    confidence = min(0.95, 0.70 + max_score * 0.08)
    reasonings = {
        "退款投诉": "命中退款/扣费/投诉类关键词",
        "账号找回": "命中账号/密码/登录类关键词",
        "技术故障": "命中闪退/报错/卡顿等技术类关键词",
        "产品咨询": "命中价格/功能/物流/售后等产品类关键词",
    }
    return {"category": best, "confidence": round(confidence, 2), "reasoning": reasonings[best]}


async def lookup_order(order_id: str) -> dict:
    """按订单号查询订单详情。"""
    order = MOCK_ORDERS.get(order_id.upper())
    if order is None:
        return {"found": False, "order_id": order_id, "message": f"未找到订单 {order_id}"}
    return {"found": True, **order}


async def lookup_payment(user_id: str) -> dict:
    """查询用户的支付记录（最近 5 条）。"""
    payments = MOCK_PAYMENTS.get(user_id.upper(), [])
    return {"user_id": user_id, "payment_count": len(payments), "recent_payments": payments}


async def verify_account(identifier: str) -> dict:
    """校验用户账号状态。identifier 可以是邮箱或手机号。"""
    account = MOCK_ACCOUNTS.get(identifier.lower())
    if account is None:
        return {"found": False, "identifier": identifier, "message": "未找到该账号，请确认邮箱或手机号是否正确"}
    return {"found": True, "identifier": identifier, **account}


async def search_knowledge_base(query: str) -> dict:
    """搜索技术知识库，返回匹配的已知问题和解决方案。"""
    results = []
    for article in MOCK_KB:
        hit = any(symptom in query for symptom in article["symptoms"])
        if hit:
            results.append({
                "id": article["id"],
                "title": article["title"],
                "solution": article["solution"],
                "relevance": "high",
            })
    if not results:
        return {"query": query, "match_count": 0, "results": [], "suggestion": "未找到已知方案，建议升级至技术团队处理"}
    return {"query": query, "match_count": len(results), "results": results}


async def search_faq(query: str) -> dict:
    """搜索产品 FAQ，返回匹配的常见问题及回答。"""
    results = []
    for faq in MOCK_FAQ:
        # 简单关键词匹配
        faq_text = faq["question"] + faq["answer"]
        score = sum(1 for ch in query if ch in faq_text)
        if score >= 2:  # 至少2个字匹配
            results.append({
                "id": faq["id"],
                "question": faq["question"],
                "answer": faq["answer"],
                "match_score": score,
            })
    results.sort(key=lambda r: r["match_score"], reverse=True)
    top = results[:3]
    return {"query": query, "match_count": len(top), "results": top}


# ─── 工具注册列表 ────────────────────────────────────────────

TRIAGE_TOOLS: list[dict] = [
    {
        "name": "classify_intent",
        "description": "对用户咨询进行意图分类。返回类别（退款投诉/账号找回/技术故障/产品咨询/一般疑问）、置信度(0-1)和判断依据。必须在处理任何用户咨询时最先调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户原始咨询内容"},
            },
            "required": ["query"],
        },
        "fn": classify_intent,
    },
    {
        "name": "lookup_order",
        "description": "按订单号查询订单详情，返回商品、金额、支付方式、状态等信息。仅在用户提供订单号或咨询涉及具体订单时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号，如 ORD-001"},
            },
            "required": ["order_id"],
        },
        "fn": lookup_order,
    },
    {
        "name": "lookup_payment",
        "description": "查询用户的支付记录，返回最近几笔支付/退款历史。用于核实扣费争议或退款状态。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户ID，如 USR-ZS"},
            },
            "required": ["user_id"],
        },
        "fn": lookup_payment,
    },
    {
        "name": "verify_account",
        "description": "校验用户账号状态（正常/锁定/冻结）。输入邮箱或手机号，返回账号状态、最后登录时间、MFA 状态等。",
        "parameters": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "用户邮箱或手机号"},
            },
            "required": ["identifier"],
        },
        "fn": verify_account,
    },
    {
        "name": "search_knowledge_base",
        "description": "搜索技术知识库，匹配已知问题和解决方案。用于排查 App 闪退、支付失败、白屏等技术故障。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "技术问题的关键词或症状描述，如'闪退'、'支付失败'"},
            },
            "required": ["query"],
        },
        "fn": search_knowledge_base,
    },
    {
        "name": "search_faq",
        "description": "搜索产品 FAQ 知识库，返回匹配的常见问题及标准回答。用于产品功能、价格、物流、售后等常规咨询。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户的问题关键词"},
            },
            "required": ["query"],
        },
        "fn": search_faq,
    },
]
