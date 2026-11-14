"""The model behind one small interface (docs/07 §10).

`ChatModel.complete(prompt)` is all the agent knows about a model. Three things implement
it: a scripted model for the tests, the local model for development, and Claude for the
evaluation and the demo. Which one runs is a setting, never a code change.
"""

from dawalink.agent.llm.base import (
    AssistantTurn,
    ChatModel,
    LLMError,
    LLMRefused,
    LLMRejected,
    LLMUnavailable,
    Message,
    ModelReply,
    Prompt,
    ToolCall,
    ToolResult,
    ToolResults,
    ToolSpec,
    Usage,
    UserText,
)

__all__ = [
    "AssistantTurn",
    "ChatModel",
    "LLMError",
    "LLMRefused",
    "LLMRejected",
    "LLMUnavailable",
    "Message",
    "ModelReply",
    "Prompt",
    "ToolCall",
    "ToolResult",
    "ToolResults",
    "ToolSpec",
    "Usage",
    "UserText",
]
