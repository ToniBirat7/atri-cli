'use client';

import { useRef } from 'react';

interface WorkspaceAccessPanelProps {
  allowedDirectory: string;
  defaultDirectory?: string;
  isStreaming: boolean;
  onAllowedDirectoryChange: (value: string) => void;
  onReset: () => void;
}

export default function WorkspaceAccessPanel({
  allowedDirectory,
  defaultDirectory,
  isStreaming,
  onAllowedDirectoryChange,
  onReset,
}: WorkspaceAccessPanelProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const trimmedDirectory = allowedDirectory.trim();
  const accessLabel = trimmedDirectory ? 'Custom root' : 'Safe default';

  const focusDirectoryField = () => {
    if (isStreaming) {
      return;
    }

    inputRef.current?.focus();
    inputRef.current?.select();
  };

  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-4 shadow-[0_18px_60px_rgba(0,0,0,0.22)] backdrop-blur-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.24em] text-white/45">
            Workspace access
          </div>
          <p className="mt-2 text-sm leading-6 text-white/60">
            Scope tool calls to a project directory before the orchestrator runs
            them.
          </p>
        </div>
        <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] font-medium text-white/70">
          {accessLabel}
        </span>
      </div>

      <label className="mt-4 block">
        <span className="text-[11px] uppercase tracking-[0.24em] text-white/45">
          Allowed directory
        </span>
        <div className="mt-2 flex items-stretch gap-2">
          <button
            type="button"
            onClick={focusDirectoryField}
            disabled={isStreaming}
            className="inline-flex h-11.5 w-11.5 shrink-0 items-center justify-center rounded-2xl border border-sky-300/20 bg-sky-300/10 text-xl font-semibold text-sky-100 transition hover:border-sky-300/30 hover:bg-sky-300/15 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Focus directory path field"
            title="Click to paste the full directory path"
          >
            +
          </button>
          <input
            ref={inputRef}
            value={allowedDirectory}
            onChange={(event) => onAllowedDirectoryChange(event.target.value)}
            disabled={isStreaming}
            placeholder={
              defaultDirectory || 'Leave blank to use the orchestrator default'
            }
            className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition placeholder:text-white/30 focus:border-sky-300/40 focus:bg-black/30 disabled:cursor-not-allowed disabled:opacity-60"
          />
        </div>
      </label>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          onClick={onReset}
          disabled={isStreaming}
          className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/72 transition hover:border-white/20 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Reset to safe default
        </button>
        {defaultDirectory ? (
          <button
            onClick={() => onAllowedDirectoryChange(defaultDirectory)}
            disabled={isStreaming}
            className="rounded-full border border-sky-300/20 bg-sky-300/10 px-3 py-1.5 text-xs font-medium text-sky-100 transition hover:border-sky-300/30 hover:bg-sky-300/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Use suggested root
          </button>
        ) : null}
      </div>

      <p className="mt-3 text-xs leading-5 text-white/45">
        {trimmedDirectory
          ? `Selected root: ${trimmedDirectory}`
          : 'No custom root set. The backend will use its safe workspace default.'}
      </p>
      <p className="mt-1 text-[11px] leading-5 text-white/35">
        Click +, then paste the full local path into the field for backend
        validation.
      </p>
    </div>
  );
}
