import json
import unicodedata
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from app.agent.models import IntentBrief, IntentRequirement
from app.intent.models import CanvasConnection, CanvasNote, CanvasPosition, IntentCanvas


class IntentCompileError(RuntimeError):
    """Raised when the model cannot produce a valid, traceable IntentBrief."""


class IntentRequestDecision(BaseModel):
    action: Literal["answer", "propose", "execute"] = "answer"
    brief: IntentBrief | None = None
    canvas: IntentCanvas | None = None
    response: str | None = None


class PlanCanvasNote(BaseModel):
    id: str
    text: str
    label: Literal["idea", "behavior", "constraint", "acceptance"]


class PlanCanvas(BaseModel):
    notes: list[PlanCanvasNote] = Field(default_factory=list)
    connections: list[CanvasConnection] = Field(default_factory=list)


class AIIntentCompiler:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 45.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        self.model = model
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )

    async def compile(
        self,
        canvas: IntentCanvas,
        *,
        project_context: str = "",
    ) -> IntentBrief:
        validate_canvas_input(canvas)
        validation_feedback = ""
        for attempt in range(2):
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    instructions=AI_COMPILER_INSTRUCTIONS,
                    tools=[INTENT_BRIEF_TOOL],
                    input=[
                        {
                            "role": "user",
                            "content": self._model_input(
                                canvas,
                                validation_feedback,
                                project_context,
                            ),
                        }
                    ],
                )
            except Exception as error:
                raise IntentCompileError(f"模型服务调用失败：{error}") from error

            try:
                brief = _parse_model_brief(response)
                validate_compiled_brief(canvas, brief)
                return brief
            except IntentCompileError as error:
                if attempt == 1:
                    raise IntentCompileError(f"模型连续两次返回无效结果：{error}") from error
                validation_feedback = str(error)

        raise AssertionError("Intent compiler retry loop ended unexpectedly")

    async def compile_agent_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        return await self._compile_routed_request(
            canvas,
            primary_source_id,
            project_context=project_context,
            session_context=session_context,
            instructions=AGENT_REQUEST_INSTRUCTIONS,
            tools=[INTENT_BRIEF_TOOL, RESPOND_TO_USER_TOOL],
            brief_action="execute",
            allow_plan=False,
        )

    async def compile_plan_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        return await self._compile_routed_request(
            canvas,
            primary_source_id,
            project_context=project_context,
            session_context=session_context,
            instructions=PLAN_REQUEST_INSTRUCTIONS,
            tools=[PLAN_TOOL, RESPOND_TO_USER_TOOL],
            brief_action="propose",
            allow_plan=True,
        )

    async def refine_plan(
        self,
        original: IntentBrief,
        canvas: IntentCanvas,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentBrief:
        validate_canvas_input(canvas)
        validation_feedback = ""
        for attempt in range(2):
            content = (
                "Rebuild the complete execution-ready IntentBrief from the original task draft "
                "and the user's edited visual Canvas. The Canvas contains compact decisions, not "
                "all implementation detail. Preserve original detail unless the edited Canvas "
                "clearly changes or removes it. Canvas decisions win when they conflict.\n\n"
                f"Original task draft:\n{original.model_dump_json(indent=2)}\n\n"
                f"Edited Canvas:\n{canvas.model_dump_json(indent=2)}"
            )
            if project_context:
                content += "\n\nRead-only snapshot of the current project:\n" + project_context
            if session_context:
                content += "\n\n" + session_context
            if validation_feedback:
                content += (
                    "\n\nYour previous result failed validation. Call submit_intent_brief "
                    f"again with a corrected result. Validation error: {validation_feedback}"
                )
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    instructions=REFINE_PLAN_INSTRUCTIONS,
                    tools=[INTENT_BRIEF_TOOL],
                    input=[{"role": "user", "content": content}],
                )
            except Exception as error:
                raise IntentCompileError(f"模型服务调用失败：{error}") from error

            try:
                brief = _parse_model_brief(response)
                validate_compiled_brief(canvas, brief)
                return brief
            except IntentCompileError as error:
                if attempt == 1:
                    raise IntentCompileError(f"模型连续两次返回无效结果：{error}") from error
                validation_feedback = str(error)

        raise AssertionError("Plan refinement retry loop ended unexpectedly")

    async def _compile_routed_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str,
        session_context: str,
        instructions: str,
        tools: list[dict[str, object]],
        brief_action: Literal["propose", "execute"],
        allow_plan: bool,
    ) -> IntentRequestDecision:
        validate_canvas_input(canvas)
        validation_feedback = ""
        for attempt in range(2):
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    instructions=instructions,
                    tools=tools,
                    input=[
                        {
                            "role": "user",
                            "content": self._agent_request_input(
                                canvas,
                                primary_source_id,
                                validation_feedback,
                                project_context,
                                session_context,
                            ),
                        }
                    ],
                )
            except Exception as error:
                raise IntentCompileError(f"模型服务调用失败：{error}") from error

            try:
                decision = _parse_request_decision(
                    response,
                    brief_action=brief_action,
                    allow_plan=allow_plan,
                )
                if decision.brief is not None:
                    validate_compiled_brief(canvas, decision.brief)
                if decision.canvas is not None:
                    validate_generated_canvas(decision.canvas, decision.brief)
                return decision
            except IntentCompileError as error:
                if attempt == 1:
                    raise IntentCompileError(f"模型连续两次返回无效结果：{error}") from error
                validation_feedback = str(error)

        raise AssertionError("Intent request compiler retry loop ended unexpectedly")

    @staticmethod
    def _model_input(
        canvas: IntentCanvas,
        validation_feedback: str,
        project_context: str,
    ) -> str:
        content = (
            "Organize this free-form canvas into an IntentBrief.\n"
            + canvas.model_dump_json(indent=2)
        )
        if project_context:
            content += "\n\nRead-only snapshot of the current project:\n" + project_context
        if validation_feedback:
            content += (
                "\n\nYour previous result failed validation. Call submit_intent_brief again with "
                f"a corrected result. Validation error: {validation_feedback}"
            )
        return content

    @staticmethod
    def _agent_request_input(
        canvas: IntentCanvas,
        primary_source_id: str,
        validation_feedback: str,
        project_context: str,
        session_context: str,
    ) -> str:
        content = (
            f'The latest user message is the note with id "{primary_source_id}". '
            "Treat it as the primary instruction. The rest of the canvas and prior conversation "
            "are optional context only.\n"
            + canvas.model_dump_json(indent=2)
        )
        if project_context:
            content += "\n\nRead-only snapshot of the current project:\n" + project_context
        if session_context:
            content += "\n\n" + session_context
        if validation_feedback:
            content += (
                "\n\nYour previous result failed validation. Choose one tool again with a "
                f"corrected result. Validation error: {validation_feedback}"
            )
        return content


