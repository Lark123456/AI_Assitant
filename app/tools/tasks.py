"""work_item 工具：create_task / list_tasks / complete_task / update_task。阶段 1 只用 type=item。"""

import uuid

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkItem
from app.tools.base import ToolContext, ToolDef, ToolResult, require_source_event_id


class CreateTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None


class ListTasksArgs(BaseModel):
    include_done: bool = False


class CompleteTaskArgs(BaseModel):
    task_id: str = Field(min_length=1)


class UpdateTaskArgs(BaseModel):
    task_id: str = Field(min_length=1, description="要修改的任务 id")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _check_fields(self) -> "UpdateTaskArgs":
        if self.title is None and self.description is None:
            raise ValueError("title 与 description 至少提供一个")
        return self


async def _run_create_task(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = CreateTaskArgs.model_validate(args)
    session: AsyncSession = ctx.session
    item = WorkItem(
        user_id=ctx.user.id,
        type="item",
        status="active",
        title=parsed.title,
        description=parsed.description,
        source_event_id=require_source_event_id(ctx),
        created_at=ctx.clock.now(),
        updated_at=ctx.clock.now(),
    )
    session.add(item)
    await session.flush()
    return ToolResult(
        status="ok",
        data={"task_id": str(item.id), "title": item.title, "status": item.status},
        message="任务已创建",
    )


async def _run_list_tasks(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = ListTasksArgs.model_validate(args)
    statuses = ["active", "done"] if parsed.include_done else ["active"]
    rows = (
        (
            await ctx.session.execute(
                select(WorkItem).where(
                    WorkItem.user_id == ctx.user.id,
                    WorkItem.type == "item",
                    WorkItem.status.in_(statuses),
                )
            )
        )
        .scalars()
        .all()
    )
    tasks = [
        {"task_id": str(r.id), "title": r.title, "status": r.status, "description": r.description}
        for r in rows
    ]
    return ToolResult(status="ok", data={"tasks": tasks}, message=f"共 {len(tasks)} 条")


async def _run_complete_task(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = CompleteTaskArgs.model_validate(args)
    session: AsyncSession = ctx.session
    try:
        task_id = uuid.UUID(parsed.task_id)
    except ValueError:
        return ToolResult(status="error", message="task_id 不是合法 UUID")
    item = (
        await session.execute(
            select(WorkItem).where(WorkItem.id == task_id, WorkItem.user_id == ctx.user.id)
        )
    ).scalar_one_or_none()
    if item is None:
        return ToolResult(status="error", message=f"任务不存在：{parsed.task_id}")
    if item.status == "done":  # 幂等：重复完成同一任务
        return ToolResult(status="ok", data={"task_id": str(item.id), "status": "done"}, message="任务已完成")
    item.status = "done"
    item.rev += 1
    item.updated_at = ctx.clock.now()
    await session.flush()
    return ToolResult(
        status="ok", data={"task_id": str(item.id), "status": "done"}, message="任务已标记完成"
    )


async def _run_update_task(ctx: ToolContext, args: dict) -> ToolResult:
    """只修改标题/描述，不改状态，也不新建任务。"""
    parsed = UpdateTaskArgs.model_validate(args)
    try:
        task_id = uuid.UUID(parsed.task_id)
    except ValueError:
        return ToolResult(status="error", message="task_id 不是合法 UUID")
    item = (
        await ctx.session.execute(
            select(WorkItem).where(
                WorkItem.id == task_id,
                WorkItem.user_id == ctx.user.id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        return ToolResult(status="error", message=f"任务不存在：{parsed.task_id}")
    if parsed.title is not None:
        item.title = parsed.title
    if parsed.description is not None:
        item.description = parsed.description
    item.rev += 1
    item.updated_at = ctx.clock.now()
    await ctx.session.flush()
    return ToolResult(
        status="ok",
        data={
            "task_id": str(item.id),
            "title": item.title,
            "description": item.description,
            "status": item.status,
        },
        message="任务已更新",
    )


CREATE_TASK = ToolDef(
    name="create_task",
    description="创建一个任务。写操作，幂等键由系统按入站事件派生。",
    args_model=CreateTaskArgs,
    run=_run_create_task,
    write=True,
)

LIST_TASKS = ToolDef(
    name="list_tasks",
    description="列出当前用户的任务，默认只列未完成的。",
    args_model=ListTasksArgs,
    run=_run_list_tasks,
)

COMPLETE_TASK = ToolDef(
    name="complete_task",
    description="把指定任务标记为完成。写操作，幂等键由系统按入站事件派生。",
    args_model=CompleteTaskArgs,
    run=_run_complete_task,
    write=True,
)

UPDATE_TASK = ToolDef(
    name="update_task",
    description="修改任务的标题或描述（不改变状态，也不新建任务）。写操作，幂等键由系统按入站事件派生。",
    args_model=UpdateTaskArgs,
    run=_run_update_task,
    write=True,
)
