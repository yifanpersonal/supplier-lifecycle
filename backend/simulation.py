"""确定性、月步长的演示模型。全部参数均为假设，不是寿命标定结果。"""
import math
from copy import deepcopy

GROUPS = [
    {"id": "seal", "name": "密封系统", "color": "#4169e1", "base_rate": .028, "replacement": 80,
     "mechanism": "O 型圈与密封垫作为老化分析对象；未取得橡胶寿命曲线，暂用假设衰减率。"},
    {"id": "spring", "name": "弹簧机构", "color": "#13a49a", "base_rate": .019, "replacement": 65,
     "mechanism": "由真实密封弹簧条目确定对象；静载松弛与动作频次的影响采用演示系数。"},
    {"id": "electric", "name": "电气与驱动", "color": "#9465d3", "base_rate": .025, "replacement": 150,
     "mechanism": "由电容、线圈、铁芯等实际条目归类；温湿度影响未标定，不能解释为真实失效概率。"},
    {"id": "body", "name": "阀体结构", "color": "#c68b37", "base_rate": .013, "replacement": 240,
     "mechanism": "阀体和阀盖组成承压分析组；实际腐蚀率未知，使用室外/盐雾场景假设。"},
    {"id": "battery", "name": "电池供能", "color": "#d66879", "base_rate": .095, "replacement": 15,
     "mechanism": "存在 7 号碱性电池记录，但无容量与电流数据；这里只演示定期更换逻辑。"},
]

DEFAULTS = {"location": "廊坊", "project_name": "燃气入户阀门评估", "years": 20,
            "temperature": 15, "humidity": 60, "cycles": 52, "exposure": "indoor",
            "warning": 70, "failure": 45, "quantity": 100, "purchase": 450,
            "installation": 80, "inspection": 12, "labor": 35, "downtime": 100,
            "inspection_interval": 1,
            "rates": {g["id"]: g["base_rate"] for g in GROUPS},
            "replacements": {g["id"]: g["replacement"] for g in GROUPS}}
PRESETS = [{"name": "廊坊", "temperature": 15, "humidity": 60},
           {"name": "广州", "temperature": 25, "humidity": 80},
           {"name": "成都", "temperature": 18, "humidity": 75},
           {"name": "自定义", "temperature": 20, "humidity": 65}]


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON 对象")
    result = deepcopy(DEFAULTS)
    unknown = set(payload) - set(result) - {"product_id"}
    if unknown:
        raise ValueError("未知字段：" + ", ".join(sorted(unknown)))
    result.update({k: v for k, v in payload.items() if k in result})
    bounds = {"years": (1, 40), "temperature": (-30, 60), "humidity": (0, 100),
              "cycles": (0, 100000), "warning": (1, 99), "failure": (1, 98),
              "quantity": (1, 100000), "purchase": (0, 1000000), "installation": (0, 1000000),
              "inspection": (0, 1000000), "labor": (0, 1000000), "downtime": (0, 1000000),
              "inspection_interval": (1, 10)}
    for key, (low, high) in bounds.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} 必须为 {low}～{high} 的有限数值")
    for key in ("years", "quantity", "inspection_interval"):
        if int(result[key]) != result[key]:
            raise ValueError(f"{key} 必须是整数")
        result[key] = int(result[key])
    if result["warning"] <= result["failure"]:
        raise ValueError("预警线必须高于失效阈值")
    if result["exposure"] not in ("indoor", "outdoor", "coastal"):
        raise ValueError("未知安装环境")
    for key in ("location", "project_name"):
        if not isinstance(result[key], str) or not 1 <= len(result[key].strip()) <= 100:
            raise ValueError(f"{key} 不能为空且不能超过 100 字")
        result[key] = result[key].strip()
    for key, low, high in [("rates", 0, .5), ("replacements", 0, 1000000)]:
        if not isinstance(result[key], dict) or set(result[key]) != {g["id"] for g in GROUPS}:
            raise ValueError(f"{key} 必须包含五个分析系统")
        for val in result[key].values():
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not low <= val <= high:
                raise ValueError(f"{key} 参数超出范围")
    return result


def threshold_time(rate, threshold):
    return round(-math.log(threshold / 100) / rate, 2) if rate > 0 else None


