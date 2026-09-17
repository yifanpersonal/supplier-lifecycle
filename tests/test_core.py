"""真实样本解析、模型确定性、事件账本和 API 边界测试。"""
import json
import math
import threading
import unittest
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.server import make_handler
from backend.simulation import DEFAULTS, simulate, validate
from backend.workbook import load_catalog, read_sheets

DATA = Path(__file__).resolve().parents[1] / "data/xinhaosi.xlsx"


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(DATA)

    def test_source_counts(self):
        self.assertEqual(self.catalog["stats"]["bom_rows"], 1624)
        self.assertEqual(self.catalog["stats"]["inspection_count"], 598)
        self.assertEqual(self.catalog["stats"]["unique_codes"], 93)
        self.assertEqual(self.catalog["stats"]["unique_batch_items"], 187)
        self.assertEqual(self.catalog["stats"]["document_count"], 184)

    def test_empty_shared_string_is_not_index_16(self):
        rows = read_sheets(DATA)["材料构成"]["rows"]
        self.assertEqual(rows[1][1][5], "")
        self.assertEqual(rows[1][1][4], "26070113120001")

    def test_tree_preserves_source_and_depth(self):
        nodes = {n["id"]: n for n in self.catalog["nodes"]}
        self.assertEqual(len(nodes), 1624)
        for node in nodes.values():
            if node["parent_id"]:
                self.assertLess(nodes[node["parent_id"]]["source_row"], node["source_row"])
                self.assertEqual(nodes[node["parent_id"]]["level"], node["level"] - 1)

    def test_evidence_join_is_composite_key(self):
        inspections = {q["id"]: q for q in self.catalog["inspections"]}
        for n in self.catalog["nodes"]:
            for qid in n["inspection_ids"]:
                q = inspections[qid]
                self.assertEqual((n["code"], n["batch"]), (q["code"], q["batch"]))
        root = self.catalog["nodes"][0]
        self.assertEqual(len(root["inspection_ids"]), 18)

    def test_no_signed_tokens_in_api_payload(self):
        encoded = json.dumps(self.catalog)
        self.assertNotIn("token=", encoded)
        self.assertTrue(all(not d["content_loaded"] for d in self.catalog["documents"]))

    def test_deterministic_monthly_series(self):
        a = simulate(self.catalog, {})
        self.assertEqual(a, simulate(self.catalog, {}))
        self.assertEqual(len(a["baseline"]), 241)
        for i, row in enumerate(a["baseline"]):
            self.assertGreaterEqual(row["health"], 0)
            self.assertLessEqual(row["health"], 100)
            self.assertEqual(row["health"], min(row["systems"].values()))
            if i:
                self.assertLessEqual(row["health"], a["baseline"][i-1]["health"])

    def test_environment_changes_output(self):
        cool = simulate(self.catalog, {"temperature": 15, "humidity": 60})
        humid = simulate(self.catalog, {"temperature": 25, "humidity": 80, "exposure": "coastal"})
        self.assertLess(humid["baseline"][-1]["health"], cool["baseline"][-1]["health"])

    def test_threshold_crossing_math(self):
        r = simulate(self.catalog, {})
        for g in r["systems"]:
            at = -math.log(r["settings"]["warning"] / 100) / g["effective_rate"]
            self.assertAlmostEqual(at, g["warning_year"], places=2)

    def test_maintenance_resets_only_target_system_and_charges(self):
        r = simulate(self.catalog, {})
        for p in r["policies"]:
            for event in p["events"]:
                self.assertEqual(p["series"][event["month"]]["systems"][event["system_id"]], 100)
                self.assertAlmostEqual(event["cost"], sum(event["breakdown"].values()), places=2)
            self.assertAlmostEqual(p["total"], sum(p["breakdown"].values()), places=2)
            self.assertEqual(p["series"][-1]["cost"], p["total"])
            event_cost = sum(event["cost"] for event in p["events"])
            fixed = p["breakdown"]["purchase"] + p["breakdown"]["installation"] + p["breakdown"]["inspection"]
            self.assertAlmostEqual(event_cost + fixed, p["total"], places=2)
            self.assertTrue(all(b["cost"] >= a["cost"] for a, b in zip(p["series"], p["series"][1:])))

    def test_cost_scales_by_devices_not_bom_rows(self):
        one = simulate(self.catalog, {"quantity": 1})
        many = simulate(self.catalog, {"quantity": 10})
        for a, b in zip(one["policies"], many["policies"]):
            self.assertAlmostEqual(a["total"] * 10, b["total"])
            self.assertEqual(len(a["events"]), len(b["events"]))

    def test_zero_cost_is_valid_and_zero_rate_has_no_events(self):
        payload = {k: 0 for k in ("purchase", "installation", "inspection", "labor", "downtime")}
        payload["rates"] = {k: 0 for k in DEFAULTS["rates"]}
        payload["replacements"] = {k: 0 for k in DEFAULTS["rates"]}
        result = simulate(self.catalog, payload)
        self.assertEqual(result["baseline"][-1]["health"], 100)
        self.assertTrue(all(p["total"] == 0 and p["events"] == [] for p in result["policies"]))
        self.assertTrue(all(g["failure_year"] is None for g in result["systems"]))

    def test_validation(self):
        for payload in [{"years": 0}, {"years": 1.5}, {"quantity": 0}, {"humidity": 101},
                        {"warning": 40, "failure": 50}, {"purchase": -1}, {"cycles": float("nan")},
                        {"years": True}, {"rates": {}}, {"location": ""}, {"exposure": "unknown"}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate(payload)

    def test_defaults_unchanged(self):
        original = deepcopy(DEFAULTS)
        simulate(self.catalog, {"years": 10, "quantity": 6})
        self.assertEqual(original, DEFAULTS)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(load_catalog(DATA)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_pages_and_catalog(self):
        for path in ("/", "/styles.css", "/js/app.js", "/api/health", "/api/config", "/api/catalog"):
            with urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)
                self.assertGreater(len(response.read()), 0)

    def test_post_simulation_and_explain(self):
        for path in ("/api/simulate", "/api/analysis/explain"):
            req = Request(self.url + path, data=b"{}", headers={"Content-Type": "application/json"})
            with urlopen(req) as response:
                data = json.load(response)
                self.assertFalse(data["llm_enabled"])

    def test_bad_json_and_unknown_product(self):
        for body in (b"[1]", b"not-json", b'{"product_id":"fake"}'):
            with self.assertRaises(HTTPError) as ctx:
                urlopen(Request(self.url + "/api/simulate", data=body))
            self.assertEqual(ctx.exception.code, 400)

    def test_upload_requires_nonempty_request(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(Request(self.url + "/api/supplier-data/import", data=b""))
        self.assertEqual(ctx.exception.code, 413)

    def test_static_traversal_blocked(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.url + "/%2e%2e/backend/server.py")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
