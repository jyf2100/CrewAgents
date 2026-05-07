/**
 * TagInput — interactive tag input with autocomplete suggestions.
 *
 * Supports Enter to confirm, Escape to close, click-outside to close,
 * and click x to remove selected tags.
 */

import { useState, useRef, useEffect, useCallback } from "react";

interface TagInputProps {
  value: string[];
  onChange: (v: string[]) => void;
  suggestions: string[];
  placeholder?: string;
}

export function TagInput({ value, onChange, suggestions, placeholder }: TagInputProps) {
  const [input, setInput] = useState("");
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);

  const filtered = suggestions.filter(
    (s) =>
      s.toLowerCase().includes(input.toLowerCase()) &&
      !value.includes(s)
  );

  const addTag = useCallback(
    (tag: string) => {
      const normalized = tag.trim().toLowerCase();
      if (!normalized || value.includes(normalized)) return;
      onChange([...value, normalized]);
      setInput("");
      setOpen(false);
      setHighlightIndex(-1);
    },
    [value, onChange]
  );

  const removeTag = useCallback(
    (tag: string) => {
      onChange(value.filter((t) => t !== tag));
    },
    [value, onChange]
  );

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
      setHighlightIndex(-1);
      return;
    }

    if (e.key === "Enter") {
      e.preventDefault();
      if (highlightIndex >= 0 && highlightIndex < filtered.length) {
        addTag(filtered[highlightIndex]);
      } else if (input.trim()) {
        addTag(input.trim());
      }
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlightIndex((prev) =>
        prev < filtered.length - 1 ? prev + 1 : prev
      );
      return;
    }

    if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((prev) => (prev > 0 ? prev - 1 : 0));
      return;
    }
  }

  const activeDescendantId =
    open && highlightIndex >= 0 && highlightIndex < filtered.length
      ? `tag-input-option-${filtered[highlightIndex]}`
      : undefined;

  return (
    <div
      ref={containerRef}
      className="relative"
      role="combobox"
      aria-expanded={open && filtered.length > 0}
      aria-label={placeholder || "Tag input"}
      aria-activedescendant={activeDescendantId}
    >
      {/* Selected tags */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {value.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/30"
            >
              {tag}
              <button
                type="button"
                onClick={() => removeTag(tag)}
                className="hover:text-accent-pink text-[10px] leading-none"
                aria-label={`Remove ${tag}`}
              >
                x
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input */}
      <input
        type="text"
        value={input}
        onChange={(e) => {
          setInput(e.target.value);
          setOpen(true);
          setHighlightIndex(-1);
        }}
        onFocus={() => {
          if (filtered.length > 0) setOpen(true);
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || "Type to search tags..."}
        className="w-full h-8 px-3 text-xs border border-border rounded-lg bg-background text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan"
        aria-autocomplete="list"
        aria-controls="tag-input-listbox"
      />

      {/* Dropdown */}
      {open && filtered.length > 0 && (
        <div
          id="tag-input-listbox"
          role="listbox"
          className="absolute z-10 mt-1 w-full max-h-40 overflow-y-auto rounded-lg border border-border bg-surface shadow-lg"
        >
          {filtered.map((tag, idx) => (
            <button
              key={tag}
              id={`tag-input-option-${tag}`}
              type="button"
              role="option"
              aria-selected={idx === highlightIndex}
              onClick={() => addTag(tag)}
              className={`
                w-full text-left px-3 py-1.5 text-xs transition-colors
                ${
                  idx === highlightIndex
                    ? "bg-accent-cyan/10 text-accent-cyan"
                    : "text-text-primary hover:bg-surface/80"
                }
              `}
            >
              {tag}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
