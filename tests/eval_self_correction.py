"""自纠正能力评测 — 100 个错误注入场景。

每个场景：LLM 调用工具 → 工具抛出 ToolExecutionError → 检查 LLM 是否重试成功。

10 个错误类别 × 每类 10 个变体 = 100 场景。

.venv\Scripts\python tests/eval_self_correction.py
"""

from __future__ import annotations

import asyncio
import itertools
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.agent_config import AgentConfig
from app.core.agent_loop import run_agent_loop
from app.core.event_bus import EventBus
from app.core.llm_client import LLMClient
from app.core.tool_registry import ToolDefinition, ToolExecutionError, ToolRegistry


# ─── Flaky Tool Factory ─────────────────────────────────────

def make_flaky_tool(error_msg: str, good_result: dict):
    call_count = [0]

    async def flaky_fn(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ToolExecutionError(error_msg)
        return good_result

    return flaky_fn, call_count


# ─── Scenario Generator ─────────────────────────────────────

def gen_scenarios() -> list[dict]:
    scenarios = []

    # C1: Identifier Format Correction (10)
    formats = [
        ("order_id", "ORD-XXX", "001", "ORD-001", [
            ("查订单 001", "001"),
            ("订单号 abc 帮我查", "abc"),
            ("查一下 order-123", "order-123"),
            ("帮我看看 45678 这个订单", "45678"),
            ("跟踪订单 No.789", "No.789"),
            ("查下 ORD 后面是 555", "555"),
            ("订单 0X1 是什么状态", "0X1"),
            ("帮我查 9999 号订单", "9999"),
            ("看下单号 42 的物流", "42"),
            ("订单 7a3f 在哪", "7a3f"),
        ]),
        ("user_id", "USR-XXX", "张三", "USR-ZS", [
            ("查用户 张三", "张三"),
            ("帮我看下用户 李四", "李四"),
            ("用户 ID 是 wangwu", "wangwu"),
            ("查一下 ZL 这个用户", "ZL"),
            ("帮我确认下 666 用户的身份", "666"),
            ("用户 test_user 的记录", "test_user"),
            ("查下 mike 的会员等级", "mike"),
            ("帮我看看 new_user_01", "new_user_01"),
            ("用户 老张 的订单", "老张"),
            ("核对下用户 yang 的信息", "yang"),
        ]),
        ("coupon_code", "CPN-XXXXX", "abc", "CPN-ABC12", [
            ("优惠券 abc 能用吗", "abc"),
            ("券码 summer 核销", "summer"),
            ("帮我查优惠券 new2024", "new2024"),
            ("这个券码 xyz99 有效吗", "xyz99"),
            ("我有个券码是 vip50", "vip50"),
            ("优惠码 first 怎么用", "first"),
            ("券 discount1 过期了吗", "discount1"),
            ("帮我激活 gift 这张券", "gift"),
            ("查一下 8折券 能用不", "8折券"),
            ("券码 welcome 提示无效", "welcome"),
        ]),
    ]
    for tool_name, expected_fmt, final_val, final_result, queries in formats:
        for i, (query, bad_val) in enumerate(queries):
            scenarios.append({
                "name": "C1-Fmt-%s-%d" % (tool_name, i + 1),
                "query": query,
                "tool_name": "lookup_" + tool_name,
                "tool_desc": "Look up %s by ID. Returns details." % tool_name,
                "tool_params": {
                    "type": "object",
                    "properties": {tool_name: {"type": "string", "description": "%s in %s format" % (tool_name, expected_fmt)}},
                    "required": [tool_name],
                },
                "error_msg": "Invalid %s format. Must be %s (e.g., %s)." % (tool_name, expected_fmt, final_result),
                "good_result": {tool_name: final_result, "status": "active", "found": True},
            })

    # C2: Numeric Validation (10)
    numeric_tools = [
        ("refund_amount", "refund amount", "> 0", [
            ("申请退 0 元", {"amount": 0}, {"refund_id": "R001", "amount": 10.0}),
            ("退款金额 -10", {"amount": -10}, {"refund_id": "R002", "amount": 10.0}),
            ("退运费 0 元", {"amount": 0}, {"refund_id": "R003", "amount": 8.0}),
            ("补偿 0 块钱", {"amount": 0}, {"refund_id": "R004", "amount": 5.0}),
            ("帮我退 -5 元差价", {"amount": -5}, {"refund_id": "R005", "amount": 5.0}),
        ]),
        ("list_page", "page number", "1..5", [
            ("翻到第 0 页", {"page": 0}, {"page": 1, "items": ["A", "B"]}),
            ("跳到第 999 页", {"page": 999}, {"page": 5, "items": ["C", "D"]}),
            ("第 -1 页", {"page": -1}, {"page": 1, "items": ["E"]}),
            ("看第 100 页订单", {"page": 100}, {"page": 5, "items": ["F"]}),
            ("第 88888 页有什么", {"page": 88888}, {"page": 3, "items": ["G"]}),
        ]),
    ]
    for tool_name, param_desc, range_desc, test_cases in numeric_tools:
        for i, (query, bad_args, good_result) in enumerate(test_cases):
            param_name = list(bad_args.keys())[0]
            scenarios.append({
                "name": "C2-Num-%s-%d" % (tool_name, i + 1),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Process %s." % param_desc,
                "tool_params": {
                    "type": "object",
                    "properties": {param_name: {"type": "number" if isinstance(list(bad_args.values())[0], (int, float)) else "integer",
                                                 "description": "%s (must be %s)" % (param_desc, range_desc)}},
                    "required": [param_name],
                },
                "error_msg": "Invalid %s: must be %s." % (param_desc, range_desc),
                "good_result": good_result,
            })

    # C3: Enum Value Correction (10)
    enum_cases = [
        ("update_status", "order status", ["pending", "shipped", "delivered", "cancelled", "refunded"], [
            ("把订单改成 cancel", {"status": "cancel"}, {"status": "cancelled"}),
            ("状态改为 ship", {"status": "ship"}, {"status": "shipped"}),
            ("标记为 refund", {"status": "refund"}, {"status": "refunded"}),
            ("改成 deliver 状态", {"status": "deliver"}, {"status": "delivered"}),
            ("把状态设为 pend", {"status": "pend"}, {"status": "pending"}),
        ]),
        ("set_priority", "ticket priority", ["low", "normal", "high", "urgent"], [
            ("优先级设为 紧急", {"level": "紧急"}, {"level": "urgent"}),
            ("标为 高优先级", {"level": "高"}, {"level": "high"}),
            ("改成 一般", {"level": "一般"}, {"level": "normal"}),
            ("优先级 低", {"level": "低"}, {"level": "low"}),
            ("设为 critical", {"level": "critical"}, {"level": "urgent"}),
        ]),
    ]
    for tool_name, param_desc, valid_values, test_cases in enum_cases:
        for i, (query, bad_args, good_result) in enumerate(test_cases):
            param_name = list(bad_args.keys())[0]
            scenarios.append({
                "name": "C3-Enum-%s-%d" % (tool_name, i + 1),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Update %s." % param_desc,
                "tool_params": {
                    "type": "object",
                    "properties": {param_name: {"type": "string", "description": "%s. Valid: %s" % (param_desc, ", ".join(valid_values))}},
                    "required": [param_name],
                },
                "error_msg": "Invalid %s '%s'. Valid values: %s." % (param_desc, list(bad_args.values())[0], ", ".join(valid_values)),
                "good_result": good_result,
            })

    # C4: Entity Not Found with Suggestions (10)
    not_found_cases = [
        ("search_category", "product category", [
            ("查查 电子数码 分类", "电子数码", ["手机通讯", "电脑办公", "数码配件"], "数码配件"),
            ("帮我找 食品饮料 类别", "食品饮料", ["零食坚果", "饮料冲调", "生鲜水果"], "零食坚果"),
            ("看看 家具家装 有什么", "家具家装", ["家纺布艺", "灯具照明", "收纳用品"], "家纺布艺"),
        ]),
        ("find_city", "city name", [
            ("北京 有门店吗", "北京", ["北京市(朝阳)", "北京市(海淀)", "北京市(通州)"], "北京市(朝阳)"),
            ("上hai 能配送吗", "上hai", ["上海市(浦东)", "上海市(徐汇)", "上海市(静安)"], "上海市(浦东)"),
        ]),
    ]
    idx = itertools.count(1)
    for tool_name, entity_type, test_cases in not_found_cases:
        for query, bad_val, suggestions, correct_val in test_cases:
            i = next(idx)
            scenarios.append({
                "name": "C4-NotFound-%s-%d" % (tool_name, i),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Search %s." % entity_type,
                "tool_params": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "%s name" % entity_type}},
                    "required": ["name"],
                },
                "error_msg": "%s '%s' not found. Did you mean: %s?" % (entity_type.capitalize(), bad_val, ", ".join(suggestions)),
                "good_result": {"name": correct_val, "items": [{"id": 1, "name": "Sample"}]},
            })

    # C5: Business Rule Violation (10)
    rule_cases = [
        ("cancel_order", "cancel order", "已发货订单不可取消，需走退货流程", [
            ("帮我取消已发货的订单", "取消已发货订单需先申请退货"),
            ("这个订单我不要了取消吧", "已发货订单无法直接取消，请申请退货退款"),
        ]),
        ("apply_discount", "apply discount", "该优惠券已达到使用上限", [
            ("帮我把这张券用上", "优惠券已达使用次数上限"),
            ("用我的满减券", "该满减优惠券已失效或达上限"),
        ]),
        ("change_address", "change shipping address", "已出库订单无法修改地址", [
            ("帮我改一下收货地址", "订单已出库，无法修改收货地址"),
            ("送到另一个地址可以吗", "地址修改仅支持未出库订单"),
        ]),
        ("merge_orders", "merge orders", "不同收货地址的订单无法合并", [
            ("帮我把两个单子合并发货", "两个订单收货地址不同，无法合并"),
            ("这几个订单能一起发吗", "合并发货仅支持同地址订单"),
        ]),
        ("extend_return_window", "extend return", "超过售后期无法延长", [
            ("帮我延长退货时间", "退货申请已超过15天售后期，无法延长"),
            ("这个能晚点退吗", "订单已超出退货时效"),
        ]),
    ]
    for i, (tool_name, action_desc, rule_msg, test_cases) in enumerate(rule_cases, 1):
        for j, (query, detail_msg) in enumerate(test_cases, 1):
            scenarios.append({
                "name": "C5-Rule-%s-%d" % (tool_name, i * 10 + j),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Process %s request." % action_desc,
                "tool_params": {
                    "type": "object",
                    "properties": {"reason": {"type": "string", "description": "Reason for the request"}},
                    "required": ["reason"],
                },
                "error_msg": "%s: %s" % (rule_msg, detail_msg),
                "good_result": {"alternative": "已转人工处理", "ticket_created": True},
            })

    # C6: Empty/Missing Parameter (10)
    empty_param_cases = [
        ("search_products", "search products", [
            ("帮我搜一下", {"keyword": ""}),
            ("搜索", {"keyword": ""}),
        ]),
        ("save_note", "save note", [
            ("帮我记个备注", {"content": ""}),
            ("把这个存下来", {"content": ""}),
        ]),
        ("send_message", "send message", [
            ("帮我发条消息", {"text": ""}),
            ("发过去吧", {"text": ""}),
        ]),
        ("add_to_cart", "add to cart", [
            ("加到购物车", {"product_id": ""}),
            ("这个也一起买", {"product_id": ""}),
        ]),
        ("rate_product", "rate product", [
            ("给个好评", {"rating": ""}),
            ("评价一下吧", {"rating": ""}),
        ]),
    ]
    for i, (tool_name, action_desc, test_cases) in enumerate(empty_param_cases, 1):
        for j, (query, bad_args) in enumerate(test_cases, 1):
            param_name = list(bad_args.keys())[0]
            scenarios.append({
                "name": "C6-Empty-%s-%d" % (tool_name, i * 10 + j),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "%s." % action_desc.capitalize(),
                "tool_params": {
                    "type": "object",
                    "properties": {param_name: {"type": "string", "description": "Required parameter. Cannot be empty."}},
                    "required": [param_name],
                },
                "error_msg": "Parameter '%s' cannot be empty. Please provide a value." % param_name,
                "good_result": {"success": True, "id": "auto-generated"},
            })

    # C7: Date Format Correction (10)
    date_cases = [
        ("check_schedule", "date in YYYY-MM-DD", [
            ("查7月23号的排期", "7月23号", "2026-07-23"),
            ("明天有什么安排", "明天", "2026-07-24"),
            ("7/23的配送", "7/23", "2026-07-23"),
            ("下周一有档期吗", "下周一", "2026-07-27"),
            ("23号下午能送吗", "23号", "2026-07-23"),
            ("查这周五的", "这周五", "2026-07-24"),
            ("7.23号发货", "7.23号", "2026-07-23"),
            ("7月30日", "7月30日", "2026-07-30"),
            ("看下下周二的", "下周二", "2026-07-28"),
            ("今天能到吗", "今天", "2026-07-23"),
        ]),
    ]
    for tool_name, param_desc, test_cases in date_cases:
        for i, (query, bad_date, good_date) in enumerate(test_cases, 1):
            scenarios.append({
                "name": "C7-Date-%s-%d" % (tool_name, i),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Check schedule for a given date.",
                "tool_params": {
                    "type": "object",
                    "properties": {"date": {"type": "string", "description": param_desc}},
                    "required": ["date"],
                },
                "error_msg": "Invalid date format '%s'. Expected YYYY-MM-DD (e.g., %s)." % (bad_date, good_date),
                "good_result": {"date": good_date, "slots_available": 3},
            })

    # C8: Capacity / Quota (10)
    quota_cases = [
        ("upload_image", "file size", "Max 10MB. Your file is 25MB.", [
            ("传这张照片", "文件过大"),
        ]),
        ("export_data", "row count", "Max 50000 rows per export. Requested 200000.", [
            ("帮我导出所有数据", "数据量超过导出上限"),
        ]),
        ("send_bulk_sms", "recipient count", "Max 100 recipients per batch. Requested 5000.", [
            ("给所有用户群发短信", "批量发送数量超限"),
        ]),
        ("create_coupons", "coupon count", "Max 1000 coupons per batch. Requested 50000.", [
            ("生成一批优惠券", "优惠券生成数量超限"),
        ]),
        ("reserve_seats", "seat count", "Only 3 seats remaining. Requested 10.", [
            ("帮我订10个位子", "座位不足"),
        ]),
    ]
    for i, (tool_name, limit_desc, error_msg, test_cases) in enumerate(quota_cases, 1):
        for j, (query, detail) in enumerate(test_cases, 1):
            scenarios.append({
                "name": "C8-Quota-%s-%d" % (tool_name, i * 10 + j),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Handle %s." % tool_name.replace("_", " "),
                "tool_params": {
                    "type": "object",
                    "properties": {"spec": {"type": "string", "description": "Request specification"}},
                    "required": ["spec"],
                },
                "error_msg": "%s %s" % (error_msg, detail),
                "good_result": {"status": "resized", "limit_applied": True},
            })

    # C9: Dependency / Prerequisite (10)
    dep_cases = [
        ("verify_payment", "verify payment", "请先设置支付密码", [
            ("帮我验证这笔付款", "需先设置支付密码"),
        ]),
        ("enable_2fa", "enable 2FA", "请先绑定手机号", [
            ("帮我开启两步验证", "需先绑定手机号"),
        ]),
        ("withdraw_balance", "withdraw", "请先完成实名认证", [
            ("帮我把余额提出来", "需先完成实名认证"),
        ]),
        ("publish_review", "publish review", "请先完成订单评价", [
            ("帮我发布这条评价", "需先完成订单才能评价"),
        ]),
        ("request_invoice", "request invoice", "请先确认收货", [
            ("帮我开张发票", "需先确认收货后才能申请发票"),
        ]),
    ]
    for i, (tool_name, action_desc, error_msg, test_cases) in enumerate(dep_cases, 1):
        for j, (query, detail) in enumerate(test_cases, 1):
            scenarios.append({
                "name": "C9-Dep-%s-%d" % (tool_name, i * 10 + j),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Handle %s." % action_desc,
                "tool_params": {
                    "type": "object",
                    "properties": {"request": {"type": "string", "description": "Request details"}},
                    "required": ["request"],
                },
                "error_msg": "%s: %s" % (error_msg, detail),
                "good_result": {"guided": True, "next_step": "complete prerequisite first"},
            })

    # C10: Rate Limit / Timeout (10)
    ratelimit_cases = [
        ("send_verification_code", "send code", "60秒内已发送过验证码，请稍后重试", [
            ("再发一次验证码", "验证码发送频率过高"),
        ]),
        ("refresh_feed", "refresh feed", "请求过于频繁，请5秒后重试", [
            ("刷新一下", "刷新频率超限"),
        ]),
        ("query_report", "query report", "查询超时：时间范围过大，请缩小至90天内", [
            ("帮我查今年的报表", "查询时间范围过大"),
        ]),
        ("batch_export", "batch export", "并发导出任务已达上限(3个)，请等待完成后再试", [
            ("再导出一份数据", "并发导出任务数达到上限"),
        ]),
        ("search_fulltext", "fulltext search", "搜索超时，请尝试更精确的关键词", [
            ("帮我搜一下", "搜索范围过大导致超时"),
        ]),
    ]
    for i, (tool_name, action_desc, error_msg, test_cases) in enumerate(ratelimit_cases, 1):
        for j, (query, detail) in enumerate(test_cases, 1):
            scenarios.append({
                "name": "C10-Limit-%s-%d" % (tool_name, i * 10 + j),
                "query": query,
                "tool_name": tool_name,
                "tool_desc": "Handle %s." % action_desc,
                "tool_params": {
                    "type": "object",
                    "properties": {"input": {"type": "string", "description": "Input parameter"}},
                    "required": ["input"],
                },
                "error_msg": "%s: %s" % (error_msg, detail),
                "good_result": {"success": True, "retry_after": "wait and retry"},
            })

    # Ensure we have exactly 100 (pad if needed from templates)
    # The generator should produce close to 100 scenarios; trim or pad to exactly 100
    return scenarios[:100]


