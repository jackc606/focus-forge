# Hosted Assistant (0.4.4) — design

Focus Forge 0.4.3 ships the Assistant as bring-your-own-key. 0.4.4 adds a
**hosted mode**: Focus Forge pays for a small monthly allotment per user, so a
modder who has never heard of an API key can open the Assistant tab, sign in
with Discord, and build a branch.

## Shape

```
Focus Forge app ──(Bearer ffa_… token)──► focusforge-assistant Worker ──(OpenRouter key)──► OpenRouter/Meta
                                            │  D1: users, usage, daily
                                            └─ Discord OAuth for sign-in
```

The app already speaks OpenAI-compatible chat completions to any base URL. Hosted
mode is the same loop pointed at the Worker's `/v1`, with a token instead of a
provider key. The Worker is the only place the OpenRouter key exists.

## Why these choices (see the 2026-09-05 discussion)

- **The quota is worthless outside Focus Forge.** The Worker only accepts our
  chat-completion shape for an allow-listed model, so a farmed token cannot be
  used for anything but building HOI4 focus trees. That removes the incentive to
  multi-account far better than any identity check.
- **Cap the wallet, not the user.** A hard global daily spend cap in D1 is the
  control that protects the money. Per-user limits are about fairness.
- **Refreshing monthly quota** (default $0.50) rather than a lump sum: cannot be
  banked, so extra accounts only help someone who exhausts theirs every month.
- **Discord sign-in with an account-age gate** (≥ 30 days): every HOI4 modder has
  Discord, accounts carry a creation date (snowflake), and aged accounts are not
  worth farming for fifty cents.
- **Measured cost**: a 15-focus branch costs 1–3 cents at 74–90 % cache hits, so
  $0.50 ≈ 15–40 branches a month.

## API contract (Worker)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Landing page: "Sign in with Discord to get your Focus Forge token" |
| GET | `/auth/discord/start` | 302 to Discord OAuth (`identify` scope), HMAC state cookie |
| GET | `/auth/discord/callback` | Exchange code, enforce account age, upsert user, mint token, show it ONCE with paste instructions |
| POST | `/v1/chat/completions` | OpenAI-compatible, non-streaming. Bearer `ffa_…`. Enforces model allow-list, monthly quota, global daily cap, per-user rate limit. Forwards to OpenRouter. Debits by real usage incl. cache-read pricing. |
| GET | `/v1/me` | `{discord_username, used_cents, limit_cents, period, reset_at, requests_today}` |

Every `/v1/chat/completions` response carries `X-FF-Used-Cents`,
`X-FF-Limit-Cents`, `X-FF-Reset` (ISO date). Errors use the OpenAI envelope
`{"error": {"message": …, "code": …}}`:

| Status | code | When |
|---|---|---|
| 401 | `bad_token` | missing/unknown/disabled token |
| 402 | `allotment_used` | user's monthly allotment spent (message names the reset date) |
| 429 | `rate_limited` | > 4 requests / 10 s or > 400 / day per user |
| 503 | `budget_exhausted` | global daily cap reached ("try again tomorrow") |
| 400 | `unsupported` | `stream: true`, disallowed model, oversized body |

## Data (D1)

- `users(id, discord_id UNIQUE, discord_username, discord_created_at, token_hash UNIQUE, limit_cents DEFAULT 50, used_microcents DEFAULT 0, period TEXT 'YYYY-MM', created_at, last_seen_at, disabled DEFAULT 0)`
- `usage(id, user_id, ts, model, prompt_tokens, cached_tokens, completion_tokens, cost_microcents, session_id)`
- `daily(day TEXT PK, spend_microcents)`

Tokens are shown once and stored hashed (SHA-256). Cost is tracked in
micro-cents so cache reads at $0.002/M don't round to zero.

## App side

Settings dialog gains a provider choice: **Focus Forge hosted (free allotment)**
or **My own key**. Hosted: a "Sign in with Discord" button opens the browser at
`/auth/discord/start`; the user pastes the token; base URL and model are fixed by
the relay. The panel header shows the remaining allotment from the `X-FF-*`
headers. 402/429/503 map to plain-language messages that also suggest switching
to your own key.

## Not in 0.4.4

Streaming, paid top-ups, an admin UI (limits are env vars; a token-gated
`/admin/grant` covers the odd manual bump), custom domain (`assistant.focusforgemod.com`
can be attached later without an app change because the base URL is a constant).
