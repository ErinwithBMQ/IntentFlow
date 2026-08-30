from types import SimpleNamespace

from app.agent.model_client import OpenAIResponsesModelClient, classify_model_error
from app.agent.models import IntentBrief, IntentRequirement, ToolResult
from app.agent.tools import ToolRegistry


class FakeResponsesAPI:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object) -> object:
        self.requests.append(request)
        return self.responses.pop(0)


class FakeOpenAIClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = FakeResponsesAPI(responses)


def response(response_id: str, *items: object) -> object:
    return SimpleNamespace(id=response_id, output=list(items))


def function_call(call_id: str, name: str, arguments: str) -> object:
    return SimpleNamespace(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


def make_intent() -> IntentBrief:
    return IntentBrief(
        title="Add a task",
        goal="Allow non-empty tasks to be added.",
        requirements=[IntentRequirement(id="REQ-1", description="Submitting text creates a task.")],
    )


async def test_responses_client_maps_function_calls_and_continues_with_tool_results() -> None:
    first_response = response(
        "response-1",
        SimpleNamespace(type="reasoning"),
        function_call(
            "call-1",
            "read_file",
            """{
                "path": "src/main.js",
                "_intentflow": {
                    "action": "读取提交处理器",
                    "reason": "先确认当前缺失的行为",
                    "related_requirement_ids": ["REQ-1"]
                }
            }""",
        ),
    )
    first_response.usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
    )
    second_response = response(
        "response-2",
        function_call(
            "call-2",
            "report_result",
            """{
                "status": "failed",
                "summary": "演示响应",
                "_intentflow": {
                    "action": "报告结果",
                    "reason": "测试适配器的第二回合",
                    "related_requirement_ids": ["REQ-1"]
                }
            }""",
        ),
    )
    fake_client = FakeOpenAIClient([first_response, second_response])
    registry = ToolRegistry()
    client = OpenAIResponsesModelClient(
        registry,
        "test-model",
        client=fake_client,
    )

    first_turn = await client.next_turn(make_intent(), [])
    tool_result = ToolResult(
        call_id="call-1",
        tool_name="read_file",
        ok=True,
        summary="Read src/main.js",
        output="file contents",
    )
    await client.next_turn(make_intent(), [first_turn, tool_result])

    assert first_turn.action == "读取提交处理器"
    assert first_turn.related_requirement_ids == ["REQ-1"]
    assert first_turn.tool_calls[0].arguments == {"path": "src/main.js"}
    assert first_turn.usage.total_tokens == 150
    assert fake_client.responses.requests[0]["model"] == "test-model"
    assert fake_client.responses.requests[0]["tools"] == registry.schemas()
    second_request = fake_client.responses.requests[1]
    assert "previous_response_id" not in second_request
    assert first_response.output[0] in second_request["input"]
    assert second_request["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": tool_result.model_dump_json(),
    }


async def test_new_empty_history_starts_a_fresh_response_chain() -> None:
    fake_client = FakeOpenAIClient(
        [
            response("response-1", function_call("call-1", "list_files", '{"path": "."}')),
            response("response-2", function_call("call-2", "list_files", '{"path": "."}')),
        ]
    )
    client = OpenAIResponsesModelClient(ToolRegistry(), "test-model", client=fake_client)

    await client.next_turn(make_intent(), [])
    await client.next_turn(make_intent(), [])

    assert "previous_response_id" not in fake_client.responses.requests[1]
    assert len(fake_client.responses.requests[1]["input"]) == 1


async def test_tool_schema_contains_visible_action_metadata() -> None:
    read_file_schema = next(
        schema for schema in ToolRegistry().schemas() if schema["name"] == "read_file"
    )

    assert read_file_schema["type"] == "function"
    assert "_intentflow" in read_file_schema["parameters"]["required"]
    metadata = read_file_schema["parameters"]["properties"]["_intentflow"]
    assert metadata["required"] == ["action", "reason", "related_requirement_ids"]

    report_schema = next(
        schema for schema in ToolRegistry().schemas() if schema["name"] == "report_result"
    )
    assert "requirements" in report_schema["parameters"]["required"]
    assert "requirements" in report_schema["parameters"]["properties"]


async def test_responses_client_summarizes_context_and_records_usage() -> None:
    summary_response = SimpleNamespace(
        output_text="- Goal: keep the task working\n- Next: rerun tests",
        usage={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
    )
    fake_client = FakeOpenAIClient([summary_response])
    client = OpenAIResponsesModelClient(ToolRegistry(), "test-model", client=fake_client)

    summary, usage = await client.summarize_context("long transcript", "older summary")

    assert "rerun tests" in summary
    assert usage is not None
    assert usage.total_tokens == 100
    assert "tools" not in fake_client.responses.requests[0]


def test_model_errors_are_classified_by_retryability() -> None:
    class ProviderError(Exception):
        def __init__(self, status_code: int) -> None:
            super().__init__(f"provider returned {status_code}")
            self.status_code = status_code

    temporary = classify_model_error(ProviderError(429))
    configuration = classify_model_error(ProviderError(401))

    assert temporary.kind == "retryable_model"
    assert temporary.retryable is True
    assert configuration.kind == "configuration"
    assert configuration.retryable is False
