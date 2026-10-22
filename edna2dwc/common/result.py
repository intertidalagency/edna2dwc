from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from edna2dwc.common.findings import FindingsLog
from edna2dwc.conversion import stages

OK = "ok"
ERROR = "error"


@dataclass(frozen=True)
class CommandResult:
    command: str
    status: str = OK
    findings: list[dict] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    next_step: str | None = None
    stage: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    json_body: Any = None
    as_json: bool = False
    exit_code: int = 0

    @classmethod
    def of(
        cls,
        command: str,
        log: FindingsLog,
        *,
        outputs: dict[str, Any] | None = None,
        next_step: str | None = None,
        extra: dict[str, Any] | None = None,
        text: str = "",
        as_json: bool = False,
        exits_on_error: bool = False,
    ) -> CommandResult:
        failed = log.has_errors()
        return cls(
            command=command,
            status=ERROR if failed else OK,
            findings=log.to_list(),
            outputs=outputs or {},
            next_step=next_step,
            extra=extra or {},
            text=text,
            as_json=as_json,
            exit_code=1 if failed and exits_on_error else 0,
        )

    @property
    def conversion_stage(self) -> str | None:
        return self.stage or stages.COMMAND_STAGES.get(self.command)

    def to_json_object(self) -> Any:
        placed = (
            {"stage": stages.position(self.conversion_stage), "next": self.next_step}
            if self.conversion_stage and self.next_step
            else {}
        )
        if isinstance(self.json_body, dict):
            return {**self.json_body, **placed}
        if self.json_body is not None:
            return self.json_body
        return {
            "command": self.command,
            "status": self.status,
            "decision": None,
            "findings": self.findings,
            "outputs": self.outputs,
            "next": self.next_step,
            **placed,
            **self.extra,
        }

    def render(self) -> str:
        if self.as_json:
            return json.dumps(self.to_json_object(), indent=2)
        if self.conversion_stage and self.next_step:
            return lines(self.text, stages.stage_line(self.conversion_stage, self.next_step))
        return self.text


def lines(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def render_findings(log: FindingsLog) -> str:
    return "\n".join(f"{f.severity.upper()}: {f.code}: {f.message}" for f in log.findings)
