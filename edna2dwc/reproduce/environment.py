from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
import platform

import pyproj

from edna2dwc.common.version import installed_commit, installed_version
from edna2dwc.conversion import artifacts

UNKNOWN_VERSION = "unknown"
READER_PACKAGES = (
    "openpyxl",
    "pyproj",
    "timezonefinder",
    "h5py",
    "pypdf",
    "pandas",
)


@dataclass(frozen=True)
class EnvironmentRecord:
    edna2dwc_version: str
    python: str
    pyproj_version: str
    proj_data_version: str
    dependencies: dict[str, str] = field(default_factory=dict)
    edna2dwc_commit: str = ""

    def to_dict(self) -> dict:
        return {
            "edna2dwc_version": self.edna2dwc_version,
            "edna2dwc_commit": self.edna2dwc_commit,
            "python": self.python,
            "pyproj": {"version": self.pyproj_version, "proj_data": self.proj_data_version},
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> EnvironmentRecord:
        pyproj_block = raw.get("pyproj") or {}
        return cls(
            edna2dwc_version=raw["edna2dwc_version"],
            edna2dwc_commit=raw.get("edna2dwc_commit", ""),
            python=raw["python"],
            pyproj_version=pyproj_block.get("version", ""),
            proj_data_version=pyproj_block.get("proj_data", ""),
            dependencies=dict(raw.get("dependencies", {})),
        )

    def all_pins(self) -> dict[str, str]:
        return {"edna2dwc": self.edna2dwc_version, **self.dependencies}

    def reconstructable_pins(self) -> dict[str, str]:
        return dict(self.dependencies)


def capture_current_environment() -> EnvironmentRecord:
    edna2dwc_version = installed_version()
    dependencies = {}
    for name in READER_PACKAGES:
        try:
            dependencies[name] = _pkg_version(name)
        except PackageNotFoundError:
            dependencies[name] = UNKNOWN_VERSION
    return EnvironmentRecord(
        edna2dwc_version=edna2dwc_version,
        edna2dwc_commit=installed_commit(),
        python=platform.python_version(),
        pyproj_version=pyproj.__version__,
        proj_data_version=pyproj.proj_version_str,
        dependencies=dependencies,
    )


def record_environment(config_path: Path, record: EnvironmentRecord) -> None:
    raw = artifacts.read_recipe(config_path)
    raw["environment"] = record.to_dict()
    artifacts.write_recipe(config_path, raw)


def version_diff_table(recorded: EnvironmentRecord, current: EnvironmentRecord) -> list[dict]:
    current_pins = current.all_pins()
    rows = []
    for package, recorded_version in recorded.all_pins().items():
        current_version = current_pins.get(package, "not installed")
        rows.append(
            {
                "package": package,
                "recorded": recorded_version,
                "current": current_version,
                "changed": recorded_version != current_version,
            }
        )
    rows.append(
        {
            "package": "edna2dwc commit",
            "recorded": recorded.edna2dwc_commit or "not recorded",
            "current": current.edna2dwc_commit or "unknown",
            "changed": recorded.edna2dwc_commit != current.edna2dwc_commit,
        }
    )
    return rows


def load_environment(config_path: Path) -> EnvironmentRecord | None:
    raw = artifacts.read_recipe(config_path)
    if "environment" not in raw:
        return None
    return EnvironmentRecord.from_dict(raw["environment"])
