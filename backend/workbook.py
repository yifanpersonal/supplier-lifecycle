"""只读解析 XLSX 的 XML，不执行宏、公式，不请求外部报告链接。"""
import hashlib
import posixpath
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def column_index(address):
    result = 0
    for c in re.match(r"[A-Z]+", address)[0]:
        result = result * 26 + ord(c) - 64
    return result - 1


def read_sheets(path):
    """保留空字符串、行号、原始文本与超链接；编码不转浮点数。"""
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")):
                strings.append("".join(t.text or "" for t in item.findall(".//m:t", NS)))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in
                ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = {}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).findall("m:sheets/m:sheet", NS):
            target = rels[sheet.attrib[f"{{{NS['r']}}}id"]]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            root = ET.fromstring(archive.read(member))
            rows = []
            for row in root.findall("m:sheetData/m:row", NS):
                values = {}
                for cell in row.findall("m:c", NS):
                    text = cell.findtext("m:v", "", NS)
                    if cell.attrib.get("t") == "s":
                        text = strings[int(text)] if text else ""
                    elif cell.attrib.get("t") == "inlineStr":
                        text = "".join(x.text or "" for x in cell.findall(".//m:t", NS))
                    values[column_index(cell.attrib["r"])] = text
                size = max(values, default=-1) + 1
                rows.append((int(row.attrib["r"]), [values.get(i, "") for i in range(size)]))
            relation_file = posixpath.dirname(member) + "/_rels/" + posixpath.basename(member) + ".rels"
            links = {}
            relations = {}
            if relation_file in archive.namelist():
                relations = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(archive.read(relation_file))}
            for link in root.findall("m:hyperlinks/m:hyperlink", NS):
                links[link.attrib["ref"]] = {"target": relations.get(link.attrib.get(f"{{{NS['r']}}}id"), ""),
                                             "location": link.attrib.get("location", "")}
            sheets[sheet.attrib["name"]] = {"rows": rows, "links": links}
    return sheets


def component_group(name):
    # 关键词只作部件归类，不把材料名称当作实测寿命。
    for group, pattern in [("seal", r"O型圈|密封垫"), ("spring", r"密封弹簧"),
                           ("battery", r"碱性电池"), ("electric", r"电容|线圈|铁芯|无线蓝牙模块"),
                           ("body", r"阀体|阀盖")]:
        if re.search(pattern, name):
            return group
    return None


def load_catalog(path):
    sheets = read_sheets(path)
    nodes, documents, stack = [], {}, {}
    by_key = defaultdict(list)
    warnings = []
    for row_number, values in sheets["材料构成"]["rows"][1:]:
        v = (values + [""] * 11)[:11]
        if not v[0].strip().isdigit():
            continue
        level = int(v[0])
        parent = stack.get(level - 1)
        if level > 1 and parent is None:
            warnings.append(f"材料构成第 {row_number} 行缺少直接父层级")
        code, batch = v[1].strip(), v[4].strip()
        doc_ids = []
        for index in range(6, 11):
            if not v[index].strip():
                continue
            ref = f"{chr(65 + index)}{row_number}"
            target = sheets["材料构成"]["links"].get(ref, {}).get("target", "")
            parsed = urlsplit(target)
            # 不向浏览器泄露签名凭据；文件名相同但 URL 路径不同的报告保持独立。
            identity = parsed.netloc + parsed.path if target else v[index]
            doc_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
            expiry = parse_qs(parsed.query).get("e", [None])[0]
            expiry_date = datetime.fromtimestamp(int(expiry), timezone.utc).isoformat() if expiry and expiry.isdigit() else None
            documents.setdefault(doc_id, {"id": doc_id, "name": v[index], "source": "供应商文件索引",
                                         "expires_at": expiry_date, "content_loaded": False,
                                         "status": "未取得附件原文", "refs": []})
            documents[doc_id]["refs"].append(ref)
            doc_ids.append(doc_id)
        node = {"id": f"n{row_number}", "parent_id": parent, "level": level,
                "code": code, "name": v[2], "spec": v[3], "batch": batch,
                "supplier": v[5], "document_ids": doc_ids, "source_row": row_number,
                "group": component_group(v[2]), "inspection_ids": [], "children": []}
        nodes.append(node)
        by_key[(code, batch)].append(node)
        stack[level] = node["id"]
        stack = {k: val for k, val in stack.items() if k <= level}
    node_map = {n["id"]: n for n in nodes}
    for n in nodes:
        if n["parent_id"] in node_map:
            node_map[n["parent_id"]]["children"].append(n["id"])

    inspections = []
    for row_number, values in sheets["质量明细"]["rows"]:
        v = (values + [""] * 54)[:54]
        if v[0] not in {"采购检验", "产品检验", "委外检验"}:
            continue
        record = {"id": f"q{row_number}", "source_row": row_number, "type": v[0], "order": v[1],
                  "date": v[2], "code": v[6].strip(), "name": v[7], "batch": v[9].strip(),
                  "project": v[17], "requirement": v[18], "severity": v[19] or v[30],
                  "measured_raw": v[25], "result": v[33], "sample_size": v[40],
                  "qualified": v[41], "unqualified": v[42]}
        inspections.append(record)
        for node in by_key.get((record["code"], record["batch"]), []):
            node["inspection_ids"].append(record["id"])

    production = []
    for row_number, values in sheets["生产过程统计"]["rows"][1:]:
        v = (values + [""] * 7)[:7]
        if not v[0]:
            continue
        production.append(dict(zip(["order", "station", "project", "tested", "qualified", "unqualified", "rate"], v), source_row=row_number))
    root = next(n for n in nodes if n["level"] == 1)
    unique_keys = list(by_key.values())
    stats = {"bom_rows": len(nodes), "unique_codes": len({n["code"] for n in nodes}),
             "unique_batch_items": len(unique_keys), "max_level": max(n["level"] for n in nodes),
             "inspection_count": len(inspections), "production_count": len(production),
             "document_count": len(documents),
             "with_inspections": sum(any(n["inspection_ids"] for n in group) for group in unique_keys),
             "with_documents": sum(any(n["document_ids"] for n in group) for group in unique_keys)}
    warnings += ["文件原名中的 306S0000073475 与生产统计订单 306S0000073396 不同，订单归属待确认。",
                 "BOM 包含重复展开、同编码父子及多个原料批次；保留原始路径，不代表单台用量。",
                 "证明文件仅有索引；未读取原文，不将文件名作为检测结论。",
                 "没有现场故障、真实工况、采购价或维护费，预测系数和费用均为可编辑演示假设。"]
    return {"product": {"id": root["code"] + ":" + root["batch"], "root_id": root["id"],
                        "name": root["name"], "model": "DRQF-15-0.1/KTLN-XF2D", "spec": root["spec"],
                        "code": root["code"], "batch": root["batch"], "supplier": "鑫豪斯",
                        "source_file": "鑫豪斯-阀批次306S0000073475.xlsx"},
            "stats": stats, "nodes": nodes, "inspections": inspections,
            "documents": list(documents.values()), "production": production, "warnings": warnings,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
