"""
Brain loader — assembles the agent's system prompt from skill files.

Skills live in brain/skills/<name>.md. Each skill is a markdown document
describing a trading domain (stocks, options, etc.). The base skill is
always included; asset-class skills are included when their corresponding
config knob is enabled.

To add a new skill:
  1. Drop a .md file into brain/skills/
  2. Add an entry to SKILL_GATES mapping filename → config knob name
  3. Enable the knob via the dashboard settings
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent / "skills"

# Maps skill filename (without .md) → config knob that gates it.
# A skill is included when its knob is truthy. "base" is always loaded.
SKILL_GATES: dict[str, str] = {
    "stocks": "asset_stocks",
    "options": "asset_options",
    "crypto": "asset_crypto",
    "futures": "asset_futures",
}


def load_skill(name: str) -> str:
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        logger.warning("Brain skill file not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8").strip()


def active_skill_names(knobs: dict) -> list[str]:
    """Return ordered list of skill names to load given current knob values."""
    names = ["base"]
    for skill, knob in SKILL_GATES.items():
        if knobs.get(knob, False):
            names.append(skill)
    return names


def build_system_prompt(knobs: dict) -> str:
    """Assemble the full system prompt from base + all active skills."""
    parts: list[str] = []
    for name in active_skill_names(knobs):
        content = load_skill(name)
        if content:
            parts.append(content)
        else:
            logger.debug("Skipping empty or missing skill: %s", name)

    prompt = "\n\n---\n\n".join(parts)
    logger.debug(
        "Brain assembled: skills=%s, prompt_length=%d",
        active_skill_names(knobs), len(prompt),
    )
    return prompt
