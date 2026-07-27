"""Self-correction evaluation with 500 scenarios (8 categories, no C5/C9).

Excludes business rule (C5) and dependency (C9) categories since those errors
cannot be resolved by parameter adjustment alone.

.venv\Scripts\python tests/eval_self_correction_500.py
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


def make_flaky_tool(error_msg: str, good_result: dict):
    call_count = [0]

    async def flaky_fn(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ToolExecutionError(error_msg)
        return good_result

    return flaky_fn, call_count


SYSTEM_PROMPT = (
    "You are a tool-using assistant. Your PRIMARY job is to call tools to complete tasks. "
    "When a tool returns an error, you MUST retry with corrected arguments. "
    "NEVER explain the error to the user. NEVER ask the user for help. "
    "JUST FIX THE PARAMETERS AND RETRY. "
    "Read the error message for hints about the correct format or values."
)


def gen_500_scenarios() -> list[dict]:
    scenarios = []

    # C1: Format Correction (80 scenarios: 8 tool types x 10 variations)
    format_tools = [
        ("lookup_order", "order_id", "ORD-XXX", "ORD-001", [
            "查订单 001", "订单号 abc 帮我查", "查一下 order-123", "帮我看看 45678",
            "跟踪订单 No.789", "查下 ORD 后面是 555", "订单 0X1 是什么状态",
            "帮我查 9999 号订单", "看下单号 42 的物流", "订单 7a3f 在哪",
        ]),
        ("lookup_user", "user_id", "USR-XXX", "USR-ZS", [
            "查用户 张三", "帮我看下用户 李四", "用户 ID 是 wangwu",
            "查一下 ZL 这个用户", "帮我确认下 666 用户", "用户 test_user 的记录",
            "查下 mike 的会员等级", "帮我看看 new_user_01", "用户 老张 的订单",
            "核对下用户 yang 的信息",
        ]),
        ("check_coupon", "coupon_code", "CPN-XXXXX", "CPN-ABC12", [
            "优惠券 abc 能用吗", "券码 summer 核销", "帮我查优惠券 new2024",
            "这个券码 xyz99 有效吗", "我有个券码是 vip50", "优惠码 first 怎么用",
            "券 discount1 过期了吗", "帮我激活 gift 这张券", "查一下 8折券 能用不",
            "券码 welcome 提示无效",
        ]),
        ("track_shipment", "tracking_no", "SF1234567890", "SF1234567890", [
            "查快递 SF123", "快件号 12345", "物流单号 abc", "帮我查 tracking123",
            "快递号 999", "查下 EMS001 的物流", "运单号 TEST42", "查件号 PKG007",
            "我的快递号是 SHIP88", "跟踪号 TRK2024",
        ]),
        ("verify_phone", "phone", "13812345678 (11 digits)", "13812345678", [
            "手机号 1381234", "号码 1590000", "验证 186-8888", "电话 139",
            "手机 17712345678", "帮我验证 188 开头的", "号码 133abc", "电话号 1990000",
            "验证手机 156-7890", "手机 134 号段",
        ]),
        ("lookup_product", "sku", "SKU-XXXXX (SKU-hyphen-5 digits)", "SKU-12345", [
            "查商品 123", "SKU 编号 abc", "产品代码 xyz99", "商品编号 42",
            "查 SKU 777 的库存", "产品号 new001", "商品代码 5a3b", "编号 XXL-001",
            "查编号 9999 的商品", "SKU 码 test 是什么",
        ]),
        ("validate_email", "email", "user@domain.com", "test@example.com", [
            "邮箱 test", "email 是 admin", "验证邮箱 user@", "邮箱地址 hello@world",
            "检查邮箱 my.email", "电邮 contact@", "email 地址 support",
            "邮箱名 info@site", "验证 mail 格式", "邮箱 admin@domain",
        ]),
        ("check_postcode", "postcode", "6 digits", "100081", [
            "邮编 100", "邮政编码 2000", "postcode 12", "地区码 310",
            "查邮编 518 的配送", "邮政编号 4300", "区号邮编 610",
            "快递到 200 号", "邮编查询 71", "邮政编码 050",
        ]),
    ]
    for tool_name, param_name, expected_fmt, example, queries in format_tools:
        for i, query in enumerate(queries):
            scenarios.append({
                "name": f"C1-Fmt-{tool_name}-{i+1}",
                "query": query,
                "tool_name": tool_name,
                "tool_desc": f"Look up information by {param_name}.",
                "tool_params": {
                    "type": "object",
                    "properties": {param_name: {"type": "string", "description": f"{param_name} in format: {expected_fmt}"}},
                    "required": [param_name],
                },
                "error_msg": f"Invalid {param_name} format. Must be {expected_fmt}. Example: {example}.",
                "good_result": {param_name: example, "status": "active", "found": True},
            })

    # C2: Numeric Validation (60 scenarios: 6 param types x 10)
    numeric_params = [
        ("set_price", "amount", "> 0", [0, -1, -10, -50, -100, -0.01, -999, -1.5, -20, -5]),
        ("set_page", "page", "1..50", [0, -1, 999, 1000, 500, -5, 0, 9999, 200, -10]),
        ("set_limit", "limit", "1..100", [0, -1, 999, 5000, 200, 0, 1000, -5, 9999, 0]),
        ("set_quantity", "qty", "1..99", [0, -1, 999, 500, 200, -5, 0, 1000, -10, 0]),
        ("set_rating", "rating", "1..5", [0, -1, 10, 100, 6, -5, 99, 7, -2, 0]),
        ("set_discount", "percent", "1..100", [0, -1, 200, 500, 150, -10, 0, 300, -5, 0]),
    ]
    for tool_name, param_name, range_desc, bad_values in numeric_params:
        for i, bad_val in enumerate(bad_values):
            scenarios.append({
                "name": f"C2-Num-{tool_name}-{i+1}",
                "query": f"Set {param_name} to {bad_val}",
                "tool_name": tool_name,
                "tool_desc": f"Configure {param_name}.",
                "tool_params": {
                    "type": "object",
                    "properties": {param_name: {"type": "number", "description": f"{param_name} (must be {range_desc})"}},
                    "required": [param_name],
                },
                "error_msg": f"Invalid {param_name}: {bad_val}. Must be {range_desc}.",
                "good_result": {"status": "ok", param_name: 1},
            })

    # C3: Enum Values (70 scenarios: 7 enums x 10)
    enum_sets = [
        ("set_status", "status", ["pending", "active", "completed", "cancelled"], [
            "pend", "activate", "complete", "cancel", "pendin", "activ", "complet", "cancell", "pendi", "actv",
        ]),
        ("set_priority", "level", ["low", "normal", "high", "urgent"], [
            "lo", "norm", "hi", "urg", "loe", "nrml", "hgh", "urgt", "loww", "hihg",
        ]),
        ("set_language", "lang", ["zh", "en", "ja", "ko"], [
            "cn", "eng", "jp", "kr", "chs", "english", "jpn", "kor", "zh-cn", "en-us",
        ]),
        ("set_currency", "currency", ["CNY", "USD", "EUR", "JPY"], [
            "rmb", "dollar", "euro", "yen", "￥", "$", "€", "¥", "rmbb", "dollars",
        ]),
        ("set_theme", "theme", ["light", "dark", "auto"], [
            "white", "black", "system", "lite", "drk", "at", "lght", "drak", "whit", "blk",
        ]),
        ("set_sort", "order", ["asc", "desc"], [
            "up", "down", "ascending", "descending", "a", "d", "ascend", "descend", "asce", "des",
        ]),
        ("set_mode", "mode", ["read", "write", "admin"], [
            "r", "w", "a", "reader", "writer", "administrator", "rd", "wr", "adm", "ro",
        ]),
    ]
    for tool_name, param_name, valid_values, bad_values in enum_sets:
        for i, bad_val in enumerate(bad_values):
            scenarios.append({
                "name": f"C3-Enum-{tool_name}-{i+1}",
                "query": f"Set {param_name} to {bad_val}",
                "tool_name": tool_name,
                "tool_desc": f"Configure {param_name}. Valid values: {', '.join(valid_values)}.",
                "tool_params": {
                    "type": "object",
                    "properties": {param_name: {"type": "string", "description": f"One of: {', '.join(valid_values)}"}},
                    "required": [param_name],
                },
                "error_msg": f"Invalid {param_name} '{bad_val}'. Must be one of: {', '.join(valid_values)}.",
                "good_result": {"status": "ok", param_name: valid_values[0]},
            })

    # C4: Entity Not Found (60 scenarios: 6 entity types x 10)
    not_found_entities = [
        ("find_city", "city", [("北京", ["北京市(朝阳)", "北京市(海淀)", "北京市(通州)"], "北京市(朝阳)"),
                               ("上hai", ["上海市(浦东)", "上海市(徐汇)", "上海市(静安)"], "上海市(浦东)"),
                               ("深セン", ["深圳市(南山)", "深圳市(福田)", "深圳市(罗湖)"], "深圳市(南山)"),
                               ("広州", ["广州市(天河)", "广州市(越秀)", "广州市(海珠)"], "广州市(天河)"),
                               ("杭洲", ["杭州市(西湖)", "杭州市(滨江)", "杭州市(余杭)"], "杭州市(西湖)"),
                               ("nanjing", ["南京市(鼓楼)", "南京市(玄武)", "南京市(建邺)"], "南京市(鼓楼)"),
                               ("成嘟", ["成都市(锦江)", "成都市(武侯)", "成都市(高新)"], "成都市(锦江)"),
                               ("重慶", ["重庆市(渝中)", "重庆市(江北)", "重庆市(南岸)"], "重庆市(渝中)"),
                               ("武漢", ["武汉市(武昌)", "武汉市(汉口)", "武汉市(汉阳)"], "武汉市(武昌)"),
                               ("蘇州", ["苏州市(姑苏)", "苏州市(工业园区)", "苏州市(虎丘)"], "苏州市(姑苏)")]),
        ("find_product", "product", [("耳機", ["蓝牙耳机 Pro", "有线耳机 Basic", "降噪耳机 Max"], "蓝牙耳机 Pro"),
                                     ("冲电宝", ["20000mAh 快充版", "10000mAh 轻薄版", "5000mAh 迷你版"], "20000mAh 快充版"),
                                     ("鼠標", ["无线鼠标 Pro", "有线鼠标 Basic", "电竞鼠标 RGB"], "无线鼠标 Pro"),
                                     ("健盘", ["机械键盘 87键", "薄膜键盘 104键", "人体工学键盘"], "机械键盘 87键"),
                                     ("显视器", ["27寸 4K 显示器", "24寸 1080p 显示器", "32寸 曲面显示器"], "27寸 4K 显示器"),
                                     ("手机売", ["iPhone 15 透明壳", "iPhone 15 硅胶壳", "iPhone 15 皮革壳"], "iPhone 15 透明壳"),
                                     ("充電線", ["Type-C 快充线 1m", "Type-C 快充线 2m", "Lightning 线 1m"], "Type-C 快充线 1m"),
                                     ("保护莫", ["钢化膜 iPhone 15", "钢化膜 iPhone 14", "软膜 通用款"], "钢化膜 iPhone 15"),
                                     ("支架", ["手机支架 桌面款", "平板支架 可调节", "笔记本支架 铝合金"], "手机支架 桌面款"),
                                     ("转接頭", ["Type-C 转 HDMI", "Type-C 转 USB-A", "Lightning 转 3.5mm"], "Type-C 转 HDMI")]),
        ("find_brand", "brand", [("華為", ["Huawei", "Honor", "Huawei Enterprise"], "Huawei"),
                                 ("蘋果", ["Apple", "Beats", "Apple Store"], "Apple"),
                                 ("小米", ["Xiaomi", "Redmi", "POCO"], "Xiaomi"),
                                 ("三星", ["Samsung", "Samsung Galaxy", "Samsung Electronics"], "Samsung"),
                                 ("索尼", ["Sony", "Sony Mobile", "Sony Entertainment"], "Sony"),
                                 ("聯想", ["Lenovo", "ThinkPad", "Legion"], "Lenovo"),
                                 ("戴爾", ["Dell", "Alienware", "Dell EMC"], "Dell"),
                                 ("惠普", ["HP", "HP Enterprise", "HP Inc"], "HP"),
                                 ("華碩", ["ASUS", "ROG", "TUF Gaming"], "ASUS"),
                                 ("宏碁", ["Acer", "Predator", "Nitro"], "Acer")]),
        ("find_color", "color", [("紅", ["红色 #FF0000", "暗红 #CC0000", "粉红 #FF9999"], "红色 #FF0000"),
                                 ("藍", ["蓝色 #0000FF", "深蓝 #000099", "浅蓝 #9999FF"], "蓝色 #0000FF"),
                                 ("緑", ["绿色 #00FF00", "深绿 #009900", "浅绿 #99FF99"], "绿色 #00FF00"),
                                 ("黄", ["黄色 #FFFF00", "金黄 #FFCC00", "浅黄 #FFFF99"], "黄色 #FFFF00"),
                                 ("紫", ["紫色 #9900FF", "深紫 #6600CC", "浅紫 #CC99FF"], "紫色 #9900FF"),
                                 ("黑", ["黑色 #000000", "深灰 #333333", "炭黑 #111111"], "黑色 #000000"),
                                 ("白", ["白色 #FFFFFF", "米白 #FFFFF0", "奶白 #FFFDD0"], "白色 #FFFFFF"),
                                 ("灰", ["灰色 #888888", "浅灰 #CCCCCC", "深灰 #444444"], "灰色 #888888"),
                                 ("橙", ["橙色 #FF8800", "深橙 #CC6600", "浅橙 #FFBB66"], "橙色 #FF8800"),
                                 ("棕", ["棕色 #885522", "深棕 #442200", "浅棕 #BB8855"], "棕色 #885522")]),
        ("find_size", "size", [("XL", ["XL (180/100A)", "XXL (185/104A)", "L (175/96A)"], "XL (180/100A)"),
                               ("S码", ["S (160/84A)", "XS (155/80A)", "M (165/88A)"], "S (160/84A)"),
                               ("42码", ["42 (260mm)", "42.5 (265mm)", "43 (270mm)"], "42 (260mm)"),
                               ("L號", ["L (175/96A)", "XL (180/100A)", "M (165/88A)"], "L (175/96A)"),
                               ("36", ["36 (225mm)", "36.5 (230mm)", "37 (235mm)"], "36 (225mm)"),
                               ("M码", ["M (165/88A)", "L (175/96A)", "S (160/84A)"], "M (165/88A)"),
                               ("28腰", ["28 (71cm)", "29 (74cm)", "30 (76cm)"], "28 (71cm)"),
                               ("XXL", ["XXL (185/104A)", "XXXL (190/108A)", "XL (180/100A)"], "XXL (185/104A)"),
                               ("39码", ["39 (245mm)", "39.5 (250mm)", "40 (255mm)"], "39 (245mm)"),
                               ("XS", ["XS (155/80A)", "S (160/84A)", "XXS (150/76A)"], "XS (155/80A)")]),
        ("find_category", "category", [("數碼", ["手机通讯", "电脑办公", "数码配件"], "手机通讯"),
                                       ("家电", ["大家电", "小家电", "厨房电器"], "大家电"),
                                       ("服飾", ["男装", "女装", "童装"], "男装"),
                                       ("美妝", ["面部护肤", "彩妆", "香水"], "面部护肤"),
                                       ("運動", ["跑步鞋", "篮球鞋", "运动服"], "跑步鞋"),
                                       ("食品", ["零食坚果", "饮料冲调", "生鲜水果"], "零食坚果"),
                                       ("家居", ["家纺布艺", "灯具照明", "收纳用品"], "家纺布艺"),
                                       ("母嬰", ["奶粉", "纸尿裤", "玩具"], "奶粉"),
                                       ("圖書", ["小说", "教材", "少儿"], "小说"),
                                       ("汽車", ["机油", "轮胎", "车载电器"], "机油")]),
    ]
    for tool_name, entity_type, test_groups in not_found_entities:
        for query_term, suggestions, correct in test_groups:
            scenarios.append({
                "name": f"C4-NotFound-{tool_name}-{query_term}",
                "query": f"Find {entity_type}: {query_term}",
                "tool_name": tool_name,
                "tool_desc": f"Search {entity_type} by name.",
                "tool_params": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": f"{entity_type} name"}},
                    "required": ["name"],
                },
                "error_msg": f"{entity_type.capitalize()} '{query_term}' not found. Did you mean: {', '.join(suggestions)}?",
                "good_result": {"name": correct, "items": [{"id": 1, "label": correct}]},
            })

    # C6: Empty Parameters (60 scenarios: 6 tools x 10)
    empty_tools = [
        ("search_catalog", "keyword", [
            "帮我搜一下", "搜索", "查一下", "找找看", "帮我搜", "查找", "搜一下这个", "帮我查查", "搜", "找一下",
        ]),
        ("save_draft", "content", [
            "帮我存一下", "保存这个", "存草稿", "保存一下", "存下来", "记录这个", "帮我保存", "存个草稿", "保留", "保存",
        ]),
        ("send_notification", "message", [
            "发个通知", "通知一下", "发消息", "推送", "发一条", "通知", "发过去", "发送", "群发", "推送一下",
        ]),
        ("add_note", "text", [
            "记下来", "备注一下", "记录这个", "写个备注", "记一条", "添加备注", "写下来", "备注", "记上", "标记一下",
        ]),
        ("create_label", "name", [
            "新建标签", "加个标签", "创建标签", "新建一个", "添加标签", "贴标签", "打个标签", "命名标签", "标签", "新建分类",
        ]),
        ("post_comment", "body", [
            "评论一下", "发个评论", "写评论", "留言", "回复一下", "评论", "写个评价", "发表评论", "写一条", "回复",
        ]),
    ]
    for tool_name, param_name, queries in empty_tools:
        for i, query in enumerate(queries):
            scenarios.append({
                "name": f"C6-Empty-{tool_name}-{i+1}",
                "query": query,
                "tool_name": tool_name,
                "tool_desc": f"Handle {tool_name.replace('_', ' ')} requests.",
                "tool_params": {
                    "type": "object",
                    "properties": {param_name: {"type": "string", "description": "Required. Cannot be empty."}},
                    "required": [param_name],
                },
                "error_msg": f"Parameter '{param_name}' is required and cannot be empty. Please provide a value.",
                "good_result": {"success": True},
            })

    # C7: Date Format (60 scenarios)
    dates = [
        ("7月23号", "2026-07-23"), ("明天", "2026-07-24"), ("7/23", "2026-07-23"),
        ("下周一", "2026-07-27"), ("23号", "2026-07-23"), ("这周五", "2026-07-24"),
        ("7.23号", "2026-07-23"), ("7月30日", "2026-07-30"), ("下周二", "2026-07-28"),
        ("今天", "2026-07-23"), ("后天", "2026-07-25"), ("昨天", "2026-07-22"),
        ("8月1号", "2026-08-01"), ("下周三", "2026-07-29"), ("这周六", "2026-07-25"),
        ("7-23", "2026-07-23"), ("23/7", "2026-07-23"), ("July 23", "2026-07-23"),
        ("7月下旬", "2026-07-23"), ("下周五", "2026-07-31"), ("8/1", "2026-08-01"),
        ("8.1", "2026-08-01"), ("8月1日", "2026-08-01"), ("下周", "2026-07-27"),
        ("周末", "2026-07-25"), ("星期一", "2026-07-27"), ("星期二", "2026-07-28"),
        ("星期三", "2026-07-29"), ("星期四", "2026-07-30"), ("星期五", "2026-07-31"),
        ("3天后", "2026-07-26"), ("一周后", "2026-07-30"), ("两周后", "2026-08-06"),
        ("本月15号", "2026-07-15"), ("上月20号", "2026-06-20"), ("下月1号", "2026-08-01"),
        ("2026.7.23", "2026-07-23"), ("2026/7/23", "2026-07-23"), ("23 July 2026", "2026-07-23"),
        ("7-23-2026", "2026-07-23"), ("7月23日2026", "2026-07-23"), ("Jul 23", "2026-07-23"),
        ("23-Jul", "2026-07-23"), ("07/23/26", "2026-07-23"), ("20260723", "2026-07-23"),
        ("下个月5号", "2026-08-05"), ("这个月底", "2026-07-31"), ("下月初", "2026-08-01"),
        ("半年后", "2027-01-23"), ("10天后", "2026-08-02"), ("15天后", "2026-08-07"),
        ("上月1号", "2026-06-01"), ("去年今天", "2025-07-23"), ("明年1月", "2027-01-23"),
        ("三天前", "2026-07-20"), ("一个星期后", "2026-07-30"), ("两周前", "2026-07-09"),
        ("半月后", "2026-08-07"), ("上上周五", "2026-07-17"), ("下下周一", "2026-08-03"),
        ("大后天", "2026-07-26"), ("大前天", "2026-07-21"),
    ]
    for i, (bad_date, good_date) in enumerate(dates):
        scenarios.append({
            "name": f"C7-Date-{i+1}",
            "query": f"Check schedule for {bad_date}",
            "tool_name": "check_schedule",
            "tool_desc": "Check availability for a given date. Date must be YYYY-MM-DD.",
            "tool_params": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "Date in YYYY-MM-DD format"}},
                "required": ["date"],
            },
            "error_msg": f"Invalid date format '{bad_date}'. Please use YYYY-MM-DD format (e.g., {good_date}).",
            "good_result": {"date": good_date, "available": True},
        })

    # C8: Quota/Capacity (60 scenarios: 6 limits x 10)
    quota_tools = [
        ("attach_file", "file_size", "Max 10MB", [
            "15MB", "25MB", "50MB", "100MB", "12MB", "20MB", "30MB", "11MB", "18MB", "22MB",
        ]),
        ("export_records", "row_count", "Max 10000 rows", [
            "50000", "200000", "100000", "500000", "15000", "25000", "30000", "75000", "40000", "60000",
        ]),
        ("send_bulk_email", "recipients", "Max 200 recipients", [
            "500", "1000", "2000", "5000", "300", "400", "600", "800", "1500", "3000",
        ]),
        ("generate_reports", "count", "Max 50 reports", [
            "100", "200", "500", "1000", "60", "75", "150", "80", "120", "300",
        ]),
        ("reserve_rooms", "rooms", "Max 10 rooms", [
            "15", "20", "30", "50", "12", "25", "18", "22", "35", "40",
        ]),
        ("upload_images", "image_count", "Max 20 images", [
            "30", "50", "100", "200", "25", "40", "60", "35", "45", "80",
        ]),
    ]
    for tool_name, limit_name, limit_desc, bad_values in quota_tools:
        for i, bad_val in enumerate(bad_values):
            scenarios.append({
                "name": f"C8-Quota-{tool_name}-{i+1}",
                "query": f"Process with {bad_val} {limit_name}",
                "tool_name": tool_name,
                "tool_desc": f"Handle {tool_name.replace('_', ' ')}. {limit_desc}.",
                "tool_params": {
                    "type": "object",
                    "properties": {"spec": {"type": "string", "description": "Request specification"}},
                    "required": ["spec"],
                },
                "error_msg": f"Limit exceeded: {limit_desc}. Requested: {bad_val}. Please reduce and retry.",
                "good_result": {"status": "resized", "adjusted": True},
            })

    # C10: Rate Limit / Timeout (60 scenarios: 6 types x 10)
    ratelimit_tools = [
        ("send_code", "verification code", "60 seconds cooldown", [
            "验证码", "验证", "code", "短信", "发送", "再来", "重新发", "没收到", "再试", "验证一下",
        ]),
        ("refresh_data", "data refresh", "5 seconds between requests", [
            "刷新", "更新", "重载", "同步", "拉取", "重新加载", "刷新数据", "更新一下", "拉数据", "再来一次",
        ]),
        ("run_query", "database query", "timeout if > 90 days range", [
            "全年数据", "今年", "去年", "所有记录", "全部", "历史数据", "近一年", "一整年", "过往", "全部数据",
        ]),
        ("start_export", "batch export", "max 3 concurrent jobs", [
            "导出4", "导出5", "导出6", "再导出3个", "同时导出", "批量导出4个", "导出10个", "并行导出", "多线程导出", "再开5个",
        ]),
        ("search_fulltext", "fulltext search", "query too broad", [
            "搜所有", "全部", "所有文章", "搜一下", "搜索全部", "全部内容", "全文检索", "搜所有文档", "搜全部数据", "全局搜索",
        ]),
        ("call_external", "external API", "rate limit 100/min", [
            "调用101", "批量调用", "大量请求", "高并发调用", "循环调用", "连续请求", "并发200", "500次请求", "连续调用200次", "大量并发",
        ]),
    ]
    for tool_name, action_desc, limit_desc, queries in ratelimit_tools:
        for i, query in enumerate(queries):
            scenarios.append({
                "name": f"C10-Limit-{tool_name}-{i+1}",
                "query": query,
                "tool_name": tool_name,
                "tool_desc": f"Handle {action_desc} requests.",
                "tool_params": {
                    "type": "object",
                    "properties": {"input": {"type": "string", "description": "Input parameter"}},
                    "required": ["input"],
                },
                "error_msg": f"Rate limited: {limit_desc}. Please wait and retry with adjusted parameters.",
                "good_result": {"status": "completed", "retry_after": "ok"},
            })

    return scenarios


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
    config = AgentConfig(max_iterations=8, system_prompt=SYSTEM_PROMPT, model="deepseek-chat")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": scenario["query"]},
    ]
    event_bus = EventBus()

    start = time.monotonic()
    try:
        state = await run_agent_loop(
            messages=messages, llm=llm, tools=registry, config=config,
            session_id="sc500", node_id="sc500", event_bus=event_bus,
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
    scenarios = gen_500_scenarios()
    print("=" * 70)
    print(f"Self-Correction Evaluation ({len(scenarios)} scenarios, 8 categories)")
    print("Excluding: C5 (business rules), C9 (dependencies)")
    print("=" * 70)
    print()

    llm = LLMClient(model="deepseek-chat")
    results = []
    t_start = time.monotonic()

    for i, scenario in enumerate(scenarios, 1):
        result = await run_scenario(scenario, llm)
        results.append(result)
        if i % 50 == 0:
            elapsed = time.monotonic() - t_start
            done = sum(1 for r in results if r["corrected"])
            print(f"  ... {i}/{len(scenarios)} done, {done} corrected ({elapsed:.0f}s elapsed)", flush=True)
        await asyncio.sleep(0.15)

    total_time = time.monotonic() - t_start

    print()
    print("=" * 70)
    print("Self-Correction Report (500 scenarios)")
    print("=" * 70)

    corrected_count = sum(1 for r in results if r["corrected"])
    rate = corrected_count / len(results) * 100 if results else 0
    print(f"\nOverall self-correction rate: {corrected_count}/{len(results)} = {rate:.1f}%")

    total_calls = sum(r["calls"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    total_successes = sum(r["successes"] for r in results)
    print(f"Total tool calls: {total_calls} (errors: {total_errors}, retry successes: {total_successes})")

    latencies = [r["elapsed_seconds"] for r in results if r["calls"] > 0]
    if latencies:
        sl = sorted(latencies)
        n = len(sl)
        p50_idx = int(n * 0.50)
        p90_idx = int(n * 0.90)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)
        print(f"\nLatency: Mean={statistics.mean(latencies):.1f}s Median={statistics.median(latencies):.1f}s "
              f"P50={sl[p50_idx]:.1f}s P90={sl[p90_idx]:.1f}s P95={sl[p95_idx]:.1f}s P99={sl[p99_idx]:.1f}s")

    agent_errors = sum(1 for r in results if r.get("agent_error"))
    print(f"Agent errors: {agent_errors}/{len(results)}")

    print("\nPer-category self-correction rate:")
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["corrected"])
    for cat in sorted(by_cat):
        hits = by_cat[cat]
        acc = sum(hits) / len(hits) * 100 if hits else 0
        print(f"  {cat}: {sum(hits)}/{len(hits)} = {acc:.0f}%")

    failures = [r for r in results if not r["corrected"]]
    print(f"\nFailed: {len(failures)}/{len(results)}")
    no_retry = sum(1 for r in failures if r["calls"] == 1)
    print(f"  No retry at all: {no_retry}")
    print(f"  Retried but still failed: {len(failures) - no_retry}")

    print(f"\nTotal wall-clock time: {total_time:.0f}s (avg {total_time/len(results):.1f}s per scenario)")
    print(f"Estimated API cost: ~${total_time/60 * 0.02:.2f} (deepseek-chat)")
    print("=" * 70)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
