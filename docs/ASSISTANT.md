# Focus Forge — the built-in Assistant

The **Assistant** tab (right dock, after *LLM*) is a chat box wired straight into the
editor. You describe what you want in plain English; a hosted model builds or edits the
open project by calling the same bridge ops the MCP server exposes, in-process, and the
canvas updates as it works. Nothing else to install.

There are two ways to connect it: **sign in with Discord** (free allotment, no key) or
**bring your own key**.

## The easy way: sign in with Discord

1. Assistant tab → **Sign in to use the assistant** (or ⚙ → *Focus Forge hosted*) →
   **Sign in with Discord**. Your browser opens; approve the sign-in.
2. The page shows a token (`ffa_…`) **once**. Copy it.
3. Back in Focus Forge, paste it into **Paste your token**, click **Test connection**
   (it reports who you're signed in as and what's left this month), then **Save**.

**What the allotment is.** Focus Forge pays for a small amount of model use per person
each month — $0.50 by default, which is roughly 15–40 branches. It refreshes on the 1st
and doesn't carry over. The tab header shows it: `… · $0.08 of $0.50 used · resets Oct 1`.
The model is fixed (the header says *Focus Forge hosted model*); the relay only accepts
Focus Forge's own requests, so the token is useless anywhere else. Discord accounts
younger than 30 days can't sign in.

**Privacy.** Prompts and the parts of your mod the assistant reads are sent to Meta
through OpenRouter; the contributor tier may use them for training. The token is stored
on this computer only.

**When it runs out.** The assistant stops with a message naming the reset date and an
**Open settings** button under it. Either wait for the reset or switch to *My own key*
in settings — your conversation is kept. Two other messages you may see: a rate limit
(more than 4 requests in 10 seconds — just wait a moment) and "the service's daily budget
is spent — try again tomorrow", which is Focus Forge's global cap, not yours.

## My own key

### 1. Get a key

The default provider is [OpenRouter](https://openrouter.ai), which fronts many models
behind one OpenAI-compatible endpoint.

1. Create an account at openrouter.ai and add a few dollars of credit.
2. Open **Keys** (openrouter.ai/keys) → *Create key* → copy it (it starts with `sk-or-`).

Any other OpenAI-compatible `/chat/completions` endpoint works too (a local server, a
different host) — change *Base URL* in the settings.

### 2. Paste it into Focus Forge

Assistant tab → ⚙ → **My own key**:

| Field | What to put |
| --- | --- |
| Base URL | `https://openrouter.ai/api/v1` (default) |
| API key | the key you copied |
| Model | `meta/muse-spark-1.3-contributor` (default) — or type any model id |
| Max tool rounds | how many tool calls one request may make before pausing (80) |
| Temperature | 0.3 is a good default for structured editing |

**Test connection** sends a one-token request and reports OK or the provider's error.
**Save** stores the settings on this computer only. Switching between *hosted* and *my
own key* keeps both sets of values, so you can flip back any time.

## Ask

Type a request and press **Send** (or Ctrl+Enter):

- "Add a 4-focus economy branch under the political opening, with a mutually exclusive
  market/state fork."
- "Every focus in the MEX_ex_ prefix is missing ai_will_do — add sensible weights."
- "Validate the tree and fix the errors."

Each tool call shows as a one-line card (`▸ add_focus MEX_x ✓`); click it to see the
arguments and the result. When the model calls `screenshot`, the PNG appears inline so you
can check the layout. **Stop** halts the run at the next step. **New chat** forgets the
conversation.

## What it can and can't do

- It can do everything the bridge can: read and write focuses, ideas, events, decisions,
  project settings; validate; smoke-check the export; batch a whole feature atomically.
- **Deletes, saves and exports always ask you first.** Decline and the model is told not
  to retry.
- It cannot open a different project file — you do that from the toolbar.
- It cannot see images. `screenshot` is for you.
- Everything it changes is unsaved until you save, and every batch is one undo step
  (Ctrl+Z).

## Cost

With your own key the header shows the running token count and an estimate
(`12.4k in · 2.1k out · ~$0.002`). On the default model a typical 10-focus branch — a few
reads, one batch, a validate and a screenshot — comes to roughly **2 cents**. Long sessions
on big trees cost more because the whole conversation is re-sent on every step; *New chat*
resets that. Models the app doesn't know the price of show `~$?`.

In hosted mode the header shows the token count and the relay's own figure for your
allotment instead of an estimate.

## Privacy

Prompts you type and the parts of your mod the model reads (focus lists, rewards, the
project summary) are sent to the provider — Meta via OpenRouter in hosted mode, whatever
you configured with your own key — only when you send a message. The key or token is
stored on this computer (QSettings) and never leaves it except as the `Authorization`
header to that provider. The existing MCP bridge and the LLM tab are unchanged and remain
offline.
