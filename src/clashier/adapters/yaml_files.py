"""UTF-8 YAML documents and same-directory atomic file replacement."""

import stat
import tempfile
from pathlib import Path
from typing import Any, Dict

import yaml

from clashier.errors import OperationError


def read_mapping(path: Path) -> Dict[str, Any]:
    """Read a mapping; a missing or empty document represents no configuration."""
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    document = yaml.safe_load(contents)
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise OperationError("CONFIGURATION_ERROR", "Expected a YAML mapping in {}".format(path.name))
    return document


def write_text(path: Path, contents: str) -> None:
    """Replace one file atomically, preserving existing permissions and UTF-8 data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        permissions = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        permissions = None
    stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=str(path.parent), prefix=".clashier-", delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(contents)
        if permissions is not None:
            temporary.chmod(permissions)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_mapping(path: Path, values: Dict[str, Any]) -> None:
    """Serialize a document before opening its replacement file."""
    rendered = yaml.safe_dump(values, allow_unicode=True, sort_keys=False, width=65536)
    write_text(path, rendered)
