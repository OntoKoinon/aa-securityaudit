# AllianceAuth Security Audit

[![release](https://img.shields.io/pypi/v/aa-securityaudit?label=release)](https://pypi.org/project/aa-securityaudit/)
[![python](https://img.shields.io/pypi/pyversions/aa-securityaudit)](https://pypi.org/project/aa-securityaudit/)
[![django](https://img.shields.io/pypi/djversions/aa-securityaudit?label=django)](https://pypi.org/project/aa-securityaudit/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**The most comprehensive security audit tool for AllianceAuth.** Know exactly who you're recruiting — and what your existing members are really up to.

Every alliance loses ships, ISK, and morale to spies, awoxers, and thieves who slipped through recruitment. Security Audit stops that before it happens by running a full background check on every character — new recruits and veteran members alike — and surfacing the red flags that matter.

## Contents

- [Why Security Audit?](#why-security-audit)
- [What It Detects](#what-it-detects)
- [What It Tracks](#what-it-tracks)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Permissions](#permissions)
- [Policy Settings](#policy-settings)
- [Performance](#performance)
- [AllianceAuth Compatibility](#allianceauth-compatibility)
- [Changelog](#changelog)
- [Contribute](#contribute)
- [License](#license)

## Why Security Audit?

- **Catch awoxers before they strike.** Don't find out someone's awoxing your supers after the fact. Security Audit detects deliberate friendly-fire patterns that other tools miss — including tackle-only awoxing, HIC infinipoint pilots, and blue-scouting with NPC-corp alts.
- **Spot spies on day one.** Automated new-join audits run the moment someone enters your alliance, checking for enemy connections, blacklist hits, and corp-history patterns that signal a plant.
- **Track the big assets.** Know who's sitting in titans, supercarriers, and dreadnoughts — and whether they're using them against your enemies or your allies.
- **Follow the money.** Large ISK donations, free contracts, and repeated transfers can signal bribery, asset extraction, or RMT. Security Audit flags them all.
- **Share findings with leadership.** Generate time-limited summary links so your FCs and directors can review audit results without needing dashboard access.

## What It Detects

### Awoxing / Friendly Fire
The most sophisticated awox detector available for AllianceAuth. It doesn't just flag killmail participation — it identifies **deliberate** friendly-fire patterns:

- **Damage ownership** — final blow or majority damage on a blue.
- **Tackle contribution** — warp scramblers, warp disruptors, and HIC infinipoints count even with zero damage. A tackle alt holding down a friendly for the enemy is an awox, not crossfire.
- **HIC pilots** — heavy interdiction cruiser pilots qualify regardless of damage or weapon, because a HIC's job is to hold the target.
- **Blue scouting** — catches the classic trick of using an NPC-corp alt to kill someone in the main's corp or alliance while the main stays blue to the victim.

It automatically excludes the noise that trips up crude detectors:
- Large-fleet crossfire with hostiles present
- Killmail whoring (low damage, no final blow, no tackle)
- Structure bashes
- Sparring in throwaway ships (rookie ships, corvettes, shuttles below a configurable ISK threshold — pods are always exempt)

Supercarrier and titan victims get extra scoring weight. Every finding names the type of awox and links directly to the zKill killmails so you can review the evidence in one click.

### Undisclosed Alts
Finds characters linked in Auth that aren't declared as expected for a main, plus undisclosed alt corporations with suspicious corp-history overlap. If someone's been hiding an alt in an enemy-adjacent corp, you'll know.

### Spy Activity / Enemy Collusion
Flags pilots appearing on the same side as blacklisted or enemy entities on killmails. If your member is consistently flying with your enemies, that's not a coincidence — and each finding links to the zKill kills so you can see exactly when and where it happened.

### Flight Risk
Detects corp-hopping behavior — pilots who bounce between corporations frequently within a configurable window. Someone who's joined and left five corps in 90 days is telling you something about themselves.

### Enemy Connections
Flags direct ties to enemy alliances, corporations, or characters on your enemy list. Build your enemy list once and every audit checks against it automatically.

### +10 Standing Contacts
Identifies pilots who have +10 standing to known hostiles or blacklisted entities. If someone's blued your enemies, that's worth a conversation.

### Blacklist Adjacency
Correlates mains, alts, and observed contacts against [allianceauth-blacklist](https://github.com/MemberAudit/allianceauth-blacklist) entries. Leverage the community's shared blacklist data to catch known bad actors before they're your problem.

### Suspicious ISK Movement
- **Large donations** — wallet transfers at or above a configurable ISK threshold.
- **Free contracts** — contracts handing over high-value assets for zero or near-zero ISK.
- **Repeated transfers** — patterns of small transfers that add up over time.

Financial exceptions let you whitelist legitimate transfers like corp reimbursements so you only see the real red flags.

## What It Tracks

### Capital Ship Observations
Tracks capital and supercapital hull usage — titans, supercarriers, force auxiliaries, dreadnoughts, and carriers — from zKill kill/loss history and MemberAudit asset and current-ship data. Know who's got the big sticks, who's actually using them, and who's been losing them.

## How It Works

### For New Recruits
Automated audits run on every new join within a configurable window (default: first 14 days). Set it and forget it — new members are vetted automatically, and findings appear on your dashboard ready for review.

### For Existing Members
Run a manual audit on any character or entire corporation at any time. Use the per-run option toggles to skip expensive checks when you just need a quick check, or enable everything for a full deep-dive:

- **Standard Audit** (always included)
- **Undisclosed Alt Check** — toggle off to skip corp-history overlap analysis
- **Capital Observations** — toggle off to skip capital ship tracking
- **Awoxing Check** — toggle off to skip friendly-fire analysis

Need to tighten or loosen a threshold for a single audit without changing global policy? The advanced overrides panel lets you adjust any threshold per-run.

### Sharing Results
Generate time-limited summary links to share audit findings with FCs, directors, or alliance leadership without granting them dashboard access. Links expire automatically based on your configured timeout.

### Real-Time Updates
Audit detail pages update live — no manual refresh needed. Watch the audit progress through each analysis stage as it happens.

## Installation

### Prerequisites

> [!IMPORTANT]
> Please make sure you meet all prerequisites before you proceed!

- **[AllianceAuth](https://github.com/allianceauth/allianceauth)** — This is an AllianceAuth plugin; you need a working AllianceAuth installation (AllianceAuth 5 fully supported).
- **[MemberAudit](https://gitlab.com/ErikKalkoken/aa-memberaudit)** >= 5.0.0 — Required for wallet data, corporation history, character snapshots, asset/ship tracking, and contact standings. MemberAudit 5.x supports both AllianceAuth 4 and 5. Without MemberAudit installed and listed in `INSTALLED_APPS`, the plugin will log a warning at startup and most audit checks will be degraded or unavailable. If you're serious about security auditing, MemberAudit is non-negotiable.
- **[allianceauth-blacklist](https://github.com/MemberAudit/allianceauth-blacklist)** *(optional but recommended)* — Enables blacklist correlation findings. Leverage shared community blacklist data to catch known bad actors.

### Steps

1. Install the latest release directly from PyPI. Make sure you're in the virtual environment of your AllianceAuth installation:
   ```bash
   pip install aa-securityaudit
   ```
   For development:
   ```bash
   pip install -e .
   ```

2. Add `allianceauth_securityaudit` to your `INSTALLED_APPS` in `local.py`, after `memberaudit` and any other dependencies:
   ```python
   INSTALLED_APPS += [
       "memberaudit",
       "allianceauth_securityaudit",
   ]
   ```

3. Run migrations:
   ```bash
   python manage.py migrate
   ```

4. Collect static files:
   ```bash
   python manage.py collectstatic
   ```

5. Restart your AllianceAuth server.

### Finalizing the Installation

1. **Assign permissions** to your leadership or recruitment teams (see [Permissions](#permissions) below).
2. **Configure policy thresholds** via the Policy Editor page. The defaults are sensible for most alliances, but everything is tunable.
3. **Build your enemy list** — Add enemy alliances, corporations, and characters via the Enemy List page. Every audit checks against this list automatically.
4. **Add financial exceptions** to exempt specific entities from having the tool report on their financials, useful for protecting the identity of entities who are paying you for contract deployments, or for hiding payments to your own spies.

## Permissions

| Permission | Description |
|---|---|
| `securityaudit.view_dashboard` | View the security audit dashboard and audit list |
| `securityaudit.view_summaries` | View shareable audit summary pages |
| `securityaudit.run_audit` | Run manual security audits on characters and corporations |
| `securityaudit.administrate` | Full admin access: policy editor, enemy list, financial exceptions, job management |
| `securityaudit.generate_link` | Generate shareable summary links for audit results |
| `securityaudit.manage_enemies` | Add and remove entries from the enemy list |
| `securityaudit.view_enemies` | View the enemy list |

## Policy Settings

All settings are configurable via the Policy Editor page in the AllianceAuth admin UI. The defaults work well for most alliances — adjust as needed for your security posture.

### Master Switches

| Setting | Default | Description |
|---|---|---|
| `enabled` | On | Globally enable or disable the plugin. |
| `automation_enabled` | On | Toggle automated new-join audits. |
| `new_join_window_days` | 14 days | How many days after a new join to automatically audit the member. |

### ISK / Wallet

| Setting | Default | Description |
|---|---|---|
| `large_donation_isk_threshold` | 1,000,000,000 ISK | Flag wallet donations at or above this amount. Lower this if you want to catch smaller transfers. |

### Contracts

| Setting | Default | Description |
|---|---|---|
| `free_contract_value_threshold` | 500,000,000 ISK | Flag contracts with zero or near-zero consideration at or above this value. |

### Corporation Movement (Flight Risk)

| Setting | Default | Description |
|---|---|---|
| `corp_hop_window_days` | 90 days | Lookback window for corp-hopping detection. |
| `corp_hop_count_threshold` | 3 | Number of corp joins within the window to flag as flight risk. |

### Undisclosed Alts (Corp History)

| Setting | Default | Description |
|---|---|---|
| `alt_corp_history_max_join_leave_diff_hours` | 24 hours | Max hours between an alt's and main's corp join/leave dates to count as suspicious overlap. |
| `corp_overlap_rule1_min_corps` | 1 | Min overlapping non-NPC corps for a strong alt signal (both join and leave dates close). |
| `corp_overlap_rule2_min_corps` | 3 | Min overlapping non-NPC corps for a moderate alt signal (either join or leave dates close). |
| `corp_overlap_rule3_min_corps` | 5 | Min overlapping non-NPC corps for a weak alt signal (no close date match). |

### Killmails

| Setting | Default | Description |
|---|---|---|
| `killmail_max_attacker_count` | 0 (no limit) | Skip killmails with more attackers than this. Useful to avoid processing huge fleet fights. Set to 0 for no limit. |

### Awox / Friendly Fire

| Setting | Default | Description |
|---|---|---|
| `awox_min_damage_share` | 0.50 (50%) | Minimum damage share (damage done / damage taken) for damage-ownership awox qualification. Below this, a pilot must have final blow, tackle, or be in a HIC to qualify. |
| `awox_lookback_days` | 180 days | How far back in kill history to look for awox kills. Older kills are ignored. |
| `awox_large_fleet_attacker_threshold` | 10 | Attacker count at which the large-fleet crossfire exclusion kicks in. In large fleets with hostiles present, low-damage non-final-blow participants without tackle or HIC are excluded as crossfire. |
| `awox_solo_attacker_threshold` | 3 | Attacker count at or below which a solo/small-gang bonus is applied to the awox score. Solo awoxing is more suspicious than fleet crossfire. |
| `awox_min_victim_value` | 10,000,000 ISK | Minimum zKill total value for rookie ship/corvette/shuttle victims to avoid being excluded as sparring. Pods are always exempt regardless of this setting. |
| `awox_blue_scouting_bonus` | 15 | Score bonus per kill qualified via the blue-scouting path (NPC-corp alt with main/other alts blue to the victim). Reflects premeditation. |

### zKill

| Setting | Default | Description |
|---|---|---|
| `zkill_throttle_seconds` | 0.10s | Delay between zKill API calls to avoid rate limiting. |
| `zkill_kill_pages` | 3 | Pages of kill history to fetch per character. |
| `zkill_loss_pages` | 3 | Pages of loss history to fetch per character. |
| `zkill_capital_kill_pages` | 5 | Pages per capital ship group to fetch for capital kill scans. |
| `zkill_capital_loss_pages` | 5 | Pages per capital ship group to fetch for capital loss scans. |

### Infrastructure

| Setting | Default | Description |
|---|---|---|
| `esi_throttle_seconds` | 0.10s | Delay between ESI API calls to avoid rate limiting. |
| `summary_link_expiry_hours` | 24 hours | Hours until shareable summary links expire. |

## Performance

Security Audit processes large datasets (killmails, wallet journals, contracts, asset lists) during each audit run. In-process caches for affiliations, type info, and corporation lookups accumulate over the lifetime of a Celery worker process. On busy alliances with automated new-join audits, these caches can grow significantly.

To prevent gradual memory growth in Celery workers, set `max_tasks_per_child` on your Celery worker process. This recycles the worker after N tasks, releasing all accumulated in-process memory:

```bash
celery -A myauth worker --max-tasks-per-child=10
```

Or in your AllianceAuth `local.py`:

```python
CELERY_WORKER_MAX_TASKS_PER_CHILD = 10
```

A value of 10 is a good starting point. Each audit run counts as one task, so this recycles the worker after every 10 audits. The cost is a ~1 second delay when the worker process restarts, which is negligible.

## AllianceAuth Compatibility

- AllianceAuth 5 is fully supported.
- The plugin ships a compatibility `allianceauth/base.html` template that forwards to `allianceauth/base-bs5.html` for AA5 environments where `allianceauth/base.html` is not present.
- Keep standard AllianceAuth app ordering in `INSTALLED_APPS` so core templates resolve as expected on older installations.
- If your AA5 build uses a different base template filename, update `allianceauth_securityaudit/templates/allianceauth/base.html` to extend that canonical base path.
- URL routing is auto-registered via the AllianceAuth hook (`url_hook`), so no manual project `urls.py` include is required.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.

## Contribute

Found a bug or have a feature idea? Please open an issue or pull request on
[GitHub](https://github.com/OntoKoinon/aa-securityaudit).

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE)
file for details.
