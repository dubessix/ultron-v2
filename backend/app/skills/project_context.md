# Skill: Project-Aware Coding

Before and while writing code, be aware of the project you are working on.

## Use Stored Project Facts
Check for stored project state (name, tech stack, goal). If present, respect it
and write code consistent with that stack and architecture.
- project_name, tech_stack, project_goal, project_structure

## Read the Live Structure
Use the injected `[PROJECT_CONTEXT]` block (from the live structure scan) to
understand where files live and how modules are organised. Follow the existing
conventions rather than inventing new ones.

## Respect Conventions
- Match the project's existing naming, imports, and file layout.
- Don't scatter files; put new code in the right place relative to the structure.

## Don't Over-Scan
Do not re-read the whole project every step. Use the provided context block and
read specific files only when you need their exact contents.

## Remember the Goal
Keep the user's stated project goal in mind. A feature should serve the product,
not just be technically clever.
