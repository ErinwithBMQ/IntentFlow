import { Save, X } from "lucide-react";
import { useEffect, useState } from "react";

import type {
  ModelSettingsResponse,
  UpdateModelSettingsRequest,
} from "../../services/api";

type ModelSettingsDialogProps = {
  open: boolean;
  settings: ModelSettingsResponse | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (settings: UpdateModelSettingsRequest) => void;
};

export function ModelSettingsDialog({
  open,
  settings,
  busy,
  error,
  onClose,
  onSave,
}: ModelSettingsDialogProps) {
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [modelsText, setModelsText] = useState("");
  const [activeModel, setActiveModel] = useState("");

  useEffect(() => {
    if (!open) return;
    setApiKey("");
    setBaseUrl(settings?.base_url ?? "");
    setModelsText(settings?.models.join("\n") ?? "");
    setActiveModel(settings?.active_model ?? "");
  }, [open, settings]);

  if (!open) return null;

  const models = parseModels(modelsText);

  function changeModels(value: string) {
    const nextModels = parseModels(value);
    setModelsText(value);
    if (!nextModels.includes(activeModel)) setActiveModel(nextModels[0] ?? "");
  }

  function save() {
    if (!activeModel || models.length === 0) return;
    onSave({
      api_key: apiKey.trim() || null,
      base_url: baseUrl.trim(),
      models,
      active_model: activeModel,
    });
  }

  return (
    <div className="project-dialog-backdrop" role="presentation">
      <section className="project-dialog model-settings-dialog" role="dialog" aria-modal="true" aria-label="模型配置">
        <header>
          <div>
            <span>MODEL PROVIDER</span>
            <h2>模型配置</h2>
          </div>
          <button type="button" aria-label="关闭模型配置" onClick={onClose}>
            <X size={17} />
          </button>
        </header>

        <div className="project-dialog__body">
          <label>
            API URL
            <input
              value={baseUrl}
              placeholder="https://api.openai.com/v1"
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </label>
          <label>
            API Key
            <input
              type="password"
              autoComplete="new-password"
              value={apiKey}
              placeholder={settings?.has_api_key ? "已配置，留空表示保持不变" : "请输入 API Key"}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>
          <label>
            可用模型（每行一个）
            <textarea
              rows={5}
              value={modelsText}
              placeholder={"例如：\ngpt-5.2\ndeepseek-v3.2"}
              onChange={(event) => changeModels(event.target.value)}
            />
          </label>
          <label>
            当前模型
            <select
              value={activeModel}
              disabled={models.length === 0}
              onChange={(event) => setActiveModel(event.target.value)}
            >
              {models.length === 0 && <option value="">请先填写模型列表</option>}
              {models.map((model) => <option key={model} value={model}>{model}</option>)}
            </select>
          </label>
          <p className="project-dialog__note">
            目前仅支持兼容 OpenAI Responses API 的服务。
          </p>
          <button
            className="project-dialog__primary"
            type="button"
            disabled={busy || models.length === 0 || !activeModel || (!settings?.has_api_key && !apiKey.trim())}
            onClick={save}
          >
            <Save size={15} />保存模型配置
          </button>
        </div>

        {error && <p className="project-dialog__error">{error}</p>}
      </section>
    </div>
  );
}

function parseModels(value: string): string[] {
  return [...new Set(value.split("\n").map((model) => model.trim()).filter(Boolean))];
}