def compile_canvas(canvas: IntentCanvas) -> IntentBrief:
    validate_canvas_input(canvas)
    notes = [note for note in canvas.notes if note.text.strip()]
    note_by_id = {note.id: note for note in notes}

    requirement_notes = [note for note in notes if note.label == "behavior"]
    if not requirement_notes:
        requirement_notes = [
            note for note in notes if note.label not in {"constraint", "acceptance"}
        ]
    if not requirement_notes:
        requirement_notes = [note for note in notes if note.label == "acceptance"]
    if not requirement_notes and notes:
        requirement_notes = [notes[0]]

    constraints = [note.text.strip() for note in notes if note.label == "constraint"]
    supplemental_text = canvas.supplemental_text.strip()
    if supplemental_text:
        constraints.append(f"补充说明：{supplemental_text}")

    requirements = [
        _compile_requirement(index, note, canvas, note_by_id)
        for index, note in enumerate(requirement_notes, start=1)
    ]
    if not requirements and supplemental_text:
        requirements = [
            IntentRequirement(
                id="REQ-01",
                description=supplemental_text,
                acceptance_criteria=[f"能够观察并验证：{supplemental_text}"],
            )
        ]
    lead_note = next((note for note in notes if note.label == "idea"), None)
    lead_text = lead_note.text.strip() if lead_note else requirements[0].description

    brief = IntentBrief(
        title=_shorten(lead_text, 28),
        goal=lead_text,
        requirements=requirements,
        constraints=constraints,
    )
    validate_compiled_brief(canvas, brief)
    return brief


