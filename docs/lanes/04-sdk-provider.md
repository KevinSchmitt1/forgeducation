# Lane 4 — SDK-as-provider / "no API key" (DESIGN DOC ONLY)

**Branch:** `docs/sdk-provider-design` · **Type:** design doc, no code · **Depends on:** none
**Status:** not started.
**Process:** see "Lane workflow" in root `CLAUDE.md`. Read `forged/llm.py` first, and use
the `claude-api` skill for accurate Anthropic SDK / structured-output details.

## The question to design an answer for (Kevin's framing)
Can the program run **without an OpenAI API key** — instead going through an agent SDK / existing
subscription, specifically **Claude Code SDK** or **GitHub Copilot**?

## Ground truth
- `forged/llm.py` has a `Provider` enum (OpenAI + Ollama). Both speak the **OpenAI chat-completions
  wire format**, so one `LLMClient.complete(system_prompt, user_prompt, response_format=...) -> content`
  covers both — only base_url + key differ.
- **Ollama is a non-starter on this machine** (it crashed the whole PC — do not propose local Ollama).
- **HARD CONSTRAINT — structured output.** Student + Reviewer graders request
  `response_format={"type": "json_schema", ...}`; malformed critic JSON burns paid runs (CLAUDE.md).
  Any new provider path MUST preserve schema-constrained JSON, or the design must say exactly how
  graders degrade safely without it. **This is the make-or-break of the whole idea.**

## Deliverable
`docs/architecture/24-sdk-as-provider.md` (next number after 23). Per option — Claude Code SDK,
GitHub Copilot, plus Anthropic API direct as a baseline:
1. **How it maps onto `LLMClient.complete`'s contract** — not OpenAI-wire (Claude Code SDK is an
   agentic subprocess; Copilot is its own protocol). Describe the adapter each needs.
2. **Does structured `json_schema` output survive?** If not, the fallback and its reliability cost.
3. **Auth / cost / consent model** — "no API key" means "uses my subscription"; ToS implications.
4. **Verdict per option**: feasible / feasible-with-caveats / not worth it, with a recommendation.

## Done means
A clear per-option verdict that answers the structured-output question head-on. Open a PR.
