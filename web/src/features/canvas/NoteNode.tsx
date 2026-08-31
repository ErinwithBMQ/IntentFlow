import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Grip, X } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";

import type { CanvasNoteLabel } from "../../services/api";
import type { NoteNode as NoteNodeType } from "./canvasState";

const LABELS: Array<{ value: CanvasNoteLabel | ""; label: string }> = [
  { value: "", label: "不设标签" },
  { value: "idea", label: "想法" },
  { value: "behavior", label: "行为" },
  { value: "constraint", label: "约束" },
  { value: "acceptance", label: "验收" },
];

type NoteNodeCallbacks = {
  editable: boolean;
  onChange: (id: string, text: string, label: CanvasNoteLabel | null) => void;
  onRemove: (id: string) => void;
};

const NoteNodeContext = createContext<NoteNodeCallbacks>({
  editable: true,
  onChange: () => undefined,
  onRemove: () => undefined,
});

export function NoteNodeProvider({
  callbacks,
  children,
}: {
  callbacks: NoteNodeCallbacks;
  children: ReactNode;
}) {
  return <NoteNodeContext.Provider value={callbacks}>{children}</NoteNodeContext.Provider>;
}

export function NoteNode({ id, data, selected }: NodeProps<NoteNodeType>) {
  const callbacks = useContext(NoteNodeContext);
  return (
    <article className={`note-node ${selected ? "note-node--selected" : ""}`}>
      <Handle className="note-handle" type="target" position={Position.Left} />
      <div className="note-node__top">
        <span className="note-node__grip">
          <Grip size={13} />
          便签
        </span>
        <button
          aria-label="删除便签"
          className="note-node__remove nodrag"
          type="button"
          disabled={!callbacks.editable}
          onClick={() => callbacks.onRemove(id)}
        >
          <X size={13} />
        </button>
      </div>
      <textarea
        className="note-node__text nodrag nowheel"
        value={data.text}
        readOnly={!callbacks.editable}
        placeholder="写下脑海里的片段……"
        onChange={(event) => callbacks.onChange(id, event.target.value, data.label)}
      />
      <select
        aria-label="便签标签"
        className="note-node__label nodrag"
        value={data.label ?? ""}
        disabled={!callbacks.editable}
        onChange={(event) =>
          callbacks.onChange(id, data.text, (event.target.value || null) as CanvasNoteLabel | null)
        }
      >
        {LABELS.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      <Handle className="note-handle" type="source" position={Position.Right} />
    </article>
  );
}
