# Agent Harness 固定评测

`harness_tasks.json` 固定了 P3 的任务 ID、输入意图和成功条件。`automated` 场景由
pytest 覆盖；`real-model` 和 `fixture` 场景用于同一模型、同一配置下的改造前后对照。

每次评测保存一份 JSON，不覆盖历史结果：

```json
{
  "run_label": "after-context-manager",
  "model": "provider/model-version",
  "configuration": {
    "context_window_tokens": 64000,
    "keep_recent_tokens": 12000
  },
  "tasks": [
    {
      "task_id": "search-before-edit",
      "success": true,
      "final_status": "completed",
      "model_turns": 5,
      "tool_calls": 6,
      "duration_ms": 12400,
      "actual_input_tokens": 8200,
      "output_tokens": 1300,
      "compression_count": 1,
      "notes": ""
    }
  ]
}
```

对照时至少汇总任务成功率、模型轮数、工具调用数、总耗时、输入/输出 Token 和上下文压缩
次数。模型、端点、任务文件版本和预算配置必须相同；人工审批等待时间不计入模型能力结论。
真实模型结果需要单独标明，不能用 FakeModel 或单元测试结果冒充。
