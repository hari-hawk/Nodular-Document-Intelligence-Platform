"""Pack loader — optional vertical specialization layer.

A pack is a directory under `src/mdi/packs/<slug>/` containing a `skills.yaml`
manifest plus prompts, validators, and enrichment dictionaries. Open-vocabulary
mode is the default: a tenant uses a pack only when they have contractual
schema guarantees per vertical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mdi.kernel.observability import get_logger
from mdi.kernel.settings import get_settings

logger = get_logger(__name__)


class PackError(RuntimeError):
    """Pack manifest is missing, malformed, or fails the contract."""


@dataclass
class Pack:
    slug: str
    version: str
    root: Path
    manifest: dict[str, Any] = field(default_factory=dict)

    def prompt(self, doc_type: str) -> str:
        rel = self.manifest.get("extract_prompts", {}).get(doc_type)
        if not rel:
            return ""
        return (self.root / rel).read_text(encoding="utf-8")

    def validators(self) -> list[dict[str, Any]]:
        rel = self.manifest.get("validators")
        if not rel:
            return []
        path = self.root / rel
        if not path.exists():
            return []
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if isinstance(loaded, dict):
            return loaded.get("rules", [])
        return list(loaded)

    def field_schema(self) -> dict[str, Any]:
        rel = self.manifest.get("field_schema")
        if not rel:
            return {}
        return yaml.safe_load((self.root / rel).read_text(encoding="utf-8")) or {}


# Manifest contract — Ishtiuk's 13 mandatory skill slots, lightly relaxed
# so open-vocabulary packs can ship with only the keys they need.
REQUIRED_KEYS: set[str] = {
    "classifier",
    "field_schema",
    "doc_type_taxonomy",
    "extract_prompts",
    "merge_rules",
    "validators",
    "enrichment",
    "compliance",
    "golden_seed",
}


def _validate_manifest(manifest: dict[str, Any], slug: str) -> None:
    missing = REQUIRED_KEYS - set(manifest.keys())
    if missing:
        # Soft warn rather than reject — open-vocabulary default doesn't need all 13.
        logger.warning(
            "pack.manifest.missing_keys",
            pack=slug,
            missing=sorted(missing),
        )


def load_pack(slug: str, packs_dir: Path | None = None) -> Pack:
    base = packs_dir or get_settings().packs_dir
    root = base / slug
    skills = root / "skills.yaml"
    if not skills.exists():
        raise PackError(f"pack {slug!r} has no skills.yaml at {skills}")

    manifest = yaml.safe_load(skills.read_text(encoding="utf-8")) or {}
    if not isinstance(manifest, dict):
        raise PackError(f"pack {slug!r} skills.yaml must be a mapping")

    _validate_manifest(manifest, slug)
    pack = Pack(
        slug=slug,
        version=str(manifest.get("version", "1.0.0")),
        root=root,
        manifest=manifest,
    )
    logger.info("pack.loaded", slug=slug, version=pack.version)
    return pack


def list_packs(packs_dir: Path | None = None) -> list[str]:
    base = packs_dir or get_settings().packs_dir
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "skills.yaml").exists())
