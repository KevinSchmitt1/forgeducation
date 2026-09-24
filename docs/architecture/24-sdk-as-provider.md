# 24 — SDK as provider: can forgeducation run without an OpenAI API key?

**Status:** designed 2026-09-24 · **DESIGN ONLY — nothing built.** Lane 4 (`docs/lanes/04-sdk-provider.md`).
**Question (Kevin's framing):** Can the program run **without an OpenAI API key** — going instead
through an agent SDK / an existing subscription, specifically **Claude Code SDK** or **GitHub
Copilot**?
**Verification rung:** review (no runtime; this is a decision doc).
**Reference:** `forged/llm.py` (the provider seam) and the bundled `claude-api` skill (authoritative
for the Anthropic SDK surface used below).

---

## The one constraint that decides everything

Before any option, restate the make-or-break from the brief and `CLAUDE.md`:

> **Student + Reviewer graders request `response_format={"type": "json_schema", ...}`. Malformed
> critic JSON burns paid runs.** Any new provider path MUST preserve schema-constrained JSON, or the
> design must say exactly how the graders degrade safely without it.

This is not a nice-to-have. The 2026-08-13 work (docs 15, 20) moved the graders *to* schema-constrained
output precisely because "prose plus a final fenced JSON block" was losing paid runs to unparseable
critic output. Any provider that cannot constrain output to a JSON schema is not a drop-in for the
grader stages — it is a regression to the exact failure the graders were hardened against.

So the question "can we swap the provider" is really **two** questions, and they have different answers:

1. Can we serve the **free-form** stages (code_author, reviser, planner — markdown / notebook-JSON /
   prose) through a different provider? *Easier.*
2. Can we serve the **schema-constrained grader** stages (student, reviewer) through it **without
   losing `json_schema`**? *This is the gate.*

An option that only passes (1) does not answer Kevin's question — it leaves an OpenAI key required for
the graders, so the program still can't run "without an API key."

---

## The seam we're plugging into

`forged/llm.py` today:

```python
class LLMClient:
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        trace_context: LLMTraceContext | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str: ...
```

- One method, one string in / one string out, plus an optional `response_format` dict.
- Both existing providers (`Provider.OPENAI`, `Provider.OLLAMA`) speak the **OpenAI
  chat-completions wire format**, so `complete()` builds one `messages=[{system},{user}]` payload and
  `_connection_kwargs()` only swaps `base_url` + `api_key`. Adding an OpenAI-compatible endpoint is a
  config change, not code.
- `response_format` is passed straight through to `client.chat.completions.create(...)` and is
  **only** sent for the non-Ollama path (Ollama omits it and the parsers fall back to lenient prose).
- Usage accounting reads `response.usage` (`prompt_tokens` / `completion_tokens` / cached / reasoning).

Any non-OpenAI-wire provider needs an **adapter**: a `complete()` implementation that (a) translates
system+user into the provider's request shape, (b) translates `response_format`'s `json_schema` into
the provider's structured-output mechanism *or* declares how the graders degrade, and (c) maps the
provider's usage fields back onto the ledger. The adapter is the whole cost of each option below.

> **Ollama is not on the table.** It is OpenAI-wire already (so it needs no adapter), but it crashed
> this machine — see `CLAUDE.md` and the lane brief. It is mentioned only to note that "another
> provider" has already been tried and rejected for a *non-schema* reason.

The three options the brief asks for, cheapest-adapter first:

| Option | Wire shape | `json_schema` survives? | "No API key"? |
|---|---|---|---|
| A. Anthropic API (direct) | Messages API (near-OpenAI) | **Yes**, natively | No — still an API key |
| B. Claude Code SDK | Agentic subprocess | **No** — prompt-coerced only | **Yes** — Claude Pro/Max login |
| C. GitHub Copilot | Copilot's own protocol | No — no sanctioned schema API | Partly — Copilot login, but ToS-barred |

---

## Option A — Anthropic API, direct (the baseline)

This is not what Kevin asked for (it is an API key, just a different vendor's), but the brief asks for
it as a **baseline** — and it is the only one of the three that clears the make-or-break gate cleanly,
so it sets the bar the "no-key" options are measured against.

### How it maps onto `complete()`

The `anthropic` SDK's `client.messages.create(...)` is close to OpenAI chat-completions but not
identical — enough to need a small adapter, not a rewrite:

| Concern | OpenAI (today) | Anthropic adapter |
|---|---|---|
| System prompt | a `{"role":"system"}` message | top-level `system=` parameter |
| User turn | `{"role":"user","content":str}` | `messages=[{"role":"user","content":str}]` |
| Output cap | `max_completion_tokens` | `max_tokens` (required) |
| Response text | `resp.choices[0].message.content` | first `text` block in `resp.content` (a list) |
| Usage | `prompt_tokens` / `completion_tokens` | `input_tokens` / `output_tokens` (+ `cache_read_input_tokens`) |

None of this is exotic — it's a `Provider.ANTHROPIC` branch in `complete()` and `_connection_kwargs()`,
mirroring the existing Ollama branch. Model IDs come from config (`claude-haiku-4-5` for the cheap
grader/planner stages, `claude-opus-4-8` or `claude-sonnet-5` for author/reviser), which the
per-stage `config/pipeline.*.yaml` resolution already supports with no schema change.

### Does `json_schema` survive? — **Yes, natively.**

The grader's `response_format={"type":"json_schema","json_schema":{"name":...,"schema":S,"strict":true}}`
maps onto Anthropic's structured outputs:

```python
client.messages.create(
    model=..., max_tokens=...,
    system=system_prompt,
    messages=[{"role": "user", "content": user_prompt}],
    output_config={"format": {"type": "json_schema", "schema": S}},
)
```

`output_config.format` constrains the response to the schema, guaranteed — the same contract the
graders rely on today. The adapter's structured-output translation is: unwrap OpenAI's nested
`json_schema.schema` and hand `S` to `output_config.format`. Two footnotes:

- **Schema shape is compatible.** Anthropic requires `additionalProperties:false` + all fields
  `required` for strict decoding — which the OpenAI strict schemas already satisfy. The Python SDK
  additionally strips constraints Anthropic doesn't enforce (`minLength`, `minimum`, …) and validates
  them client-side, so an over-specified grader schema won't 400.
- **Supported on the cheap tier.** Structured outputs work on Haiku 4.5 (the natural gpt-5-mini
  replacement) as well as Opus 4.8 / Sonnet 5 — so the graders don't get pushed onto an expensive
  model just to keep their schema.

This is the crucial result: **the make-or-break constraint is preserved without degradation.** The
graders stay schema-constrained; no lenient-parse fallback is needed.

### Auth / cost / consent

- **Auth:** `ANTHROPIC_API_KEY`, resolved exactly like `OPENAI_API_KEY` is today. There is also an
  `ant auth login` OAuth-profile path (a bare client picks it up with no env var) — but that profile
  is a **Claude Developer Platform** credential billed as API usage, *not* a consumer Pro/Max
  subscription. So this option does **not** deliver "no API key / use my subscription." It swaps one
  metered API vendor for another.
- **Cost:** billed per token like OpenAI. Rough mapping of the current stage tiers: gpt-5-mini →
  Haiku 4.5 ($1/$5 per MTok), gpt-5 → Opus 4.8 ($5/$25) or Sonnet 5 ($3/$15). Comparable order of
  magnitude; a real run would be needed to compare true spend.
- **Consent / ToS:** ordinary paid-API terms. No subscription-reuse gray area.

### Verdict: **feasible — recommended *if* the goal is provider portability, not key elimination.**

Small, contained adapter; the make-or-break constraint survives natively; it's the honest "second
provider" that de-risks a single-vendor dependency. But it does **not** answer "run without an API
key" — it's still a key, just Anthropic's. If provider independence is the actual want, build this. If
key-elimination is the actual want, this option doesn't deliver it and the next two are where the
question really lives.

---

## Option B — Claude Code SDK (the real "no API key" candidate)

This is the option that literally matches "use my existing subscription": the **Claude Code SDK**
(`claude-agent-sdk`) can authenticate against a **Claude Pro/Max login**, no API key. It is also the
one that **fails the make-or-break gate.**

### How it maps onto `complete()` — it doesn't, cleanly

The Claude Code SDK is **not** a chat-completions client. It is Claude Code packaged as a library: an
**agentic harness** you drive with `query(prompt, options)`, which runs a full agent loop with
built-in tools (file read/write/edit, bash, grep, web) and its own context management. Per the
`claude-api` skill, it is a *separate product* — "harness-only, you host it" — deliberately distinct
from the Messages API and its Tool Runner.

To serve a single system+user completion through it, the adapter would:

- Spin up an agentic subprocess/session per `complete()` call (the pipeline makes many of these).
- Fold `system_prompt` into the harness's system/append-system option and pass `user_prompt` as the
  query.
- Disable or ignore the built-in tools (the graders and authors don't want a filesystem agent —
  they want one text response).
- Scrape the final assistant text out of the streamed result.

That is a large, awkward adapter that fights the tool's purpose: we'd be paying for an agent loop to
get a single completion, per stage, per iteration.

### Does `json_schema` survive? — **No.**

The Claude Code SDK exposes no `output_config.format` / `response_format` equivalent — it is an
agent runtime, not a constrained-decoding endpoint. The only way to get grader JSON out of it is to
**prompt-coerce** it ("respond only with JSON matching this schema") and parse leniently. That is
exactly the "prose plus a final fenced JSON block" contract docs 15/20 removed **because it burned
paid runs on malformed critic JSON.** Adopting the SDK for the grader stages walks that regression
straight back in.

So the honest degrade story is bad for the stages that matter most: **the two grader stages are the
ones that cannot lose schema, and the SDK is precisely where schema can't be guaranteed.** A hybrid
("SDK for the free-form author/reviser, keep an API for the graders") is conceivable — but it defeats
the premise, because it still requires an OpenAI *or* Anthropic API key for the graders. There is no
"no key at all" configuration that keeps the graders safe.

### Auth / cost / consent

- **Auth:** Claude Pro/Max subscription login (the genuine "no API key" answer), or an API key.
- **Cost:** subscription-metered rather than per-token — attractive on paper for iterative offline work.
- **Consent / ToS — the decisive problem:** using a **consumer** Pro/Max subscription to
  programmatically power a *separate product's* pipeline is a subscription-reuse gray area at best.
  Consumer subscriptions are scoped to interactive Claude Code use; wiring one in as forgeducation's
  headless inference backend for unattended paid runs is not clearly permitted and should not be
  designed in without an explicit reading of current terms. This is a **STOP-and-confirm**, not an
  implementation detail.

### Verdict: **not worth it as a general provider.** Free-form-only experiment at most.

It is the only true "no API key" path, but it (a) breaks the make-or-break constraint on the exact
stages that can't afford it, (b) needs a heavy adapter that misuses an agent harness as a completion
endpoint, and (c) sits in a subscription-ToS gray zone. If someone still wants to explore it, scope it
to the **free-form author/reviser stages only**, keep a real API for the graders, and get the ToS
question answered first — but understand that this does not achieve "run without an API key," it only
shifts *some* spend onto a subscription.

---

## Option C — GitHub Copilot

### How it maps onto `complete()` — its own protocol

Copilot is not a general-purpose completions API. Its chat endpoint is an editor-integration protocol
reached with a Copilot OAuth token harvested from an IDE session; there is no public, sanctioned
"Copilot completions API" for third-party programs. An adapter would have to impersonate an editor
client against an unsupported endpoint.

### Does `json_schema` survive? — **No.**

There is no sanctioned structured-output / `json_schema` mechanism exposed through the Copilot path.
Same failure mode as Option B for the graders, with less upside: prompt-coerce + lenient parse, i.e.
the regression docs 15/20 removed.

### Auth / cost / consent

- **Auth:** Copilot subscription OAuth token — nominally "no API key."
- **Consent / ToS — barred.** Using Copilot credentials to drive a non-editor, headless product
  pipeline is outside Copilot's terms of service. This isn't a gray area like Option B; it's a
  straightforward ToS violation and a fragile dependency on a reverse-engineered endpoint.

### Verdict: **not worth it.** Own protocol, no structured output, clear ToS violation, brittle.
Don't build.

---

## Recommendation

**Answer to Kevin's question — "can it run without an OpenAI API key?":**

- **Without *any* metered API key at all?** Only the **Claude Code SDK (Option B)** delivers that, and
  it fails the make-or-break structured-output constraint on the grader stages and sits in a
  subscription-ToS gray zone. So the honest answer is **no — not without either regressing the graders
  or resolving a ToS question first.** GitHub Copilot (Option C) is a firm no on ToS grounds.

- **Without an *OpenAI-specific* key — i.e. provider portability?** **Yes, via the Anthropic API
  (Option A).** It's the only option that preserves `json_schema` natively, and the adapter is small
  and contained. But it's still a paid API key, just Anthropic's.

**What to build, if anything:** if the real driver is *not being locked to one vendor*, implement
**Option A** — a `Provider.ANTHROPIC` branch in `llm.py` that maps `complete()` onto
`messages.create(..., output_config={"format":{"type":"json_schema","schema":S}})`, plus the usage
mapping and a `config/pipeline.*.yaml` model entry. That keeps the grader guarantee intact and gives
forgeducation a second, first-class provider.

If the real driver is *literally eliminating the key / riding a Claude subscription*, the finding is
that **no option does that while keeping the graders schema-safe.** The path forward would be a
scoped, free-form-only Claude Code SDK experiment (author/reviser stages), an OpenAI *or* Anthropic
API retained for the graders, and the subscription-ToS question answered explicitly before any code —
and that path should be opened only if Kevin decides the partial win is worth it, because it does not
achieve "no API key."

**Net:** the structured-output constraint is the whole ballgame. It rules Copilot out entirely, makes
the Claude Code SDK a graders-excluded special case, and leaves the direct Anthropic API as the only
clean swap — which trades vendors, not the requirement for a key.
