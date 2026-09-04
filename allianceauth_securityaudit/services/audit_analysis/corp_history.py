from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from ...models import AuditFinding, AuditRelationshipCounterparty
from ..esi_client import EsiClient
from ..memberaudit_adapter import MemberAuditAdapter

def score_beta_overlap_rule(corp_stats, rule1_min=1, rule2_min=3, rule3_min=5):
    if not corp_stats:
        return None

    count = len(corp_stats)
    any_close = any(item.get("any_close") for item in corp_stats)
    any_both_close = any(item.get("both_close") for item in corp_stats)

    options = []
    if count >= rule1_min and any_both_close:
        extras = corp_stats[rule1_min:]
        score = 60 + (5 * len(extras))
        score += sum(10 if item.get("both_close") else 5 if item.get("any_close") else 0 for item in extras)
        options.append(("rule_1", score))

    if count >= rule2_min and any_close:
        extras = corp_stats[rule2_min:]
        score = 40 + (5 * len(extras))
        score += sum(5 for item in extras if item.get("any_close"))
        options.append(("rule_2", score))

    if count >= rule3_min and not any_close:
        score = 10 + (5 * (count - (rule3_min - 1)))
        options.append(("rule_3", score))

    if not options:
        return None
    return max(options, key=lambda x: x[1])