def validate_compiled_brief(canvas: IntentCanvas, brief: IntentBrief) -> None:
    if not brief.title.strip() or not brief.goal.strip():
        raise IntentCompileError("IntentBrief 的标题和目标不能为空")
    if not brief.requirements:
        raise IntentCompileError("IntentBrief 至少需要一项需求")

    expected_ids = [f"REQ-{index:02d}" for index in range(1, len(brief.requirements) + 1)]
    requirement_ids = [requirement.id for requirement in brief.requirements]
    if requirement_ids != expected_ids:
        raise IntentCompileError("需求 ID 必须从 REQ-01 开始连续编号且不能重复")

    source_note_ids = {
        note.id for note in canvas.notes if note.text.strip()
    }
    for requirement in brief.requirements:
        if not requirement.description.strip():
            raise IntentCompileError(f"{requirement.id} 的描述不能为空")
        if not requirement.acceptance_criteria or any(
            not criterion.strip() for criterion in requirement.acceptance_criteria
        ):
            raise IntentCompileError(f"{requirement.id} 至少需要一条非空验收标准")
        if len(requirement.source_ids) != len(set(requirement.source_ids)):
            raise IntentCompileError(f"{requirement.id} 包含重复的来源便签 ID")
        unknown_ids = set(requirement.source_ids) - source_note_ids
        if unknown_ids:
            unknown = "、".join(sorted(unknown_ids))
            raise IntentCompileError(f"{requirement.id} 引用了不存在的来源便签：{unknown}")
        if source_note_ids and not requirement.source_ids:
            raise IntentCompileError(f"{requirement.id} 缺少来源便签 ID")

    if any(not constraint.strip() for constraint in brief.constraints):
        raise IntentCompileError("约束内容不能为空")


def _parse_model_brief(response: Any, tool_name: str = "submit_intent_brief") -> IntentBrief:
    function_call = next(
        (
            item
            for item in response.output
            if item.type == "function_call" and item.name == tool_name
        ),
        None,
    )
    if function_call is None:
        raise IntentCompileError("模型没有提交结构化 IntentBrief")

    try:
        payload = json.loads(function_call.arguments)
        brief = IntentBrief.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValidationError) as error:
        raise IntentCompileError(f"模型返回的 IntentBrief 无法通过结构校验：{error}") from error
    return brief


def _parse_plan_proposal(response: Any) -> tuple[IntentBrief, IntentCanvas]:
    function_call = next(
        (
            item
            for item in response.output
            if item.type == "function_call" and item.name == "submit_plan"
        ),
        None,
    )
    if function_call is None:
        raise IntentCompileError("模型没有提交结构化任务草案")

    try:
        payload = json.loads(function_call.arguments)
        canvas = _layout_plan_canvas(PlanCanvas.model_validate(payload.pop("canvas")))
        brief = IntentBrief.model_validate(payload)
    except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as error:
        raise IntentCompileError(f"模型返回的任务草案无法通过结构校验：{error}") from error
    return brief, canvas


def _layout_plan_canvas(plan: PlanCanvas) -> IntentCanvas:
    """Lay out a compact plan as a left-to-right task map."""
    notes_by_id = {note.id: note for note in plan.notes}
    behavior_ids = [note.id for note in plan.notes if note.label == "behavior"]
    detail_ids = [
        note.id
        for note in plan.notes
        if note.label in {"constraint", "acceptance"}
    ]
    details_by_behavior = {note_id: [] for note_id in behavior_ids}
    assigned_details: set[str] = set()

    for connection in plan.connections:
        source = notes_by_id.get(connection.source)
        target = notes_by_id.get(connection.target)
        if source is None or target is None:
            continue
        if (
            source.label == "behavior"
            and target.id in detail_ids
            and target.id not in assigned_details
        ):
            details_by_behavior[source.id].append(target.id)
            assigned_details.add(target.id)
        elif (
            target.label == "behavior"
            and source.id in detail_ids
            and source.id not in assigned_details
        ):
            details_by_behavior[target.id].append(source.id)
            assigned_details.add(source.id)

    positions: dict[str, CanvasPosition] = {}
    cursor_y = 60.0
    for behavior_id in behavior_ids:
        attached_ids = list(dict.fromkeys(details_by_behavior[behavior_id]))
        row_count = max(1, len(attached_ids))
        for index, detail_id in enumerate(attached_ids):
            positions.setdefault(
                detail_id,
                CanvasPosition(x=700, y=cursor_y + index * 160),
            )
        positions[behavior_id] = CanvasPosition(
            x=380,
            y=cursor_y + (row_count - 1) * 80,
        )
        cursor_y += row_count * 160 + 40

    for detail_id in detail_ids:
        if detail_id in assigned_details:
            continue
        positions[detail_id] = CanvasPosition(x=700, y=cursor_y)
        cursor_y += 160

    behavior_center = (
        sum(positions[note_id].y for note_id in behavior_ids) / len(behavior_ids)
        if behavior_ids
        else 60.0
    )
    idea_ids = [note.id for note in plan.notes if note.label == "idea"]
    idea_targets: list[tuple[str, float]] = []
    for index, idea_id in enumerate(idea_ids):
        connected_behavior_y = [
            positions[other_id].y
            for connection in plan.connections
            if idea_id in {connection.source, connection.target}
            for other_id in [
                connection.target if connection.source == idea_id else connection.source
            ]
            if other_id in positions and notes_by_id[other_id].label == "behavior"
        ]
        desired_y = (
            sum(connected_behavior_y) / len(connected_behavior_y)
            if connected_behavior_y
            else behavior_center + index * 160
        )
        idea_targets.append((idea_id, desired_y))

    previous_y: float | None = None
    for idea_id, desired_y in sorted(idea_targets, key=lambda item: item[1]):
        y = desired_y if previous_y is None else max(desired_y, previous_y + 160)
        positions[idea_id] = CanvasPosition(x=60, y=y)
        previous_y = y

    return IntentCanvas(
        notes=[
            CanvasNote(
                id=note.id,
                text=note.text,
                label=note.label,
                position=positions.get(note.id, CanvasPosition(x=380, y=cursor_y)),
            )
            for note in plan.notes
        ],
        connections=plan.connections,
    )


