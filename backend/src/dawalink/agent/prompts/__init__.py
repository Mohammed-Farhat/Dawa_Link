"""The prompts, kept as versioned files (docs/07 §5, AG-D12).

The version is stored on every `agent_runs` row and in every trace. Changing a prompt
means a new version, and an evaluation run that compares it with the previous one.
"""

from functools import cache
from importlib import resources

from dawalink.domain.vocabulary import AgentMode

# Change it with any edit to the files of `v1/`.
PROMPT_VERSION = "v1.3"
_FOLDER = "v1"


@cache
def _read(name: str) -> str:
    return resources.files(__package__).joinpath(_FOLDER, name).read_text(encoding="utf-8").strip()


def system_parts(mode: AgentMode) -> tuple[str, ...]:
    """The fixed parts of the prompt, in the order they are sent.

    They never change within a version, and they come before everything that does, so a
    provider that caches prompts can reuse them (cheaper and faster).
    """
    mode_file = "mode_sourcing.md" if mode is AgentMode.SOURCING else "mode_assistant.md"
    return (_read("system_core.md"), _read(mode_file), _read("examples.md"))
