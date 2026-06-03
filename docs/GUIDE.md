# Using PromptForge

PromptForge is a platform for **managing and evaluating LLM prompts** — think "Git +
a test suite, for prompts." This guide explains what it does, the workflow, and
(most importantly) **what you provide** to get value out of it.

## The idea

If you build a feature on an LLM — a support-reply drafter, a summarizer, a SQL
explainer — you eventually hit three problems:

1. **No history.** The prompt lives in code or a notebook; nobody can answer "who
   changed it, when, and did quality drop because of it?"
2. **No regression testing.** You tweak the prompt to fix one input and silently
   break three others. There's no "run the test suite" for prompts.
3. **No record.** You don't know what each call cost, how long it took, or how
   often it failed.

PromptForge gives you versioned prompts, recorded runs (with cost/latency), and an
**eval suite** you can re-run against any prompt version to get a pass rate — so
changing a prompt becomes measurable instead of a guess.

## Core concepts

| Thing | What it is |
|---|---|
| **Prompt** | A named template with `{{variables}}`, e.g. `Reply to {{customer_message}} in a {{tone}} tone`. |
| **Version** | An immutable snapshot of a prompt's body + variables. Editing creates a *new* version; old ones never change, so every result stays reproducible. |
| **Run** | One execution of a version against concrete inputs. Records the output, token counts, cost, latency, and any error. |
| **Eval Suite** | A named collection of test cases for a kind of task (e.g. "Support Reply Quality"). |
| **Eval Case** | One test: an **input**, an **expected** criterion, and a **judge**. *You author these.* |
| **Judge** | How a case is scored: `exact`, `contains`, `regex`, or `llm_judge` (see below). |
| **Batch** | One run of a suite against one or more versions — fans out to (cases × versions) jobs and produces a result per case. |
| **Result** | Per case: passed/failed, a score, and the judge's reasoning. |

## The workflow

Using the seeded "Support Reply Drafter" as the example:

1. **Create a prompt** with variables: `Write a {{tone}} reply to: {{customer_message}}`.
2. **Iterate as versions.** v1 is basic; v2 adds a tone instruction. Both are kept.
3. **Author an eval suite + cases** — the test set you care about (next section).
4. **Run a batch** of the suite against v2 (or against v1 *and* v2 to compare).
5. **Read the pass rate.** "v2 passes 18/20; v1 passed 14/20" → v2 is better, with evidence.
6. **Iterate.** Change the prompt, re-run, watch the number move. Repeat.

The batch runs on a background worker and streams results live as each case
finishes (Server-Sent Events), so the UI fills in case-by-case.

## What you provide (this is the important part)

PromptForge doesn't invent your tests — **you bring the cases**. To get real value:

**1. Prompts.** Write the prompt body with `{{variable}}` placeholders for anything
that changes per call. Declare each variable (name + type). Example:

```
body: "You are a {{tone}} support agent. Reply to:\n\n{{customer_message}}"
variables: [{name: "tone", type: "str"}, {name: "customer_message", type: "str"}]
```

**2. Eval cases.** This is what you curate. Good cases come from inputs you actually
care about: real past examples, edge cases that have burned you, and "golden"
expected behavior. Each case is:

- **inputs** — values for the prompt's variables: `{customer_message: "where's my order?", tone: "apologetic"}`
- **expected** — the criterion: `{value: "sorry"}`
- **judge** — how to check it: `contains` (the reply must contain "sorry")

The more representative your cases, the more a pass rate actually means. 10–30
well-chosen cases per suite beats 200 random ones.

## Choosing a judge

"Correct" means different things, so there are four judges:

- **exact** — output must equal the expected string (after trimming). Use for
  deterministic answers (math, a known correct output).
- **contains** — output must contain a substring. Use for "the reply must mention
  the refund policy."
- **regex** — output must match a pattern. Use for formats (an email, a JSON shape,
  an order number).
- **llm_judge** — a separate LLM scores the output against a rubric you write, and
  passes if the score clears a threshold. Use for open-ended quality — "is this
  reply helpful, on-topic, and on-tone?" — where no single string is "right."

A suite has a default judge; any case can override it.

## Demo mode and your own key

- **Try the demo:** `POST /api/v1/demo/login` gives an instant read-only session on
  a seeded workspace — browse prompts, versions, runs, and an example eval report
  without signing up.
- **Free runs:** a demo visitor gets a few real LLM runs on the hosted key, then is
  asked to **bring your own key** (the `X-Provider-Key` header — your OpenAI or
  Anthropic key). BYOK runs are unlimited and billed to you, not us.
- **Sign up** for a full workspace where you can create prompts and run your own
  eval batches.

## Sharing results

Any prompt or eval batch can be turned into a **public, read-only link** (revocable,
optionally expiring) via `POST /api/v1/shares`. Anyone with the link sees a minimal
view — no account, no access to the rest of your workspace. Handy for showing a
teammate "here's the eval report proving v2 beats v1."

Live examples (no auth):
- Prompt: https://promptforge-api.fly.dev/api/v1/public/share/demo-prompt-support-reply
- Eval report: https://promptforge-api.fly.dev/api/v1/public/share/demo-eval-support-quality

## Try it via the API

Full interactive docs at https://promptforge-api.fly.dev/docs. A minimal end-to-end
flow (sign up → prompt → eval suite → batch) is in
[DEPLOY.md](DEPLOY.md#smoke-test) and the SSE walkthrough in the project notes.
