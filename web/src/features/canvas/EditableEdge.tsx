import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

type EditableEdgeCallbacks = {
  editable: boolean;
  editingEdgeId: string | null;
  onStartEditing: (id: string) => void;
  onChange: (id: string, label: string) => void;
  onRemove: (id: string) => void;
  onFinishEditing: () => void;
};

const EditableEdgeContext = createContext<EditableEdgeCallbacks>({
  editable: true,
  editingEdgeId: null,
  onStartEditing: () => undefined,
  onChange: () => undefined,
  onRemove: () => undefined,
  onFinishEditing: () => undefined,
});

export function EditableEdgeProvider({
  callbacks,
  children,
}: {
  callbacks: EditableEdgeCallbacks;
  children: ReactNode;
}) {
  return (
    <EditableEdgeContext.Provider value={callbacks}>
      {children}
    </EditableEdgeContext.Provider>
  );
}

export function EditableEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  label,
  markerStart,
  markerEnd,
  interactionWidth,
  style,
}: EdgeProps) {
  const callbacks = useContext(EditableEdgeContext);
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const labelText = typeof label === "string" ? label : "";
  const editing = callbacks.editable && callbacks.editingEdgeId === id;
  const [draft, setDraft] = useState(labelText);
  const composing = useRef(false);
  const labelPosition = {
    transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
  };

  useEffect(() => {
    if (editing) setDraft(labelText);
  }, [editing, labelText]);

  function finishEditing() {
    callbacks.onChange(id, draft);
    callbacks.onFinishEditing();
  }

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerStart={markerStart}
        markerEnd={markerEnd}
        interactionWidth={interactionWidth}
        style={style}
      />
      <EdgeLabelRenderer>
        {editing ? (
          <div
            className="inline-edge-editor nodrag nopan"
            style={labelPosition}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) {
                finishEditing();
              }
            }}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            <span className="inline-edge-editor__measure" aria-hidden="true">
              {draft || "输入文字"}
            </span>
            <input
              autoFocus
              aria-label="连线文字"
              size={1}
              value={draft}
              placeholder="输入文字"
              onChange={(event) => setDraft(event.target.value)}
              onCompositionStart={() => {
                composing.current = true;
              }}
              onCompositionEnd={(event) => {
                composing.current = false;
                setDraft(event.currentTarget.value);
              }}
              onFocus={(event) => event.currentTarget.select()}
              onKeyDown={(event) => {
                event.stopPropagation();
                if (composing.current || event.nativeEvent.isComposing) return;
                if (event.key === "Enter" || event.key === "Escape") {
                  event.currentTarget.blur();
                }
              }}
            />
            <button
              aria-label="删除连线"
              type="button"
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => callbacks.onRemove(id)}
            >
              ×
            </button>
          </div>
        ) : labelText ? (
          <span
            className={`editable-edge-label ${callbacks.editable ? "nodrag nopan" : ""}`}
            style={labelPosition}
            onDoubleClick={callbacks.editable ? (event) => {
              event.stopPropagation();
              callbacks.onStartEditing(id);
            } : undefined}
          >
            {labelText}
          </span>
        ) : null}
      </EdgeLabelRenderer>
    </>
  );
}