class CorpHistoryMixin:

    def _score_beta_overlap_rule(self, corp_stats):
        return score_beta_overlap_rule(
            corp_stats,
            rule1_min=self.policy.corp_overlap_rule1_min_corps,
            rule2_min=self.policy.corp_overlap_rule2_min_corps,
            rule3_min=self.policy.corp_overlap_rule3_min_corps,
        )

    @staticmethod
    def _intervals_overlap(start_a, end_a, start_b, end_b):
        if end_a is None:
            end_a = timezone.now()
        if end_b is None:
            end_b = timezone.now()
        return start_a < end_b and start_b < end_a

    @staticmethod
    def _corp_history_intervals(corp_history):
        if not corp_history:
            return []
        rows = []
        for row in corp_history:
            corp_id = row.get("corporation_id")
            start = EsiClient.parse_esi_time(row.get("start_date"))
            if not corp_id or not start:
                continue
            rows.append({"corporation_id": int(corp_id), "start_date": start})
        rows.sort(key=lambda x: x["start_date"])
        intervals = []
        for i, row in enumerate(rows):
            end = rows[i + 1]["start_date"] if i + 1 < len(rows) else None
            intervals.append((row["corporation_id"], row["start_date"], end))
        return intervals

    def _find_hop_windows(self, corp_history):
        """Return a list of corp-hopping windows.

        Each window is a list of corp history rows where at least threshold changes
        occurred within the configured number of days. NPC corporation memberships
        are excluded from the hop calculation.
        """
        if not corp_history:
            return []

        # Fetch and cache NPC corporation IDs so they can be excluded.
        npc_cache_key = "securityaudit:npc_corp_ids"
        npc_ids = cache.get(npc_cache_key)
        if npc_ids is None:
            try:
                npc_ids = set(self.esi.get_npc_corporations())
            except Exception:
                npc_ids = set()
            cache.set(npc_cache_key, npc_ids, 86400)

        dated = []
        for entry in corp_history:
            corp_id = entry.get("corporation_id")
            if corp_id and corp_id in npc_ids:
                continue
            start_date = self.esi.parse_esi_time(entry.get("start_date"))
            if not start_date:
                continue
            dated.append({"corporation_id": corp_id, "start_date": start_date})

        if not dated:
            return []

        dated.sort(key=lambda x: x["start_date"])
        n = len(dated)
        window_timedelta = timedelta(days=self.policy.corp_hop_window_days)
        threshold = self.policy.corp_hop_count_threshold

        j = 0
        windows = []
        last_end = -1
        for i in range(n):
            if i < last_end:
                continue
            if j < i:
                j = i
            while j < n and (dated[j]["start_date"] - dated[i]["start_date"]) <= window_timedelta:
                j += 1
            if (j - i) >= threshold:
                windows.append(dated[i:j])
                last_end = j

        return windows

    def _detect_alt_corp_history(self, audit_run, character_id, user, kills, progress_callback=None):
        def _fmt(td):
            parts = []
            if td.days:
                parts.append(f"{td.days} day{'s' if td.days != 1 else ''}")
            hours, rem = divmod(td.seconds, 3600)
            if hours:
                parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            minutes, _ = divmod(rem, 60)
            if minutes:
                parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            if not parts:
                return "0 minutes"
            return ", ".join(parts)

        reference_ids = MemberAuditAdapter.get_user_declared_character_ids(user)
        if character_id:
            reference_ids.add(character_id)
        if not reference_ids:
            return None

        resolved_refs = self.esi.resolve_names(reference_ids) if reference_ids else {}
        main_name = resolved_refs.get(character_id) or audit_run.target.character_name or "main"

        reference_intervals_by_id = {}
        reference_current_corps_by_id = {}
        for ref_id in reference_ids:
            history = MemberAuditAdapter.get_character_corp_history(character_id=ref_id)
            if not history:
                try:
                    history = self.esi.get_character_corp_history(ref_id)
                except Exception:
                    history = []
            intervals = self._corp_history_intervals(history)
            reference_intervals_by_id[ref_id] = intervals
            reference_current_corps_by_id[ref_id] = {corp_id for corp_id, _start, end in intervals if end is None}

        source_map = {}
        candidate_references = {}

        def _note_source(cid, ref_id, label):
            if cid in reference_ids:
                return
            source_map.setdefault(cid, set()).add(label)
            candidate_references.setdefault(cid, set()).add(ref_id)

        type_label = {
            AuditRelationshipCounterparty.COUNTERPARTY_PLUS_TEN: f"+10 standing contact (from {main_name})",
            AuditRelationshipCounterparty.COUNTERPARTY_ISK_DONATION: f"wallet donation (from {main_name})",
            AuditRelationshipCounterparty.COUNTERPARTY_FREE_CONTRACT: f"free contract (from {main_name})",
        }
        for cp in audit_run.counterparties.exclude(character_id__isnull=True):
            cp_id = cp.character_id
            if cp_id in reference_ids or cp.counterparty_type == AuditRelationshipCounterparty.COUNTERPARTY_POSSIBLE_ALT:
                continue
            _note_source(cp_id, character_id, type_label.get(cp.counterparty_type, "observed counterparty"))

        for contact_id in MemberAuditAdapter.get_contact_character_ids(character_id):
            _note_source(contact_id, character_id, f"contact (from {main_name})")

        for alt_id in MemberAuditAdapter.get_user_declared_character_ids(user):
            if character_id and alt_id == character_id:
                continue
            alt_name = resolved_refs.get(alt_id) or str(alt_id)
            alt_standings = MemberAuditAdapter.get_contact_character_standings(alt_id)
            for contact_id, standing in (alt_standings or {}).items():
                if contact_id in reference_ids:
                    continue
                if standing is not None and float(standing) >= 10:
                    _note_source(contact_id, alt_id, f"+10 standing contact (from {alt_name})")

        killmail_links = {}
        killmail_dates = {}
        for kill in kills or []:
            kill_id = kill.get("killmail_id")
            if not kill_id:
                continue
            kill_time = None
            raw_time = kill.get("killmail_time")
            if raw_time:
                try:
                    kill_time = EsiClient.parse_esi_time(raw_time)
                except Exception:
                    kill_time = None
            killmail_dates[str(kill_id)] = kill_time
            participant_ids = set()
            for attacker in kill.get("attackers") or []:
                aid = attacker.get("character_id")
                if aid:
                    participant_ids.add(aid)
            source_character_id = kill.get("__source_character_id")
            for pid in participant_ids:
                if pid in reference_ids:
                    continue
                source_map.setdefault(pid, set()).add("killmail")
                if source_character_id:
                    candidate_references.setdefault(pid, set()).add(source_character_id)
                killmail_links.setdefault(pid, set()).add(str(kill_id))

        if not source_map:
            return None

        now = timezone.now()
        max_delta = timedelta(hours=self.policy.alt_corp_history_max_join_leave_diff_hours)

        npc_ids = cache.get("securityaudit:npc_corp_ids")
        if npc_ids is None:
            try:
                npc_ids = set(self.esi.get_npc_corporations())
            except Exception:
                npc_ids = set()
            cache.set("securityaudit:npc_corp_ids", npc_ids, 86400 * 7)

        reference_total = {ref_id: 0 for ref_id in reference_ids}
        for refs in candidate_references.values():
            for ref_id in refs:
                if ref_id in reference_total:
                    reference_total[ref_id] += 1
        reference_pending = reference_total.copy()

        candidate_ids = sorted(source_map)
        total_candidates = max(len(candidate_ids), 1)
        matched_candidates = []
        all_corp_ids = set()

        for idx, candidate_id in enumerate(candidate_ids, start=1):
            try:
                history = MemberAuditAdapter.get_character_corp_history(character_id=candidate_id)
                if not history:
                    try:
                        history = self.esi.get_character_corp_history(candidate_id)
                    except Exception:
                        history = []
                candidate_intervals = self._corp_history_intervals(history)
                if not candidate_intervals:
                    continue
                candidate_current_corps = {corp_id for corp_id, _start, end in candidate_intervals if end is None}

                references_for_candidate = []
                for ref_id in sorted(reference_ids):
                    ref_intervals = reference_intervals_by_id.get(ref_id) or []
                    if not ref_intervals:
                        continue
                    reference_current_corps = reference_current_corps_by_id.get(ref_id) or set()
                    overlaps = []
                    by_corp = {}
                    for c_corp, c_start, c_end in candidate_intervals:
                        for r_corp, r_start, r_end in ref_intervals:
                            if c_corp != r_corp:
                                continue
                            c_effective_end = c_end or now
                            r_effective_end = r_end or now
                            overlap_start = max(c_start, r_start)
                            overlap_end = min(c_effective_end, r_effective_end)
                            if overlap_start >= overlap_end:
                                continue

                            start_diff = abs(c_start - r_start)
                            end_diff = abs(c_effective_end - r_effective_end)
                            both_close = start_diff <= max_delta and end_diff <= max_delta
                            any_close = start_diff <= max_delta or end_diff <= max_delta
                            present_excluded = (
                                c_corp in candidate_current_corps
                                and c_corp in reference_current_corps
                            )
                            npc = c_corp in npc_ids

                            overlaps.append(
                                {
                                    "reference_id": ref_id,
                                    "corp_id": c_corp,
                                    "npc": npc,
                                    "start_diff": start_diff,
                                    "end_diff": end_diff,
                                    "overlap_days": (overlap_end - overlap_start).days,
                                    "candidate_start": c_start,
                                    "candidate_end": c_end,
                                    "reference_start": r_start,
                                    "reference_end": r_end,
                                    "both_close": both_close,
                                    "any_close": any_close,
                                    "present_excluded": present_excluded,
                                }
                            )
                            all_corp_ids.add(c_corp)

                            if npc or present_excluded:
                                continue
                            stats = by_corp.setdefault(
                                c_corp, {"corp_id": c_corp, "both_close": False, "any_close": False}
                            )
                            stats["both_close"] = stats["both_close"] or both_close
                            stats["any_close"] = stats["any_close"] or any_close

                    qualifying = sorted(by_corp.values(), key=lambda item: item["corp_id"])
                    rule_eval = self._score_beta_overlap_rule(qualifying)
                    if not rule_eval:
                        continue
                    rule_name, rule_score = rule_eval
                    references_for_candidate.append(
                        {
                            "reference_id": ref_id,
                            "rule_name": rule_name,
                            "rule_score": rule_score,
                            "qualifying_count": len(qualifying),
                            "overlaps": overlaps,
                            "candidate_intervals": candidate_intervals,
                            "reference_intervals": ref_intervals,
                        }
                    )

                if references_for_candidate:
                    winner = max(references_for_candidate, key=lambda row: row["rule_score"])
                    matched_candidates.append(
                        {
                            "candidate_id": candidate_id,
                            "sources": source_map[candidate_id],
                            "references": references_for_candidate,
                            "winner": winner,
                            "candidate_intervals": candidate_intervals,
                        }
                    )
            finally:
                for ref_id in candidate_references.get(candidate_id, ()):
                    reference_pending[ref_id] = max(reference_pending.get(ref_id, 0) - 1, 0)
                if callable(progress_callback):
                    progress_callback(
                        idx,
                        total_candidates,
                        candidate_id,
                        {
                            "corphistory_references": [
                                {
                                    "id": ref_id,
                                    "name": resolved_refs.get(ref_id) or str(ref_id),
                                    "total": reference_total.get(ref_id, 0),
                                    "completed": reference_total.get(ref_id, 0) - reference_pending.get(ref_id, 0),
                                    "done": reference_pending.get(ref_id, 0) <= 0,
                                }
                                for ref_id in sorted(reference_ids)
                            ]
                        },
                    )

        if not matched_candidates:
            return None

        candidate_ids_to_resolve = {item["candidate_id"] for item in matched_candidates}
        all_ids_to_resolve = set(reference_ids) | candidate_ids_to_resolve | all_corp_ids
        resolved = self.esi.resolve_names(all_ids_to_resolve) if all_ids_to_resolve else {}
        target_name = resolved.get(character_id) or audit_run.target.character_name or str(character_id)

        def _render_reference_grid(character_name, reference_name, reference_intervals, candidate_intervals):
            reference_intervals_desc = sorted(reference_intervals, key=lambda x: x[1], reverse=True)
            candidate_intervals_desc = sorted(candidate_intervals, key=lambda x: x[1], reverse=True)

            def _render_row(ref_entry, cand_entry):
                ref_cell = ""
                cand_cell = ""
                overlap_html = ""
                row_style = ""
                if ref_entry:
                    ref_corp, ref_start, ref_end = ref_entry
                    ref_end_eff = ref_end or now
                    ref_name = resolved.get(ref_corp) or str(ref_corp)
                    ref_npc = '<span class="badge text-bg-secondary ms-1">NPC</span>' if ref_corp in npc_ids else ""
                    ref_end_str = ref_end.strftime("%Y-%m-%d %H:%M") if ref_end else "Present"
                    ref_start_str = ref_start.strftime("%Y-%m-%d %H:%M")
                    ref_range_end = ref_end.strftime("%b %Y") if ref_end else "Present"
                    ref_range = f'{ref_start.strftime("%b %Y")} &ndash; {ref_range_end}'
                    ref_duration_days = max((ref_end_eff - ref_start).days, 0)
                    ref_day_label = "day" if ref_duration_days == 1 else "days"
                    ref_cell = (
                        f'<div class="fw-semibold">{ref_name}{ref_npc}</div>'
                        f'<div class="small">{ref_range} '
                        f'<span class="badge bg-primary" style="border-radius: 0.35rem;">{ref_duration_days} {ref_day_label}</span></div>'
                        f'<div class="small text-muted">{ref_start_str} to {ref_end_str}</div>'
                    )
                if cand_entry:
                    cand_corp, cand_start, cand_end = cand_entry
                    cand_end_eff = cand_end or now
                    cand_name = resolved.get(cand_corp) or str(cand_corp)
                    cand_npc = '<span class="badge text-bg-secondary ms-1">NPC</span>' if cand_corp in npc_ids else ""
                    cand_end_str = cand_end.strftime("%Y-%m-%d %H:%M") if cand_end else "Present"
                    cand_start_str = cand_start.strftime("%Y-%m-%d %H:%M")
                    cand_range_end = cand_end.strftime("%b %Y") if cand_end else "Present"
                    cand_range = f'{cand_start.strftime("%b %Y")} &ndash; {cand_range_end}'
                    cand_duration_days = max((cand_end_eff - cand_start).days, 0)
                    cand_day_label = "day" if cand_duration_days == 1 else "days"
                    cand_cell = (
                        f'<div class="fw-semibold">{cand_name}{cand_npc}</div>'
                        f'<div class="small">{cand_range} '
                        f'<span class="badge bg-primary" style="border-radius: 0.35rem;">{cand_duration_days} {cand_day_label}</span></div>'
                        f'<div class="small text-muted">{cand_start_str} to {cand_end_str}</div>'
                    )
                if (
                    ref_entry
                    and cand_entry
                    and ref_entry[0] == cand_entry[0]
                    and ref_entry[0] not in npc_ids
                    and not (ref_entry[2] is None and cand_entry[2] is None)
                ):
                    _, ref_start, ref_end = ref_entry
                    _, cand_start, cand_end = cand_entry
                    ref_end_eff = ref_end or now
                    cand_end_eff = cand_end or now
                    overlap_start = max(ref_start, cand_start)
                    overlap_end = min(ref_end_eff, cand_end_eff)
                    if overlap_start < overlap_end:
                        row_style = ' style="background-color: #f8d7da !important; color: #212529 !important;"'
                        overlap_days = (overlap_end - overlap_start).days
                        start_diff = abs(cand_start - ref_start)
                        end_diff = abs(cand_end_eff - ref_end_eff)
                        overlap_html = (
                            f'<span class="badge bg-danger mb-1" style="border-radius: 0.35rem;">OVERLAP</span>'
                            + f'<div class="small text-danger">Start Difference: {_fmt(start_diff)}</div>'
                            + f'<div class="small text-danger">End Difference: {_fmt(end_diff)}</div>'
                            + f'<div class="small text-danger">Overlap Duration: {overlap_days} day{"s" if overlap_days != 1 else ""}</div>'
                        )
                row_html = (
                    f'<tr{row_style}>'
                    f'<td class="align-top" style="width: 50%;">{ref_cell}</td>'
                    f'<td class="align-top" style="width: 50%;">{cand_cell}</td>'
                    f"</tr>"
                )
                if overlap_html:
                    row_html += (
                        f'<tr{row_style}>'
                        f'<td colspan="2" class="text-center">{overlap_html}</td>'
                        f"</tr>"
                    )
                return row_html

            # Greedy pairing: for each reference interval, find the best matching
            # candidate interval (same corp AND overlapping in time). This correctly
            # highlights overlaps when a character has multiple intervals for the
            # same corp (e.g. was in TTB in 2023 and again in 2026).
            used_candidates = set()
            pairs = []  # (ref_entry, cand_entry, sort_key)
            for ref_entry in reference_intervals_desc:
                ref_corp_id, ref_start, ref_end = ref_entry
                ref_end_eff = ref_end or now
                best_idx = None
                best_diff = None
                for cand_idx, cand_entry in enumerate(candidate_intervals_desc):
                    if cand_idx in used_candidates or cand_entry[0] != ref_corp_id:
                        continue
                    cand_end_eff = cand_entry[2] or now
                    overlap_start = max(ref_start, cand_entry[1])
                    overlap_end = min(ref_end_eff, cand_end_eff)
                    if overlap_start >= overlap_end:
                        # Same corp but not overlapping in time; don't pair, so the
                        # candidate remains available for a later reference interval
                        # that actually overlaps.
                        continue
                    diff = abs(ref_start - cand_entry[1])
                    if best_idx is None or diff < best_diff:
                        best_idx = cand_idx
                        best_diff = diff
                if best_idx is not None:
                    used_candidates.add(best_idx)
                    cand_entry = candidate_intervals_desc[best_idx]
                    pairs.append((ref_entry, cand_entry, max(ref_start, cand_entry[1])))
                else:
                    pairs.append((ref_entry, None, ref_start))
            for cand_idx, cand_entry in enumerate(candidate_intervals_desc):
                if cand_idx not in used_candidates:
                    pairs.append((None, cand_entry, cand_entry[1]))
            pairs.sort(key=lambda x: x[2], reverse=True)
            table_rows = [_render_row(ref, cand) for ref, cand, _ in pairs]
            if not table_rows:
                table_rows.append('<tr><td colspan="2" class="text-muted">No corp-history rows to display.</td></tr>')

            return (
                '<table class="table table-sm table-striped table-hover mb-0 mt-2" '
                'style="--bs-table-color:#f8f9fa;--bs-table-bg:#343a40;--bs-table-striped-color:#f8f9fa;--bs-table-striped-bg:#3e4651;--bs-table-hover-color:#ffffff;--bs-table-hover-bg:#4a5563;">'
                f"<thead><tr><th>{reference_name}</th><th>{character_name}</th></tr></thead>"
                f"<tbody>{''.join(table_rows)}</tbody>"
                "</table>"
            )

        match_summaries = []
        total_candidate_score = 0
        for item in matched_candidates:
            candidate_id = item["candidate_id"]
            character_name = resolved.get(candidate_id) or str(candidate_id)
            sources_str = ", ".join(sorted(item["sources"]))
            winner = item["winner"]
            total_candidate_score += winner["rule_score"]

            candidate_killmail_entries = [(kid, killmail_dates.get(kid)) for kid in killmail_links.get(candidate_id, [])]
            with_date = [(kid, kt) for kid, kt in candidate_killmail_entries if kt]
            without_date = [(kid, kt) for kid, kt in candidate_killmail_entries if not kt]
            with_date.sort(key=lambda x: x[1], reverse=True)
            sorted_killmails = with_date + without_date
            last_activity = with_date[0][1].strftime("%Y-%m-%d %H:%M") if with_date else "Unknown"
            last_activity_html = f'<p class="mb-1"><strong>Last zKill activity:</strong> {last_activity}</p>'
            killmail_html = ""
            if "killmail" in item["sources"] and sorted_killmails:
                lines = "".join(
                    f'<li>{kt.strftime("%Y-%m-%d %H:%M") if kt else "unknown date"} &mdash; <a href="https://zkillboard.com/kill/{kid}/" target="_blank" rel="noopener noreferrer">{kid}</a></li>'
                    for kid, kt in sorted_killmails
                )
                killmail_html = f'<p class="mb-1"><strong>Killmail links:</strong></p><ul class="small mb-0">{lines}</ul>'

            tab_group_id = f"alt-overlap-beta-{audit_run.id}-{candidate_id}"
            tab_buttons = []
            tab_panels = []
            sorted_refs = sorted(
                item["references"],
                key=lambda row: str(resolved_refs.get(row["reference_id"]) or row["reference_id"]).casefold(),
            )
            for tab_idx, ref_data in enumerate(sorted_refs):
                ref_id = ref_data["reference_id"]
                ref_name = resolved_refs.get(ref_id) or str(ref_id)
                is_active = tab_idx == 0
                is_winner = ref_id == winner["reference_id"]
                tab_id = f"{tab_group_id}-tab-{tab_idx}"
                pane_id = f"{tab_group_id}-pane-{tab_idx}"
                active_class = " btn-primary active" if is_active else " btn-secondary"
                selected = "true" if is_active else "false"
                winner_badge = " ★" if is_winner else ""
                tab_buttons.append(
                    f'<button class="btn btn-sm me-1{active_class}" id="{tab_id}" '
                    f'type="button" role="tab" data-tab-group="{tab_group_id}" data-tab-pane="{pane_id}" '
                    f'aria-controls="{pane_id}" aria-selected="{selected}">{ref_name}{winner_badge}</button>'
                )
                rule_label = ref_data["rule_name"].replace("_", " ").upper()
                reference_grid = _render_reference_grid(
                    character_name=character_name,
                    reference_name=ref_name,
                    reference_intervals=ref_data["reference_intervals"],
                    candidate_intervals=ref_data["candidate_intervals"],
                )
                pane_class = "tab-pane active" if is_active else "tab-pane"
                winner_label = ' <span class="badge text-bg-success">Used for score</span>' if is_winner else ""
                tab_panels.append(
                    f'<div class="{pane_class}" id="{pane_id}" role="tabpanel" aria-labelledby="{tab_id}" style="display: {"block" if is_active else "none"};">'
                    f'<p class="mb-1"><strong>{rule_label}</strong> score: {ref_data["rule_score"]} '
                    f'({ref_data["qualifying_count"]} qualifying non-NPC corp{"s" if ref_data["qualifying_count"] != 1 else ""})'
                    f"{winner_label}</p>"
                    f"{reference_grid}</div>"
                )

            notes = f'''<div class="small">
  <p class="mb-1"><strong>Shared via:</strong> {sources_str}</p>
  <p class="mb-1"><strong>Selected score:</strong> {winner["rule_score"]} ({winner["rule_name"].replace("_", " ").upper()} from {resolved_refs.get(winner["reference_id"]) or winner["reference_id"]})</p>
  {last_activity_html}
  {killmail_html}
  <div class="mt-2">
    <p class="mb-1"><strong>Shared overlaps by character:</strong></p>
    <div class="btn-group mb-2" id="{tab_group_id}" role="tablist">{"".join(tab_buttons)}</div>
    <div class="tab-content" id="{tab_group_id}-content">{"".join(tab_panels)}</div>
  </div>
</div>'''

            all_overlap_rows = [overlap for ref_data in item["references"] for overlap in ref_data["overlaps"]]
            first_seen = min(overlap["candidate_start"] for overlap in all_overlap_rows)
            last_seen = max((overlap["candidate_end"] or now) for overlap in all_overlap_rows)
            AuditRelationshipCounterparty.objects.create(
                audit_run=audit_run,
                counterparty_type=AuditRelationshipCounterparty.COUNTERPARTY_POSSIBLE_ALT,
                character_id=candidate_id,
                character_name=character_name,
                total_amount=Decimal("0"),
                event_count=winner["qualifying_count"],
                first_seen=first_seen,
                last_seen=last_seen,
                notes=notes,
            )

            by_ref_summary = ", ".join(
                f'{resolved_refs.get(ref_data["reference_id"]) or ref_data["reference_id"]}: {ref_data["rule_name"].upper()}={ref_data["rule_score"]}'
                for ref_data in sorted_refs
            )
            match_summaries.append(
                f'{character_name}: selected {winner["rule_name"].upper()}={winner["rule_score"]} from {resolved_refs.get(winner["reference_id"]) or winner["reference_id"]}; refs [{by_ref_summary}]'
            )

        self._create_finding(
            audit_run,
            AuditFinding.TYPE_UNDISCLOSED_ALT_CORPS,
            AuditFinding.SEVERITY_HIGH,
            "Possible associates with similar corporation history",
            f"{len(matched_candidates)} observed possible associates matched beta corp-history overlap rules with {target_name}.",
            total_candidate_score,
            evidence=[
                ("possible_alt_characters", "; ".join(match_summaries)),
                ("beta_overlap_total_score", str(total_candidate_score)),
            ],
        )
        return {"score": total_candidate_score, "summary": "undisclosed_alts"}