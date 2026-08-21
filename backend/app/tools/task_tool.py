"""
Ultron Task & Project Management Tool
Provides a production-grade, un-mocked developer tool to manage projects (like TrustQuiz),
modules (e.g., Authentication, Quiz Engine), subtasks, and priority tracking in SQLite (Level 1 Security).
"""

import uuid
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool
from backend.app.database.db import get_db_connection

class TaskArgs(BaseModel):
    action: str = Field(..., description="Action to perform: create, update_status, update_priority, list, delete.")
    task_id: Optional[str] = Field(None, description="Target task UUID (required for status/priority updates or deletion).")
    project_name: Optional[str] = Field("General", description="The project context (e.g. 'TrustQuiz').")
    module_name: Optional[str] = Field("Root", description="The specific project module (e.g. 'Authentication', 'Dashboard').")
    title: Optional[str] = Field(None, description="The summary title of the task.")
    description: Optional[str] = Field(None, description="Optional extra task details.")
    priority: Optional[str] = Field("medium", description="Priority level: high, medium, low.")
    status: Optional[str] = Field("todo", description="Task state: todo, in_progress, done.")
    due_date: Optional[str] = Field(None, description="Target due date (ISO format, e.g., 'YYYY-MM-DD').")
    parent_task_id: Optional[str] = Field(None, description="Parent task UUID for hierarchical subtask mapping.")

class TaskTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="manage_task",
            name="Task & Project Manager",
            description="Manages project tasks, hierarchy trees, priorities, subtasks, and statuses in the database.",
            category="productivity",
            tags=["task", "todo", "project", "track", "backlog", "sprint"],
            permission_level=1,  # Level 1: Write (no manual confirmation required)
            args_model=TaskArgs,
            usage_examples=[
                "manage_task(action='create', project_name='TrustQuiz', module_name='Authentication', title='OAuth Setup', priority='high')",
                "manage_task(action='list', project_name='TrustQuiz')",
                "manage_task(action='update_status', task_id='some-id', status='done')"
            ]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "list").lower()
        task_id = kwargs.get("task_id")
        project_name = kwargs.get("project_name", "General")
        module_name = kwargs.get("module_name", "Root")
        title = kwargs.get("title")
        description = kwargs.get("description")
        priority = kwargs.get("priority", "medium").lower()
        status_val = kwargs.get("status", "todo").lower()
        due_date = kwargs.get("due_date")
        parent_task_id = kwargs.get("parent_task_id")

        if priority not in ("high", "medium", "low"):
            return {"success": False, "error": f"Unsupported priority '{priority}'.", "data": {}}
        if status_val not in ("todo", "in_progress", "done"):
            return {"success": False, "error": f"Unsupported task status '{status_val}'.", "data": {}}

        with get_db_connection() as conn:
            cursor = conn.cursor()

            if action == "create":
                if not title:
                    return {"success": False, "error": "Parameter 'title' is required for task creation.", "data": {}}
                
                new_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO project_tasks (
                        id, project_name, module_name, title, description, priority, due_date, status, parent_task_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (new_id, project_name, module_name, title, description, priority, due_date, status_val, parent_task_id)
                )
                conn.commit()
                return {
                    "success": True,
                    "data": {
                        "message": f"Task '{title}' successfully created inside {project_name}/{module_name}.",
                        "task_id": new_id,
                        "project": project_name,
                        "module": module_name,
                        "priority": priority,
                        "status": status_val
                    },
                    "error": None
                }

            elif action == "list":
                # Returns filtered task lists
                query = "SELECT * FROM project_tasks WHERE 1=1"
                params = []
                if project_name and project_name != "General":
                    query += " AND project_name = ?"
                    params.append(project_name)
                if module_name and module_name != "Root":
                    query += " AND module_name = ?"
                    params.append(module_name)
                
                query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC"
                
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                results = [dict(row) for row in rows]
                
                return {
                    "success": True,
                    "data": {
                        "tasks": results,
                        "count": len(results),
                        "project_name": project_name,
                        "module_name": module_name
                    },
                    "error": None
                }

            elif action == "update_status":
                if not task_id:
                    return {"success": False, "error": "Parameter 'task_id' is required for update_status action.", "data": {}}
                
                cursor.execute("UPDATE project_tasks SET status = ? WHERE id = ?;", (status_val, task_id))
                updated = cursor.rowcount > 0
                conn.commit()
                
                if not updated:
                    return {"success": False, "error": f"Task '{task_id}' not found.", "data": {}}
                
                return {
                    "success": True,
                    "data": {"message": f"Task status updated to '{status_val}'.", "task_id": task_id, "status": status_val},
                    "error": None
                }

            elif action == "update_priority":
                if not task_id:
                    return {"success": False, "error": "Parameter 'task_id' is required for update_priority action.", "data": {}}
                
                cursor.execute("UPDATE project_tasks SET priority = ? WHERE id = ?;", (priority, task_id))
                updated = cursor.rowcount > 0
                conn.commit()
                
                if not updated:
                    return {"success": False, "error": f"Task '{task_id}' not found.", "data": {}}
                
                return {
                    "success": True,
                    "data": {"message": f"Task priority updated to '{priority}'.", "task_id": task_id, "priority": priority},
                    "error": None
                }

            elif action == "delete":
                if not task_id:
                    return {"success": False, "error": "Parameter 'task_id' is required for delete action.", "data": {}}
                
                cursor.execute("DELETE FROM project_tasks WHERE id = ?;", (task_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
                
                if not deleted:
                    return {"success": False, "error": f"Task '{task_id}' not found.", "data": {}}
                
                return {
                    "success": True,
                    "data": {"message": f"Task '{task_id}' successfully deleted.", "task_id": task_id},
                    "error": None
                }

            else:
                return {"success": False, "error": f"Unsupported action '{action}'.", "data": {}}
