"""大模型扩展点：未来实现相同协议；首版只返回可核查的本地说明。"""
from typing import Protocol


class AnalysisProvider(Protocol):
    def explain(self, catalog: dict, simulation: dict) -> dict:
        """未来接入时仅传必要的结构化事实，返回带证据 ID 的解释。"""
        ...


class LocalRuleAnalysis:
    def explain(self, catalog, simulation):
        return {"provider": "local-rules", "llm_enabled": False,
                "summary": "已关联真实 BOM 与检验记录；衰减率、健康阈值与费用未经过现场数据标定。",
                "items": [{"system_id": g["id"], "text": g["mechanism"],
                           "inspection_ids": g["inspection_ids"], "document_ids": g["document_ids"],
                           "formula": "H(t)=100×exp(-基础衰减率×环境载荷系数×t)",
                           "coefficient_source": "演示假设", "document_content_loaded": False}
                          for g in simulation["systems"]]}
