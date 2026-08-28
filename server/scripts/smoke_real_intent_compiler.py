import asyncio

from app.intent.models import IntentCanvas
from app.main import create_ai_intent_compiler

SCENARIOS = {
    "unconnected_notes": {
        "notes": [
            {
                "id": "note-add",
                "text": "提交非空文字后立刻显示新任务",
                "label": None,
                "position": {"x": 80, "y": 100},
            },
            {
                "id": "note-empty",
                "text": "空白输入不能创建任务",
                "label": None,
                "position": {"x": 460, "y": 300},
            },
        ],
        "connections": [],
        "supplemental_text": "保持现有简洁样式",
    },
    "supplemental_text_only": {
        "notes": [],
        "connections": [],
        "supplemental_text": "增加一个清空全部待办的按钮，并能验证列表已经清空。",
    },
    "conflicting_notes": {
        "notes": [
            {
                "id": "note-submit-enter",
                "text": "按回车键应该提交新任务",
                "label": "behavior",
                "position": {"x": 100, "y": 120},
            },
            {
                "id": "note-no-enter",
                "text": "按回车键不能提交，只能点击按钮",
                "label": "constraint",
                "position": {"x": 420, "y": 120},
            },
        ],
        "connections": [],
        "supplemental_text": "不要自行忽略互相冲突的要求。",
    },
}


async def main() -> None:
    compiler = create_ai_intent_compiler()
    for name, payload in SCENARIOS.items():
        canvas = IntentCanvas.model_validate(payload)
        brief = await compiler.compile(canvas)
        print(f"\n=== {name} ===")
        print(brief.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
