"use client";

interface EmptyStateProps {
  onSuggestion: (text: string) => void;
}

const suggestions = [
  {
    text: "मलाई घरेलु हिंसाको उजुरी दिने प्रक्रिया बारेमा जानकारी दिनुहोस्।\n\n<context>\n[यहाँ सम्बन्धित कानूनी सामग्री पेस्ट गर्नुहोस्]\n</context>",
    label: "Domestic violence complaint process",
  },
  {
    text: "What is the process for filing a case in the District Court?\n\n<context>\n[Paste relevant legal text here]\n</context>",
    label: "District Court filing process",
  },
  {
    text: "मुद्दाको म्याद तामेली प्रक्रिया के हो?\n\n<context>\n[यहाँ सम्बन्धित कानूनी सामग्री पेस्ट गर्नुहोस्]\n</context>",
    label: "Case summons procedure",
  },
  {
    text: "Explain the mediation process before a civil case goes to trial.\n\n<context>\n[Paste relevant legal text here]\n</context>",
    label: "Pre-trial mediation",
  },
];

export default function EmptyState({ onSuggestion }: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-4">
      <div className="mb-6 text-center">
        <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] flex items-center justify-center">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="1.5">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <h1 className="text-2xl font-semibold text-[var(--color-text-primary)] mb-1">
          Kanoon Box
        </h1>
        <p className="text-sm text-[var(--color-text-muted)]">
          UNDP A2J Legal Information Assistant — Demo
        </p>
      </div>

      <div className="max-w-xl mb-6 px-4 py-3 rounded-xl border border-[var(--color-accent)]/20 bg-[var(--color-accent)]/5 text-sm text-[var(--color-text-secondary)]">
        <p className="font-medium text-[var(--color-accent)] mb-1">Demo Mode — No RAG Pipeline Connected</p>
        <p className="leading-relaxed">
          This demonstrates the Gemma 4 E2B model&apos;s ability to answer legal questions
          from provided context. Since no retrieval system is connected, please
          <strong className="text-[var(--color-text-primary)]"> paste the relevant legal text </strong>
          along with your question using this format:
        </p>
        <pre className="mt-2 text-xs bg-[var(--color-bg-tertiary)] p-2.5 rounded-lg overflow-x-auto text-[var(--color-text-muted)]">
{`Your question here

<context>
[Paste relevant legal text / KB content here]
</context>`}
        </pre>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
        {suggestions.map((s) => (
          <button
            key={s.label}
            onClick={() => onSuggestion(s.text)}
            className="text-left px-4 py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-hover)] hover:border-[var(--color-accent)]/30 transition-all group"
          >
            <span className="text-sm text-[var(--color-text-primary)] group-hover:text-[var(--color-accent)] transition-colors line-clamp-2">
              {s.text.split("\n")[0]}
            </span>
            <span className="block text-[10px] text-[var(--color-text-muted)] mt-1">
              {s.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