def _parse_request_decision(
    response: Any,
    *,
    brief_action: Literal["propose", "execute"],
    allow_plan: bool,
) -> IntentRequestDecision:
    function_calls = [item for item in response.output if item.type == "function_call"]
    if len(function_calls) != 1:
        raise IntentCompileError("模型必须且只能选择一种 Agent 响应")

    function_call = function_calls[0]
    if function_call.name == "submit_intent_brief":
        return IntentRequestDecision(
            action=brief_action,
            brief=_parse_model_brief(response),
        )
    if function_call.name == "submit_plan":
        if not allow_plan:
            raise IntentCompileError("未开启 Canvas 规划模式，不能生成 Canvas 任务草案")
        brief, canvas = _parse_plan_proposal(response)
        return IntentRequestDecision(
            action="propose",
            brief=brief,
            canvas=canvas,
        )
    if function_call.name != "respond_to_user":
        raise IntentCompileError(f"模型调用了未知的 Agent 响应工具：{function_call.name}")

    try:
        payload = json.loads(function_call.arguments)
        message = str(payload["message"]).strip()
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise IntentCompileError("模型返回的非执行回复无法解析") from error
    if not message:
        raise IntentCompileError("模型返回的非执行回复不能为空")
    return IntentRequestDecision(action="answer", response=message)


def validate_canvas_input(canvas: IntentCanvas) -> None:
    notes = [note for note in canvas.notes if note.text.strip()]
    if not notes and not canvas.supplemental_text.strip():
        raise ValueError("Canvas needs at least one note or supplemental description")
    note_ids = [note.id for note in notes]
    if any(not note_id.strip() for note_id in note_ids):
        raise ValueError("Non-blank canvas notes must have a non-empty ID")
    if len(note_ids) != len(set(note_ids)):
        raise ValueError("Non-blank canvas note IDs must be unique")


def validate_generated_canvas(
    canvas: IntentCanvas,
    brief: IntentBrief | None = None,
) -> None:
    validate_canvas_input(canvas)
    if canvas.supplemental_text.strip():
        raise IntentCompileError("Canvas 提案不能把详细说明藏在补充文本中")

    notes = [note for note in canvas.notes if note.text.strip()]
    note_ids = {note.id for note in notes}
    labels = {note.label for note in notes}
    required_labels = {"idea", "behavior", "acceptance"}
    if brief is not None and brief.constraints:
        required_labels.add("constraint")
    missing_labels = required_labels - labels
    if missing_labels:
        missing = "、".join(sorted(missing_labels))
        raise IntentCompileError(f"Canvas 提案缺少关键信息类型：{missing}")

    normalized_texts: set[str] = set()
    for note in notes:
        text = note.text.strip()
        if note.label is None:
            raise IntentCompileError(f"Canvas 卡片 {note.id} 缺少信息类型")
        if len([line for line in text.splitlines() if line.strip()]) > 2:
            raise IntentCompileError(f"Canvas 卡片 {note.id} 超过两行，请重新概括")
        if _display_units(text) > 48:
            raise IntentCompileError(f"Canvas 卡片 {note.id} 信息过多，请重新概括")
        if "..." in text or "…" in text:
            raise IntentCompileError(f"Canvas 卡片 {note.id} 不能用省略号截断内容")
        normalized = "".join(text.split()).casefold()
        if normalized in normalized_texts:
            raise IntentCompileError(f"Canvas 卡片 {note.id} 与其他卡片内容重复")
        normalized_texts.add(normalized)

    connection_ids: set[str] = set()
    for connection in canvas.connections:
        if connection.id in connection_ids:
            raise IntentCompileError(f"Canvas 连线 ID 重复：{connection.id}")
        connection_ids.add(connection.id)
        if connection.source not in note_ids or connection.target not in note_ids:
            raise IntentCompileError(f"Canvas 连线 {connection.id} 指向不存在的卡片")
        if connection.source == connection.target:
            raise IntentCompileError(f"Canvas 连线 {connection.id} 不能连接卡片自身")


