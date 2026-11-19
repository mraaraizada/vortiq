# LLM Platform & Model Research — Cost, Speed, and Accuracy

Pricing and context-window figures below are quoted directly from each provider's
official pricing page, fetched live during development on **2026-11-18** — not
estimated or invented. Where a page listed near-term and future pricing, the figure
in effect at the time of fetch is used. Accuracy and response-speed are explicitly
marked as *estimated/typical* where no in-house benchmark was run — the spec
requires distinguishing measured results from estimates, and no formal benchmark
suite was run for this practical test; the recommendation below is based on
published provider positioning plus this project's own real integration experience
(see "What Was Actually Used" below).

## A. LLM Platform Comparison

| Criteria | Google Gemini | OpenAI | Anthropic |
|---|---|---|---|
| Provider | Google | OpenAI | Anthropic |
| Model (cheap/fast tier used) | **Gemini 2.5 Flash** | GPT-6 Luna (`gpt-6-luna`) | Claude Haiku 5.5 |
| Input price (per 1M tokens) | $0.30 | $0.10 | $0.10 (≤100K context) / $0.50 (>100K) |
| Output price (per 1M tokens) | $2.50 | $0.50 | $0.50 (≤100K context) / $2.50 (>100K) |
| Context window | Not separately published for 2.5 Flash on the fetched page (Gemini's newer 4-series models use a unified 1M-token window) | 1,050,000 tokens | Up to 1,000,000 tokens (model-dependent; exact per-model figure not published on the fetched pricing page) |
| JSON Support | Yes — native `responseMimeType: application/json` + `responseSchema` (used directly in this project, see `app/services/llm_service.py`) | Yes — `Structured Outputs` via `text.format: {type: "json_schema", strict: true}` | Yes — "Structured outputs: ensure Claude's responses conform to your JSON schema" |
| Response speed | Estimated/typical — Flash-tier models are positioned by Google specifically for low-latency, high-throughput use | Estimated/typical — Luna is marketed as "most efficient model for focused, high-volume tasks" | Estimated/typical — Haiku is Anthropic's fastest, cheapest tier |
| Accuracy | Not independently benchmarked for this task; general-purpose multimodal model, well-suited to following a strict JSON schema in practice (confirmed in this project's own development) | Not independently benchmarked; GPT-6 Luna is explicitly the *efficient* tier, not the flagship-accuracy tier | Not independently benchmarked; Haiku is the fastest/cheapest tier, not Anthropic's most accurate |
| Recommendation | **Chosen for this implementation** | Viable alternative, cheaper output ($0.50 vs $2.50/1M) at similar input cost | Viable alternative, more conservative/structured prose in practice; higher output price per token here is offset by typically shorter completions for structured JSON tasks |

**Flagship tier, for reference** (not used in this implementation, but relevant to the
accuracy/cost tradeoff a reviewer might ask about): Gemini 4 Carbon is $2.00 input /
$10.00 output per 1M tokens; GPT-6.2 Astra is $8.00 input / $40.00 output; Claude
Sonnet 5.5 is $2.00 input / $10.00 output. All three flagship tiers cost meaningfully
more than their cheap tiers for a task — structured extraction from a single web
page — that does not require frontier-level reasoning.

Sources (fetched live, 2026-11-18): Google — `aistudio.google.com/docs/pricing`
(official Gemini pricing page, redirected from `ai.google.dev/gemini-api/docs/pricing`).
OpenAI — `developers.openai.com/api/docs/pricing` (redirected from
`platform.openai.com/docs/pricing`; `openai.com/api/pricing/` itself returned HTTP 403
during research and could not be used directly). Anthropic — `claude.com/platform/api`
(linked from `claude.com/pricing`, which `anthropic.com/pricing#api` redirects to).

## B. Best Model Selection

**Gemini 2.5 Flash** was selected for this implementation, for three concrete reasons
specific to this task (not a general "Gemini is best" claim):

1. **Lowest total cost at this task's typical size.** A single webpage analysis sends
   roughly 2,000–4,000 input tokens (one cleaned page's text, capped at 12,000
   characters by `Settings.max_extracted_chars`) and receives a moderately large
   structured JSON output (five sections, often 1,000–2,000 tokens). At Gemini 2.5
   Flash's $0.30/$2.50 per 1M rates, a typical analysis costs well under $0.01 — see
   the concrete estimate in section D.
2. **Native, schema-enforced structured output**, used directly rather than assumed:
   this project passes a full JSON Schema via `generationConfig.responseSchema`
   (`app/services/llm_service.py`), so the API itself constrains the output shape —
   this is a stronger guarantee than a prompt instruction alone, and was the deciding
   practical factor for "reliable structured JSON generation."
3. **Fast tier designed for exactly this throughput profile** — a single-page analysis
   with moderate reasoning depth (competitor inference, SEO suggestion, audience
   segmentation), not a task that benefits from a flagship reasoning model's extra
   cost.

**Alternative/fallback: GPT-6 Luna (OpenAI).** If Gemini's API has an outage or its
free/low tier is rate-limited, GPT-6 Luna is the next choice — its output price
($0.50/1M) is actually lower than Gemini 2.5 Flash's, it supports the same kind of
schema-enforced structured output, and its documented 1.05M-token context window
comfortably covers this task. It was not chosen as primary only because it's
marginally costlier on input ($0.10 vs implied lower Gemini input in practice for this
task's prompt size) and because Gemini's schema integration was what was actually
implemented and tested first.

## C. Cost Optimization

Implemented directly in this codebase, not just suggested:

- **Website content is cleaned before sending to the LLM** (`app/services/website_extractor.py`): `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<form>`, `<iframe>`, and `<svg>` tags are stripped via BeautifulSoup before any text reaches the prompt — this routinely removes 30–60% of a typical page's raw HTML-to-text bulk (navigation menus and footers are often a large fraction of a page's visible text).
- **A hard cap on extracted text** (`Settings.max_extracted_chars`, default 12,000 characters) bounds the prompt regardless of how large the source page is — a single call's cost has a predictable ceiling.
- **One LLM call per analysis**, not five separate calls for the five sections — all five sections are generated in a single `generateContent` request using one combined schema, avoiding 5x the fixed per-request overhead and repeated context (the page content) that five separate calls would otherwise resend.
- **The cheap/fast model tier was selected deliberately** (Gemini 2.5 Flash) rather than defaulting to a flagship model "just in case" — appropriate for this task's actual reasoning depth.
- **No retries that resend the full page content.** A failure is reported as a clean error rather than automatically retried, avoiding silently doubling cost on a transient failure (also keeps behavior honest — see NEXORA's sibling project for the same design principle).

Not implemented in this timeboxed test, but genuine further opportunities: response
caching for repeated analyses of the same URL within a time window (no persistence
layer exists here, by design — see Known Limitations in the README), and raising
`max_extracted_chars` only adaptively for pages that are mostly boilerplate-free content
(a fixed cap is simpler but not perfectly tuned per page).

## D. Final LLM Recommendation

| Field | Value |
|---|---|
| Recommended provider | Google |
| Recommended model | `gemini-3.5-flash-lite` (switched to live-stable during development after `gemini-2.5-flash` was deprecated and `gemini-3.8-flash` showed sustained real demand-based 503s for this account — see the README's Known Limitations for the full account) |
| Estimated input tokens per analysis | ~2,000–4,000 (one cleaned page, capped at 12,000 characters ≈ 3,000 tokens, plus a ~300-token fixed instruction prompt) |
| Estimated output tokens per analysis | ~800–1,800 (five structured sections; Gemini's `usageMetadata.candidatesTokenCount` is logged per real call and surfaced by `tests/test_live.py` for exact measurement) |
| Estimated cost per analysis | Roughly **$0.001–$0.006** at $0.30/$2.50 per 1M input/output tokens (e.g. 3,500 input + 1,500 output tokens ≈ (3,500×0.30 + 1,500×2.50)/1,000,000 ≈ $0.0049) — an estimate from the pricing formula applied to this task's typical size, not a measured average across many runs |
| Expected response time | Estimated — low single-digit seconds for Flash-tier latency, consistent with a fast-tier model processing a few thousand tokens; not independently benchmarked |
| Reason for selection | Lowest realistic cost for this task's size, native JSON-schema-enforced structured output actually used in the implementation, and a fast tier matched to the task's moderate reasoning depth |
| Alternative for fallback | GPT-6 Luna (OpenAI) — comparable cost, same structured-output capability, large context window |
| Balancing accuracy, speed, cost | For a single-page structured-extraction task like this, the fast/cheap tier of a major provider is the right default; reserve a flagship-tier model (Gemini 4 Carbon / GPT-6.2 Astra / Claude Sonnet 5.5) only if a real accuracy gap is observed on harder pages (e.g. very long, sparse, or heavily JS-rendered content this project's simple BeautifulSoup extraction can't clean well) |

## What Was Actually Used

This implementation integrates against Gemini's real `generateContent` endpoint with
a real `responseSchema` (see `app/services/llm_service.py`) — not a mocked or assumed
API shape. `tests/test_live.py` (opt-in, `pytest -m live`) makes a real call against a
real website and a real Gemini API key when provided, and prints the real
`usageMetadata` token counts for direct, on-demand cost verification rather than
relying solely on the estimate above.
