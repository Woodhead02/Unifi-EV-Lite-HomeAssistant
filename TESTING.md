# Testing v1.1.0 on a real charger

This version was tested with automated tests and simulations, but **not yet on a
real charger**. Follow these steps once, in order. It takes about an hour.
Tick each box as you go. If anything in **"What should happen"** does not
happen, stop and note which step failed.

You need: the charger installed and working in UniFi Connect, Home Assistant,
the UniFi app (or the Connect page in your browser), and ideally a car you can
plug in for part 4.

---

## Part 0 — Make it safe before you start

- [ ] **Set a fixed safe limit in UniFi Connect.** In Connect, open the charger
      and set its maximum output to a value that is safe even with the house at
      full load (ask your electrician). This is your safety net: whatever Home
      Assistant does, the charger never goes above it.
- [ ] **Take a Home Assistant backup** (Settings → System → Backups).
- [ ] **Write down** the charger's current maximum output shown in Connect:
      `_____ A`

## Part 1 — Install

1. Copy the `unifi_ev_station` folder from the zip into
   `/config/custom_components/` in Home Assistant, replacing the old folder.
2. Restart Home Assistant.
3. If the integration is not set up yet: Settings → Devices & services →
   Add integration → **UniFi EV Station**. Use a **local** UniFi OS user.

- [ ] **What should happen:** the integration loads without errors
      (Settings → System → Logs shows nothing red for `unifi_ev_station`).

## Part 2 — Check the new things are there

Open the charger's device page (Settings → Devices & services → UniFi EV
Station → your charger).

- [ ] **Live telemetry** (under Diagnostic) shows **Connected**.
- [ ] **Maximum output pending** (under Diagnostic) shows **Off**.
- [ ] **Maximum output** slider goes from **6 to 32 A** (or lower, if you set a
      limit in Part 3).
- [ ] **Power / Current / Voltage** show numbers (0 is fine if no car).

Then set your own limit:

4. On the integration card, click **Configure**.
5. Set **Maximum current per charger** to the limit your electrician approved
   (for example 16). Leave the other values as they are. Save.

- [ ] **What should happen:** the Maximum output slider now stops at your
      limit. Typing a higher number is refused with an error.

## Part 3 — Commands reach the charger (no car needed)

Keep the UniFi Connect page for the charger open next to Home Assistant.

| # | Do this in Home Assistant | What should happen | ✓ |
|---|---|---|---|
| 3.1 | Set **Maximum output** to **10 A** | Connect shows 10 A within a few seconds. *Pending* stays Off. | |
| 3.2 | Set it to **8 A** (a decrease) | Connect shows 8 A straight away. | |
| 3.3 | Set it to **12 A**, then within 30 s set **16 A** | Connect shows 12 A first. *Pending* turns **On**. Within about a minute Connect shows 16 A and *Pending* turns **Off**. (Increases are limited to one per 30 s.) | |
| 3.4 | Change it in **Connect** to a different value (e.g. 20 A), then wait up to 5 minutes | Home Assistant puts it back to its own value (16 A). This is the "re-send" safety feature. | |

> If 3.1 does not change anything in Connect: open the **Maximum output**
> entity's attributes and look at `last_error`, then check the logs.

## Part 4 — With a car plugged in

Use a **low** limit for this part (e.g. 8–10 A).

| # | Do this | What should happen | ✓ |
|---|---|---|---|
| 4.1 | Plug in and start charging | **Power** and **Current** rise; **Charging status** shows *Charging*. | |
| 4.2 | Set Maximum output to **6 A** | **Current** drops to about 6 A within ~30 s (the car takes a moment). | |
| 4.3 | Set it to **10 A** | **Current** rises to about 10 A. | |
| 4.4 | Turn **Allow charging** off, then on | Charging stops, then resumes. | |

## Part 5 — Failure tests (the important part)

| # | Do this | What should happen | ✓ |
|---|---|---|---|
| 5.1 | **Restart Home Assistant** while charging | After restart the charger is set to the same Maximum output as before (check Connect and the logs: *"maximum output set to X A (unknown_state)"*). | |
| 5.2 | **Restart the UniFi console** (or unplug its network cable for 2 min) | While it is down: **Live telemetry** → *Disconnected*, Power/Current → *Unavailable* (not 0). When it is back: telemetry reconnects and the limit is re-sent (log: *"re-asserting setpoints"*). | |
| 5.3 | **Change the password** of the Home Assistant user in UniFi OS | Home Assistant shows a **Re-authenticate** prompt. Enter the new password → everything works again. Change it back afterwards if you like. | |
| 5.4 | **Stop Home Assistant completely** while charging | The charger keeps charging at its last limit and never above the safe limit from Part 0. (This is why Part 0 matters.) Start Home Assistant again. | |

## Part 6 — Leave it running

- [ ] Let it run for a few days of normal charging.
- [ ] Check the logs once a day for warnings from `unifi_ev_station`.
- [ ] Only after that, connect it to your load-management automation.

---

### Turn on detailed logs (helps if something fails)

Add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.unifi_ev_station: debug
```

Look at Settings → System → Logs. Useful lines start with
*"Charger … maximum output set to"*, *"telemetry lost"*,
*"telemetry restored"* and *"failed to set maximum output"*.

### If something goes wrong

- Put the old version back from your backup (Part 0), or copy the original
  `unifi_ev_station` folder back and restart.
- The safe limit set in UniFi Connect still protects the supply either way.
- When reporting a problem, include the step number, your EV Station model and
  firmware, UniFi OS and Connect versions, and the relevant log lines.
  **Never** post passwords, cookies or tokens.
