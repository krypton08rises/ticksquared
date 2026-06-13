# tick-tick — modular daily scheduler

A Telegram bot that, every morning, asks how your day looks, builds a modular
hour-by-hour plan from your TickTick task lists, lets you reshuffle each slot
with a tap, and syncs the confirmed plan back to TickTick as scheduled tasks.

## How it works

```
 06:30  ──► morning question:  Work (home) / Work (office) / Day off
              │
              ▼
        builds plan from config.yaml templates, fills focus slots
        with incomplete tasks pulled from your TickTick lists
              │
              ▼
        sends you the plan + per-slot 🔄 buttons + ✅ Confirm
              │
        you reshuffle, then Confirm ──► tasks written to TickTick with times
```

- **No cron needed.** A persistent process schedules the morning ping itself.
- **One-time login.** TickTick OAuth is done once; tokens refresh silently.
- **Edit anytime.** All your subjects/priorities live in `config.yaml`.

## Files

| File | Role |
|------|------|
| `config.yaml`     | Your schedule templates, categories, priorities — **edit this** |
| `main.py`         | Entry point / always-on bot |
| `telegram_bot.py` | Telegram messages, buttons, sync-back |
| `scheduler.py`    | Builds the day plan, fills slots |
| `ticktick.py`     | TickTick API client + token refresh |
| `auth.py`         | One-time OAuth login |
| `setup_lists.py`  | One-shot: create + seed your TickTick Lists |
| `state.py`        | Per-day JSON state |
| `history.py`      | Append-only outcome log (`state/history.jsonl`) — recommender fuel |
| `recommend.py`    | The scoring seam — swap this one file for a learned model later |

## Daily loop

- **Morning** (`morning_trigger`): plan the day (see flow above).
- **Evening** (`evening_trigger`, default 23:00): review ping lists today's
  focus slots; mark each ✅ done / ⏭️ didn't-get-to / ❌ drop, then Submit.
  - ✅ done → completed in TickTick + logged
  - ⏭️ skip → logged; **floats to the top of tomorrow's candidates**
  - ❌ drop → logged; sinks to the bottom of future candidates
- Trigger either manually any time: `/plan` and `/review` in the chat.

### Quick capture: `/add`
Drop a task into any list without leaving Telegram.
- `/add` → tap a category (📚 Reading · 🗂 Projects · 📖 Study · 🧹 Admin ·
  💼 Work · ⚡ Quick) → for Projects pick the sub-project → send the text. Done.
- `/add buy milk` → one-shot straight into the **Inbox**.
- 📚 **Reading** items keep any link you paste; on Confirm the morning reading
  slot stamps a time on it, so TickTick fires a notification with the tappable
  link at 08:00.
- 💼 **Work** and ⚡ **Quick** are capture-only — jotted down anytime, never
  auto-scheduled into a focus slot.

### Schedule shape
- **08:00–09:00** light reading (pulled from Reading Queue) every day.
- **Weekday evenings 20:30–22:30** — two 60-min deep-work slots (Projects/Study).
- **Weekends/day-off** — dense deep-work sessions plus a 30-min admin slot.

### The scoring seam (why nothing gets wasted later)
Carry-over lives behind one function, `recommend.score_candidates(category,
candidates, history)`. Today it's a transparent heuristic (skips bubble up,
drops sink). When you add smart recommendations, you replace **only that
function body** with a model trained on `state/history.jsonl` — the scheduler,
evening loop, Telegram UI, and log are untouched. The history log is the
durable artifact; the heuristic is deliberately disposable.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill it in (see below), and: chmod 600 .env
```

### 1. Telegram bot
1. Message **@BotFather** → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
2. Find your chat id: `python main.py --whoami`, then message your bot — it prints
   the id. Put it in `TELEGRAM_CHAT_ID`.

### 2. TickTick OAuth
1. Go to https://developer.ticktick.com/manage → create an app.
2. Set its **redirect URI** to exactly `http://localhost:8080/callback`.
3. Copy client id/secret into `.env`.
4. Run `python auth.py` once → browser opens → approve. Tokens saved to
   `tokens.json`. Done forever (unless you revoke it).

### 3. TickTick lists
Make sure you have lists named to match `config.yaml`:
`Projects`, `Study`, `Admin`, `Reading Queue`, `Work`, `Inbox` (rename in config
if you prefer). `python setup_lists.py` creates any that are missing.
Put your actual tasks in them. Empty lists fall back to the `items:` in config.

## Run

```bash
python main.py            # start the bot; morning + evening pings fire at config times
python main.py --now      # test: send today's planning message right now
python main.py --review   # test: send tonight's review message right now
```

### Keep it alive (systemd user service)
```ini
# ~/.config/systemd/user/tick-tick.service
[Unit]
Description=tick-tick scheduler bot
[Service]
WorkingDirectory=%h/Desktop/Projects/tick-tick
ExecStart=%h/Desktop/Projects/tick-tick/.venv/bin/python main.py
Restart=always
[Install]
WantedBy=default.target
```
```bash
systemctl --user enable --now tick-tick
loginctl enable-linger $USER   # so it runs even when you're logged out
```

## Tuning behaviour
- `fill_strategy: rotation` spreads slots across categories; `priority` drains
  your top category first.
- `weight:` per category biases how often it's picked under rotation.
- Add/remove `focus` blocks in any template to change how many slots a day has.
