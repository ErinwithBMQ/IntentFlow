from app.agent.models import IntentBrief, IntentRequirement
from app.intent.models import CanvasNote, IntentCanvas


def compile_canvas(canvas: IntentCanvas) -> IntentBrief:
    notes = [note for note in canvas.notes if note.text.strip()]
    note_by_id = {note.id: note for note in notes}
    if not notes and not canvas.supplemental_text.strip():
        raise ValueError("Canvas needs at least one note or supplemental description")

    requirement_notes = [note for note in notes if note.label == "behavior"]
    if not requirement_notes:
        requirement_notes = [
            note for note in notes if note.label not in {"constraint", "acceptance"}
        ]
    if not requirement_notes:
        requirement_notes = [note for note in notes if note.label == "acceptance"]

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

    return IntentBrief(
        title=_shorten(lead_text, 28),
        goal=lead_text,
        requirements=requirements,
        constraints=constraints,
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