def _display_units(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        for character in text
    )


def _compile_requirement(
    index: int,
    note: CanvasNote,
    canvas: IntentCanvas,
    note_by_id: dict[str, CanvasNote],
) -> IntentRequirement:
    connected_ids: list[str] = []
    acceptance_criteria: list[str] = []
    for connection in canvas.connections:
        if note.id not in {connection.source, connection.target}:
            continue
        other_id = connection.target if connection.source == note.id else connection.source
        other_note = note_by_id.get(other_id)
        if other_note is None:
            continue
        connected_ids.append(other_id)
        if other_note.label == "acceptance":
            acceptance_criteria.append(other_note.text.strip())

    if note.label == "acceptance":
        acceptance_criteria.append(note.text.strip())
    if not acceptance_criteria:
        acceptance_criteria.append(f"能够观察并验证：{note.text.strip()}")

    return IntentRequirement(
        id=f"REQ-{index:02d}",
        description=note.text.strip(),
        acceptance_criteria=_unique(acceptance_criteria),
        source_ids=_unique([note.id, *connected_ids]),
    )


def _shorten(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}…"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


AI_COMPILER_INSTRUCTIONS = """You are the intent compiler inside IntentFlow.
Convert the user's free-form notes, connections, labels, positions, and supplemental text into
one structured IntentBrief by calling submit_intent_brief exactly once.

Rules:
- Labels, connections, and spatial positions are hints, not mandatory structure.
- Ignore blank notes. Preserve meaningful isolated notes and supplemental text.
- Do not silently resolve contradictions. Keep conflicting expectations visible in requirements,
  acceptance criteria, or constraints.
- Do not invent product behavior or source IDs.
- Number requirements consecutively as REQ-01, REQ-02, and so on.
- Every requirement needs at least one observable acceptance criterion.
- source_ids may only contain IDs copied exactly from non-blank input notes. If notes exist, every
  requirement must reference at least one note. For supplemental-text-only input, use an empty list.
- Return concise user-facing Chinese text when the input is Chinese.
- Use the supplied project snapshot to make the plan consistent with existing code, but do not
  claim to have changed files or run commands.
"""


AGENT_REQUEST_INSTRUCTIONS = """You are the unified conversational coding Agent inside IntentFlow.
The latest user message is the primary instruction. Canvas notes, earlier conversation, and the
read-only project snapshot are supporting context and must never trigger execution by themselves.
The authoritative session context contains persisted Run, approval, verification, and final review
facts. Trust those structured facts over claims in conversational text.

Choose exactly one tool:
- Call submit_intent_brief only when the latest message clearly asks to inspect, change, test, or
  otherwise act on the coding project. If the message explicitly asks to implement the attached
  Canvas, you may use the Canvas as task requirements.
- Call respond_to_user for greetings, thanks, small talk, unclear fragments, or questions that
  do not clearly request project action. A text request to plan or discuss an approach must also
  receive a normal text response; Canvas planning is only available through the explicit UI mode.
  You may answer questions about the project or session state, including whether a Run was kept or
  undone. Briefly reply in the user's language. Do not claim to have changed files or run commands.

When submitting an IntentBrief, follow the same traceability rules as the intent compiler: preserve
meaningful constraints, use consecutive requirement IDs, provide observable acceptance criteria,
and only cite source IDs present in the input. Return concise Chinese text for Chinese input.
"""