# ─── Runner ─────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = (
    "You are a helpful assistant. When you call a tool and it returns an error, "
    "read the error message carefully, fix the issue described, and retry the tool "
    "with corrected arguments. Always retry at least once before giving up. "
    "If the error requires information you do not have, make a reasonable guess "
    "based on the error message's hints (e.g., suggested values, format examples)."
)


async def run_scenario(scenario: dict, llm: LLMClient) -> dict:
    flaky_fn, call_counter = make_flaky_tool(
        scenario["error_msg"], scenario["good_result"]
    )

    registry = ToolRegistry()
    await registry.register(ToolDefinition(
        name=scenario["tool_name"],
        description=scenario["tool_desc"],
        parameters=scenario["tool_params"],
        fn=flaky_fn,
        source="eval",
    ))

    config = AgentConfig(max_iterations=8, system_prompt=SYSTEM_PROMPT_TEMPLATE, model="deepseek-chat")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE},
        {"role": "user", "content": scenario["query"]},
    ]
    event_bus = EventBus()

    start = time.monotonic()
    try:
        state = await run_agent_loop(
            messages=messages, llm=llm, tools=registry, config=config,
            session_id="sc", node_id="sc", event_bus=event_bus,
        )
        elapsed = time.monotonic() - start
        events = event_bus.flush_events()

        tool_results = [e for e in events if e.get("type") == "tool_result"]
        errors = [e for e in tool_results if e.get("is_error")]
        successes = [e for e in tool_results if not e.get("is_error")]
        corrected = len(errors) > 0 and len(successes) > 0

        return {
            "name": scenario["name"],
            "category": scenario["name"].split("-")[0],
            "corrected": corrected,
            "calls": len([e for e in events if e.get("type") == "tool_call"]),
            "errors": len(errors),
            "successes": len(successes),
            "elapsed_seconds": round(elapsed, 2),
            "agent_error": state.error,
        }
    except Exception as exc:
        return {
            "name": scenario["name"],
            "category": scenario["name"].split("-")[0],
            "corrected": False,
            "calls": 0, "errors": 0, "successes": 0,
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "agent_error": str(exc),
        }


