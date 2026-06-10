from __future__ import annotations

from ly_next.agent.skills_loader import (
    discover_skills,
    read_skill_content,
    skills_enabled,
)
from ly_next.tools.base import ToolResult, tool


@tool(
    name="list_skills",
    description=(
        "List agent skills (SKILL.md playbooks for how to execute tasks). "
        "Not for project docs in the knowledge base (knowledge_search)."
    ),
    category="safe",
    parameters={"type": "object", "properties": {}},
)
async def list_skills() -> ToolResult:
    if not skills_enabled():
        return ToolResult(success=True, result={"skills": [], "enabled": False})
    items = discover_skills()
    return ToolResult(
        success=True,
        result={
            "enabled": True,
            "count": len(items),
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "path": s.rel_path,
                }
                for s in items
            ],
        },
    )


@tool(
    name="read_skill",
    description=(
        "Read SKILL.md for a skill id from list_skills and follow its workflow. "
        "Not for searching documents_path corpus (knowledge_search)."
    ),
    category="safe",
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "Skill id from list_skills (e.g. deploy-model or foo/bar)",
            }
        },
        "required": ["skill_id"],
    },
)
async def read_skill(skill_id: str) -> ToolResult:
    if not skills_enabled():
        return ToolResult(success=False, error="agent.skills.enabled is false")
    text, err = read_skill_content(skill_id)
    if err:
        return ToolResult(success=False, error=err)
    return ToolResult(
        success=True,
        result={"skill_id": skill_id, "content": text},
    )