def build_systems(catalog, settings):
    output = []
    for definition in GROUPS:
        group = deepcopy(definition)
        ids = [n["id"] for n in catalog["nodes"] if n["group"] == group["id"]]
        if not ids:
            continue
        selected_ids = set(ids)
        members = [n for n in catalog["nodes"] if n["id"] in selected_ids]
        temp = max(.7, 1 + (settings["temperature"] - 20) * .015)
        humidity = 1 + max(0, settings["humidity"] - 60) * (.006 if group["id"] in ("electric", "body") else .003)
        exposure = {"indoor": 1, "outdoor": 1.18, "coastal": 1.4}[settings["exposure"]]
        if group["id"] == "battery":
            exposure = 1 + (exposure - 1) * .3
        cycles = 1 + settings["cycles"] / (6000 if group["id"] in ("seal", "spring") else 30000)
        factor = temp * humidity * exposure * cycles
        rate = settings["rates"][group["id"]] * factor
        tests = sorted({q for n in members for q in n["inspection_ids"]})
        docs = sorted({d for n in members for d in n["document_ids"]})
        group.update({"base_rate": settings["rates"][group["id"]], "effective_rate": rate,
                      "replacement": settings["replacements"][group["id"]], "factor": factor,
                      "factors": {"temperature": temp, "humidity": humidity, "exposure": exposure, "cycles": cycles},
                      "node_ids": ids, "inspection_ids": tests, "document_ids": docs,
                      "initial_health": 100, "initial_health_source": "归一化演示起点，不由合格率换算",
                      "warning_year": threshold_time(rate, settings["warning"]),
                      "failure_year": threshold_time(rate, settings["failure"]),
                      "mechanism": group["mechanism"]})
        output.append(group)
    return output


def policy_simulation(settings, systems, policy):
    """每月检测是否触线，更换分析组后年龄清零；费用按设备数线性放大。"""
    quantity = settings["quantity"]
    totals = {"purchase": settings["purchase"] * quantity,
              "installation": settings["installation"] * quantity,
              "inspection": 0., "replacement": 0., "labor": 0., "downtime": 0.}
    age = {g["id"]: 0 for g in systems}
    events, series = [], []
    threshold = settings["warning"] if policy == "preventive" else settings["failure"]
    for month in range(settings["years"] * 12 + 1):
        current = {}
        if month and month % (settings["inspection_interval"] * 12) == 0:
            totals["inspection"] += settings["inspection"] * quantity
        for group in systems:
            key = group["id"]
            if month:
                age[key] += 1
            before = 100 * math.exp(-group["effective_rate"] * age[key] / 12)
            if month and before <= threshold:
                costs = {"replacement": group["replacement"] * quantity,
                         "labor": settings["labor"] * quantity,
                         "downtime": (settings["downtime"] * quantity if policy == "corrective" else 0)}
                for cat, amount in costs.items():
                    totals[cat] += amount
                events.append({"month": month, "year": round(month / 12, 2), "system_id": key,
                               "system": group["name"], "trigger_health": round(before, 2),
                               "action": "预警触线：计划更换" if policy == "preventive" else "失效触线：更换恢复",
                               "cost": round(sum(costs.values()), 2), "breakdown": costs})
                age[key] = 0
                before = 100
            current[key] = round(before, 2)
        series.append({"year": round(month / 12, 4), "health": min(current.values()),
                       "systems": current, "cost": round(sum(totals.values()), 2)})
    return {"id": policy, "name": "预防性维护" if policy == "preventive" else "到失效阈值更换",
            "series": series, "events": events, "breakdown": {k: round(v, 2) for k, v in totals.items()},
            "total": round(sum(totals.values()), 2), "per_unit": round(sum(totals.values()) / quantity, 2)}


def simulate(catalog, payload):
    if payload.get("product_id", catalog["product"]["id"]) != catalog["product"]["id"]:
        raise ValueError("未找到产品")
    settings = validate(payload)
    systems = build_systems(catalog, settings)
    baseline = []
    for month in range(settings["years"] * 12 + 1):
        values = {g["id"]: round(100 * math.exp(-g["effective_rate"] * month / 12), 2) for g in systems}
        baseline.append({"year": round(month / 12, 4), "health": min(values.values()), "systems": values})
    return {"model_version": "rule-demo-1.0", "model_type": "未标定规则演示", "llm_enabled": False,
            "product": catalog["product"], "source_sha256": catalog["source_sha256"],
            "settings": settings, "systems": systems, "baseline": baseline,
            "policies": [policy_simulation(settings, systems, policy) for policy in ("preventive", "corrective")],
            "limitations": ["健康指数不等于可靠度或故障概率；100 是统一归一化起点。",
                            "预测不含维护曲线为自然衰减；维护方案曲线在更换后重置相应系统。",
                            "月份内理想化触线更换，不模拟发现延迟；用于算法展示，不是现场安全决策。",
                            "费用为未折现累计支出；不含能耗、通胀、残值、事故损失和质保抵扣。",
                            "同组批次不按 BOM 行数计费；每次是单台分析组更换包，同批设备同步更换是假设。",
                            "城市温湿度是可编辑场景预设，未联网查询真实气象。"]}
