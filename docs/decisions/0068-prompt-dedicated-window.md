# 0068 — Prompt rendered as a dedicated Window, not a BeforeInput processor

**Status:** Accepted
**Date:** 2026-05-13

## Context

The `> ` prompt prefix in the input pane was rendered via
`BeforeInput("> ")` attached to the BufferControl's
`input_processors`. That placed the prefix inside the BufferControl's
scrollable content. When typed text exceeded the visible input
width, prompt_toolkit's horizontal scroll pushed the prefix off the
left edge, and the scroll did not reliably reset to 0 after the
buffer was cleared — leaving the prompt permanently hidden.

## Decision

The prompt is a fixed-width 2-col `FormattedTextControl` sibling
`Window` in the input row's `VSplit`, alongside the existing
`input_window` and `clock_window`:

```python
VSplit([prompt_window, input_window, clock_window])
```

It lives outside the BufferControl's render domain, so horizontal
scrolling of the buffer can never affect it.

## Consequences

- The prompt is always visible regardless of buffer width or scroll
  position.
- Mirrors the clock pattern (fixed-width, non-focusable sibling)
  already established in [ADR 0067](0067-remove-input-pane-buttons.md).
- Visible input width is unchanged — the 2 columns were already
  consumed by the `BeforeInput` prefix.

## Rejected alternative

Keep `BeforeInput("> ")` and force `horizontal_scroll = 0` on every
buffer text change. Rejected: reaches into prompt_toolkit internals,
fragile across versions, and treats the symptom rather than the
structural cause.