PLAN_REQUEST_INSTRUCTIONS = """You route the latest Plan-mode message inside IntentFlow.
The latest user message is the primary instruction. Canvas notes, earlier conversation, and the
read-only project snapshot are supporting context and must not turn a question into a plan.

Choose exactly one tool:
- Call submit_intent_brief only when the latest message clearly asks for an implementation plan,
  design proposal, task breakdown, or changes to the coding project.
- Call respond_to_user for factual questions about the project, explanations, greetings, thanks,
  small talk, or unclear fragments. Answer directly and naturally in the user's language. Do not
  manufacture requirements or acceptance criteria for a simple question.

When submitting a plan, preserve meaningful constraints, use consecutive requirement IDs, provide
observable acceptance criteria, and only cite source IDs present in the input. Never claim to have
changed files or run commands. Return both a complete task draft and a compact visual Canvas. Keep
implementation and verification detail in the task draft, not in Canvas cards.
"""


REFINE_PLAN_INSTRUCTIONS = """You turn an edited visual planning Canvas back into a complete,
execution-ready IntentBrief by calling submit_intent_brief exactly once.

Rules:
- The Canvas is deliberately concise. Do not mistake short cards for a request to delete useful
  implementation detail from the original task draft.
- Preserve original requirements, constraints, and acceptance details unless the edited Canvas
  clearly changes, removes, or contradicts them.
- Treat idea cards as goals, behavior cards as requested capabilities, constraint cards as
  boundaries, and acceptance cards as observable completion conditions.
- Use connections to decide which constraints and acceptance conditions belong to which behavior.
- Canvas edits override conflicting text in the original task draft.
- Number requirements consecutively as REQ-01, REQ-02, and so on.
- Every requirement needs at least one observable acceptance criterion.
- source_ids may only contain IDs copied exactly from non-blank Canvas cards.
- Return concise user-facing Chinese text when the input is Chinese.
"""


INTENT_BRIEF_TOOL: dict[str, object] = {
    "type": "function",
    "name": "submit_intent_brief",
    "description": "Submit the structured and source-traceable IntentBrief.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "goal": {"type": "string"},
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "pattern": r"^REQ-\d{2}$"},
                        "description": {"type": "string"},
                        "acceptance_criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "source_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "id",
                        "description",
                        "acceptance_criteria",
                        "source_ids",
                    ],
                    "additionalProperties": False,
                },
            },
            "constraints": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "goal", "requirements", "constraints"],
        "additionalProperties": False,
    },
    "strict": False,
}


PLAN_TOOL: dict[str, object] = {
    "type": "function",
    "name": "submit_plan",
    "description": (
        "Submit a complete implementation plan and a compact visual Canvas without starting a Run."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "goal": {"type": "string"},
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "pattern": r"^REQ-\d{2}$"},
                        "description": {"type": "string"},
                        "acceptance_criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "source_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "id",
                        "description",
                        "acceptance_criteria",
                        "source_ids",
                    ],
                    "additionalProperties": False,
                },
            },
            "constraints": {"type": "array", "items": {"type": "string"}},
            "canvas": {
                "type": "object",
                "description": (
                    "A visual decision overview, not a copy of the task draft. Use one compact, "
                    "complete concept per card. Let the graph grow naturally: an idea may "
                    "branch to multiple behavior cards, and constraints or acceptance cards "
                    "should connect to the behavior they qualify. Do not include requirement IDs, "
                    "implementation steps, long prose, ellipses, hidden detail, or duplicated text."
                ),
                "properties": {
                    "notes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {
                                    "type": "string",
                                    "description": (
                                        "One short, self-contained concept that fits in one or two "
                                        "lines. Semantically summarize instead of truncating."
                                    ),
                                },
                                "label": {
                                    "type": "string",
                                    "enum": ["idea", "behavior", "constraint", "acceptance"],
                                },
                            },
                            "required": ["id", "text", "label"],
                            "additionalProperties": False,
                        },
                    },
                    "connections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "label": {
                                    "type": "string",
                                    "description": "Optional short relationship phrase.",
                                },
                            },
                            "required": ["id", "source", "target", "label"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["notes", "connections"],
                "additionalProperties": False,
            },
        },
        "required": ["title", "goal", "requirements", "constraints", "canvas"],
        "additionalProperties": False,
    },
    "strict": False,
}


RESPOND_TO_USER_TOOL: dict[str, object] = {
    "type": "function",
    "name": "respond_to_user",
    "description": "Reply naturally when the latest message does not require a structured task.",
    "parameters": {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    },
    "strict": False,
}
