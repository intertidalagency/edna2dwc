from __future__ import annotations

from dataclasses import dataclass, field



@dataclass
class SynthesizeIdsResult:
    findings: FindingsLog = field(default_factory=FindingsLog)


