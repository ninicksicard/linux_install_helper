# models.py

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PackageNode:
    name: str
    installer: str
    installed: bool
    installed_version: str
    command_line: str
    versions: list[str]
    selected_version: str
    dependencies: list["PackageNode"] = field(default_factory=list)
    is_dependency: bool = False
    last_action: str = "install"
    dependencies_loaded: bool = False