async def main():
    scenarios = gen_scenarios()
    print("=" * 70)
    print("Self-Correction Evaluation (%d error-injection scenarios)" % len(scenarios))
    print("10 categories x ~10 variations each")
    print("=" * 70)
    print()

    llm = LLMClient(model="deepseek-chat")
    results = []
    t_start = time.monotonic()

    for i, scenario in enumerate(scenarios, 1):
        result = await run_scenario(scenario, llm)
        results.append(result)

        status = "OK" if result["corrected"] else "FAIL"
        if i % 20 == 0:
            print("  ... %d/%d done (%.0fs elapsed)" % (i, len(scenarios), time.monotonic() - t_start), flush=True)

        await asyncio.sleep(0.2)

    total_time = time.monotonic() - t_start

    # Report
    print()
    print("=" * 70)
    print("Self-Correction Report")
    print("=" * 70)

    corrected_count = sum(1 for r in results if r["corrected"])
    rate = corrected_count / len(results) * 100 if results else 0
    print("\nOverall self-correction rate: %d/%d = %.1f%%" % (corrected_count, len(results), rate))

    total_call_events = sum(r["calls"] for r in results)
    total_error_events = sum(r["errors"] for r in results)
    print("Total tool calls: %d (errors: %d, retry successes: %d)" % (
        total_call_events, total_error_events, sum(r["successes"] for r in results)))

    latencies = [r["elapsed_seconds"] for r in results if r["calls"] > 0]
    if latencies:
        sl = sorted(latencies)
        n = len(sl)
        print("\nScenario latency (seconds):")
        print("  Mean: %.1f  Median: %.1f  P50: %.1f  P90: %.1f  P95: %.1f" % (
            statistics.mean(latencies), statistics.median(latencies),
            sl[int(n * 0.50)], sl[int(n * 0.90)], sl[int(n * 0.95)]))

    agent_errors = sum(1 for r in results if r.get("agent_error"))
    print("\nAgent-level errors: %d/%d" % (agent_errors, len(results)))

    # Per-category breakdown
    print("\nPer-category self-correction rate:")
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["corrected"])
    for cat, hits in sorted(by_cat.items()):
        acc = sum(hits) / len(hits) * 100 if hits else 0
        print("  %s: %d/%d = %.0f%%" % (cat, sum(hits), len(hits), acc))

    # Non-corrected details
    failures = [r for r in results if not r["corrected"]]
    if failures:
        print("\nFailed scenarios (%d):" % len(failures))
        for r in failures[:10]:
            reason = "agent error: %s" % r.get("agent_error", "")[:60] if r.get("agent_error") else "no retry"
            print("  - %s: %s" % (r["name"], reason))

    print("\nTotal wall-clock time: %.0fs (avg %.1fs per scenario)" % (total_time, total_time / len(results)))
    print("=" * 70)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
