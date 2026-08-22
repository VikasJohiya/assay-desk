"""Gold Prediction & Calibration Engine — Phase 1 (US, China, India).

This package holds the scripted ingestion pipeline. Phase-1 scope covers the
price connector only (USD gold, USD/INR). Signal connectors (Fed/Treasury,
RBI/CBIC, PBoC/SGE) are added later, each in its own module under sources/.
"""

__all__ = ["errors", "prices", "sources"]
