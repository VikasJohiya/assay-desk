"""Explicit failure types.

Guardrail (Section 6.2): the pipeline must FAIL VISIBLY. A source that is down,
returns an error page, or returns an unparseable/empty payload must raise here —
never be swallowed and replaced with stale, cached, or template data. A visibly
broken run is safe; a silently degraded one that still looks confident is the
dangerous failure mode.
"""


class PipelineError(Exception):
    """Base class for every pipeline failure. Callers surface, never hide it."""


class SourceUnavailableError(PipelineError):
    """A source did not return usable data (HTTP error, timeout, HTML challenge,
    empty body, or a payload that did not match the expected shape)."""

    def __init__(self, source: str, detail: str):
        self.source = source
        self.detail = detail
        super().__init__(f"[{source}] source unavailable: {detail}")


class NoObservationError(PipelineError):
    """The source responded correctly but held no observation for the requested
    date/range. Distinct from SourceUnavailableError: the feed works, the datum
    simply is not there (e.g. a market holiday, or data not yet published)."""

    def __init__(self, source: str, detail: str):
        self.source = source
        self.detail = detail
        super().__init__(f"[{source}] no observation: {detail}")
