from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

MANIFEST_FIELDS = (
    "title",
    "abstract",
    "license",
    "creators",
    "geographic_description",
    "pub_date",
    "bounding_box",
)


@dataclass
class Manifest:
    values: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)

        self.provenance[field_name] = provenance

    def ask_list(self) -> list[str]:


    "title": ".//{*}title",
    "abstract": ".//{*}abstract/{*}para",
    "geographic_description": ".//{*}geographicDescription",
    "pub_date": ".//{*}pubDate",
}




@dataclass
class InitScanResult:
    manifest: Manifest


def init_scan(scan_dir: Path) -> InitScanResult:
    eml_paths = sorted(scan_dir.glob("**/eml.xml"))
