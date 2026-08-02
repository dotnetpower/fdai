"""Trust-rechecked packaged skill assets for code assurance."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

from fdai.core.skills import parse_skill_bundle_manifest, parse_skill_markdown

from .provider import CODE_REVIEW_TOOL_ID, SECURITY_REVIEW_TOOL_ID


@dataclass(frozen=True, slots=True)
class CodeAssuranceAssets:
    skills: tuple[bytes, ...]
    skill_bundle: bytes


def load_code_assurance_assets() -> CodeAssuranceAssets:
    """Load exact package bytes and reject member or tool drift."""

    root = files("fdai_code_assurance").joinpath("assets")
    skills = (
        root.joinpath("skills", "code-review", "SKILL.md").read_bytes(),
        root.joinpath("skills", "security-review", "SKILL.md").read_bytes(),
    )
    parsed_skills = tuple(parse_skill_markdown(raw) for raw in skills)
    bundle_raw = root.joinpath("skill-bundle.json").read_bytes()
    bundle = parse_skill_bundle_manifest(bundle_raw)
    member_names = tuple(member.name for member in bundle.manifest.members)
    skill_names = tuple(skill.manifest.name for skill in parsed_skills)
    if member_names != skill_names:
        raise ValueError("code-assurance skill bundle members do not match packaged skills")
    required_tools = set(bundle.manifest.required_tools)
    expected_tools = {CODE_REVIEW_TOOL_ID, SECURITY_REVIEW_TOOL_ID}
    if required_tools != expected_tools:
        raise ValueError("code-assurance skill bundle tools do not match package tools")
    return CodeAssuranceAssets(skills=skills, skill_bundle=bundle_raw)


__all__ = ["CodeAssuranceAssets", "load_code_assurance_assets"]
