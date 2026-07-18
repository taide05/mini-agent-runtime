from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    max_iterations: int = 10
    system_prompt: str = (
        "You are a helpful AI assistant with access to tools. "
        "Use tools when you need to look up information or perform calculations. "
        "After using tools, synthesize the results into a clear answer. "
        "If a tool returns an error, try a different approach or explain the issue to the user."
    )
    model: str = "deepseek-chat"
    metadata: dict = field(default_factory=dict)
