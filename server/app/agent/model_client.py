import json
from collections import deque
from typing import Protocol

from openai import AsyncOpenAI

from app.agent.models import AgentHistoryItem, IntentBrief, ModelTurn, ToolResult
from app.agent.models import ToolCall as IntentFlowToolCall
from app.agent.tools import ToolRegistry


class ModelClient(Protocol):
    async def next_turn(
        self,
        intent: IntentBrief,
        history: list[AgentHistoryItem],
    ) -> ModelTurn: ...


class FakeModelClient:
    """Returns scripted turns so the Agent loop can be tested without an API key."""

    def __init__(self, turns: list[ModelTurn]) -> None:
        self._turns = deque(turns)
        self.received_histories: list[list[AgentHistoryItem]] = []

    async def next_turn(
        self,
        intent: IntentBrief,
        history: list[AgentHistoryItem],
    ) -> ModelTurn:
        del intent
        self.received_histories.append(list(history))
        if not self._turns:
            raise RuntimeError("Fake model has no scripted turn left")
        return self._turns.popleft()


class OpenAIResponsesModelClient:
    """Adapts OpenAI Responses function calls to IntentFlow model turns."""

    def __init__(
        self,
        registry: ToolRegistry,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 45.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        self.registry = registry
        self.model = model
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._conversation: list[object] = []
        self._history_cursor = 0

    async def next_turn(
        self,
        intent: IntentBrief,
        history: list[AgentHistoryItem],
    ) -> ModelTurn:
        if not history:
            self._conversation = [self._intent_input(intent)]
            self._history_cursor = 0

        input_items = [*self._conversation, *self._tool_outputs(history)]
        request: dict[str, object] = {
            "model": self.model,
            "instructions": MODEL_INSTRUCTIONS,
            "tools": self.registry.schemas(),
            "input": input_items,
        }

        response = await self.client.responses.create(**request)
        turn = self._to_model_turn(response)
        self._conversation = [*input_items, *response.output]
        self._history_cursor = len(history)
        return turn

    @staticmethod
    def _intent_input(intent: IntentBrief) -> dict[str, object]:
        return {
            "role": "user",
            "content": (
                "Implement this IntentBrief in the controlled workspace:\n"
                + intent.model_dump_json(indent=2)
            ),
        }

    def _tool_outputs(
        self,
        history: list[AgentHistoryItem],
    ) -> list[dict[str, object]]:
        return [
            {
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": item.model_dump_json(),
            }
            for item in history[self._history_cursor :]
            if isinstance(item, ToolResult)
        ]

    @staticmethod
    def _to_model_turn(response: object) -> ModelTurn:
        tool_calls: list[IntentFlowToolCall] = []
        for item in response.output:
            if item.type != "function_call":
                continue

            try:
                arguments = json.loads(item.arguments)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"Model returned invalid JSON for {item.name}") from error
            if not isinstance(arguments, dict):
                raise RuntimeError(f"Model returned non-object arguments for {item.name}")

            metadata = arguments.pop("_intentflow", {})
            if not isinstance(metadata, dict):
                metadata = {}
            tool_calls.append(
                IntentFlowToolCall(
                    id=item.call_id,
                    name=item.name,
                    arguments=arguments,
                    action=str(metadata.get("action", "")),
                    reason=str(metadata.get("reason", "")),
                    related_requirement_ids=metadata.get("related_requirement_ids", []),
                )
            )

        if not tool_calls:
            raise RuntimeError("Model response did not contain a function call")

        first_call = tool_calls[0]
        return ModelTurn(
            action=first_call.action or f"调用 {first_call.name}",
            reason=first_call.reason or "模型根据当前 IntentBrief 选择了下一步工具",
            related_requirement_ids=first_call.related_requirement_ids,
            tool_calls=tool_calls,
        )


MODEL_INSTRUCTIONS = """You are the coding model inside IntentFlow.
Use only the provided tools. Do not claim that you edited files or ran commands without tools.
Inspect before editing. When a tool fails, use its returned result to recover.
Call report_result only after the implementation has a successful test or build command.
Every function call must include _intentflow with a concise user-visible action, reason,
and the related requirement IDs. These fields must describe observable engineering actions,
not hidden chain-of-thought. Use report_result instead of returning a final text-only answer.
"""
