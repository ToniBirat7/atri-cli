'use client';

interface EmptyStateProps {
  onSuggestion: (text: string) => void;
  accessSummary: string;
}

const suggestions = [
  {
    text: 'Summarize the project architecture and the major runtime services.',
    label: 'Architecture overview',
  },
  {
    text: 'Draft a practical plan to improve build speed and startup reliability.',
    label: 'Performance plan',
  },
  {
    text: 'Review the frontend and suggest a cleaner, more modern chat layout.',
    label: 'UI review',
  },
  {
    text: 'Explain how streaming events move from the backend to the browser.',
    label: 'Streaming flow',
  },
];

export default function EmptyState({
  onSuggestion,
  accessSummary,
}: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4">
      <div className="mb-6 text-center">
        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-bg-tertiary border border-border flex items-center justify-center">
          <svg
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth="1.5"
          >
            <path d="M12 2l7 4v8l-7 4-7-4V6l7-4z" />
            <path d="M9 12l2 2 4-5" />
          </svg>
        </div>
        <h1 className="text-2xl font-semibold text-text-primary mb-1">
          Assistant Workspace
        </h1>
        <p className="text-sm text-text-muted">
          Start with a prompt, or use one of the examples below.
        </p>
      </div>

      <div className="max-w-xl mb-6 px-4 py-3 rounded-xl border border-accent/20 bg-accent/5 text-sm text-text-secondary">
        <p className="font-medium text-accent mb-1">Live streaming enabled</p>
        <p className="leading-relaxed">
          The assistant can stream responses, surface tool calls, and keep the
          UI responsive while it works.
        </p>
      </div>

      <div className="max-w-xl mb-6 px-4 py-3 rounded-xl border border-border bg-bg-secondary text-sm text-text-secondary">
        <p className="font-medium text-text-primary mb-1">Workspace access</p>
        <p className="leading-relaxed text-text-muted">{accessSummary}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
        {suggestions.map((s) => (
          <button
            key={s.label}
            onClick={() => onSuggestion(s.text)}
            className="text-left px-4 py-3 rounded-xl border border-border bg-bg-secondary hover:bg-bg-hover hover:border-accent/30 transition-all group"
          >
            <span className="text-sm text-text-primary group-hover:text-accent transition-colors line-clamp-2">
              {s.text.split('\n')[0]}
            </span>
            <span className="block text-[10px] text-text-muted mt-1">
              {s.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
