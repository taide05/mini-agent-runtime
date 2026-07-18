from fastapi import APIRouter, HTTPException

from app.core.tool_registry import ToolDefinition
from app.schemas import ToolDefinitionSchema, ToolListResponse, ToolRegisterRequest
from app.services.tool_service import get_tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
async def api_list_tools():
    registry = await get_tool_registry()
    tools = await registry.list_all()
    return ToolListResponse(
        tools=[
            ToolDefinitionSchema(name=t.name, description=t.description, parameters=t.parameters)
            for t in tools
        ]
    )


@router.post("", response_model=ToolDefinitionSchema, status_code=201)
async def api_register_tool(body: ToolRegisterRequest):
    registry = await get_tool_registry()
    existing = await registry.get(body.name)
    if existing:
        raise HTTPException(409, f"Tool '{body.name}' already exists")

    async def _runtime_fn(**kwargs):
        return {"note": "Runtime tool executed", "args": kwargs}

    tool_def = ToolDefinition(
        name=body.name,
        description=body.description,
        parameters=body.parameters,
        fn=_runtime_fn,
        source="runtime",
    )
    await registry.register(tool_def)
    return ToolDefinitionSchema(name=tool_def.name, description=tool_def.description, parameters=tool_def.parameters)


@router.delete("/{tool_name}", status_code=204)
async def api_unregister_tool(tool_name: str):
    registry = await get_tool_registry()
    ok = await registry.unregister(tool_name)
    if not ok:
        raise HTTPException(404, f"Tool '{tool_name}' not found")
