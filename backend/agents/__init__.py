"""Sentinel Agent - 6-Agent AI Pipeline.

1. ThesisOrchestrator    - Parses PM theses, maps tickers to GeoTargets
2. SensorOrchestrator    - Weather-immune sensor routing (optical->SAR fallback)
3. ConsensusVisionAgent  - Multi-model CV consensus for zero hallucination
4. QuantRegressionAgent  - Historical backtest for financial materiality
5. OmnichannelRAGAgent   - SEC 10-K RAG for digital revenue correction
6. ComplianceCoPilot     - Cryptographic provenance and SEC audit PDF
"""
from .orchestrator import ThesisOrchestrator
from .sensor_orchestrator import SensorOrchestrator
from .consensus_vision import ConsensusVisionAgent
from .quant_regression import QuantRegressionAgent
from .omnichannel_rag import OmnichannelRAGAgent
from .compliance_copilot import ComplianceCoPilot

__all__ = [
    "ThesisOrchestrator",
    "SensorOrchestrator",
    "ConsensusVisionAgent",
    "QuantRegressionAgent",
    "OmnichannelRAGAgent",
    "ComplianceCoPilot",
]
