from decimal import Decimal
import json

from django.db import models

from ..models import AuditFinding, AuditRun, AuditTarget
from .audit_analysis.alt import AltMixin
from .audit_analysis.awox import AwoxDetectionMixin
from .audit_analysis.base import AuditResult, BaseAuditMixin
from .audit_analysis.blacklist import BlacklistMixin
from .audit_analysis.capital_ships import CapitalShipMixin
from .audit_analysis.collusion import CollusionDetectionMixin
from .audit_analysis.corp_history import CorpHistoryMixin
from .audit_analysis.enemy import EnemyDetectionMixin
from .audit_analysis.financial import FinancialMixin
from .audit_analysis.plus_ten import PlusTenMixin
from .esi_client import EsiClient
from .janice_client import JaniceClient
from .memberaudit_adapter import MemberAuditAdapter
from .zkill_client import ZkillClient


class AuditEngine(BaseAuditMixin, CorpHistoryMixin, EnemyDetectionMixin, CollusionDetectionMixin, AwoxDetectionMixin, PlusTenMixin, FinancialMixin, BlacklistMixin, AltMixin, CapitalShipMixin):

    def __init__(self, policy, progress_callback=None, policy_overrides=None):
        self.policy = policy
        overrides = policy_overrides or {}
        self._audit_options = overrides.pop("__audit_options__", {}) or {}
        self._apply_policy_overrides(overrides)
        self.esi = EsiClient(throttle_seconds=float(policy.esi_throttle_seconds))
        self.zkill = ZkillClient(throttle_seconds=float(policy.zkill_throttle_seconds))
        self.janice = JaniceClient()
        self.progress_callback = progress_callback
        self._load_financial_exceptions()

    def _audit_option_enabled(self, name, default=True):
        return bool(self._audit_options.get(name, default))

    def _apply_policy_overrides(self, overrides):
        if not overrides:
            return
        for name, value in overrides.items():
            if not hasattr(self.policy, name) or value is None:
                continue
            try:
                field = self.policy._meta.get_field(name)
            except Exception:
                continue
            if isinstance(field, models.DecimalField):
                value = Decimal(str(value))
            elif isinstance(field, (models.IntegerField, models.PositiveIntegerField)):
                value = int(value)
            setattr(self.policy, name, value)

    def _progress(self, value, message, details=None):
        if callable(self.progress_callback):
            self.progress_callback(value, 100, message, details)

    def run(self, audit_run: AuditRun) -> AuditResult:
        target = audit_run.target
        if target.target_type == target.TARGET_INDIVIDUAL:
            return self._run_individual(audit_run)
        return self._run_corporation(audit_run)

    def _run_individual(self, audit_run: AuditRun) -> AuditResult:
        target = audit_run.target
        self._progress(10, "Resolving character profile")
        user = MemberAuditAdapter.find_user_by_main_name(target.character_name)

        character_id = target.character_id
        snapshot = MemberAuditAdapter.get_character_snapshot(
            character_name=target.character_name,
            character_id=character_id,
            user=user,
        )

        if not character_id and snapshot and snapshot.get("character_id"):
            character_id = snapshot.get("character_id")
        if not character_id:
            character_id = self.esi.resolve_character_name(target.character_name)
            if not character_id:
                raise ValueError(f"Character '{target.character_name}' could not be resolved")

        if not snapshot:
            snapshot = MemberAuditAdapter.get_character_snapshot(character_id=character_id, user=user)
        character = snapshot or self.esi.get_character(character_id)

        update_fields = []
        if target.character_id != character_id:
            target.character_id = character_id
            update_fields.append("character_id")
        corp_id = character.get("corporation_id")
        if corp_id and target.corp_id != corp_id:
            target.corp_id = corp_id
            update_fields.append("corp_id")
        if update_fields:
            target.save(update_fields=update_fields)

        # Resolve the owning user from the character id so audits of alts
        # still correctly look up the full declared alt set.
        user = MemberAuditAdapter.get_user_for_character_id(character_id) or user

        character_ids = {int(character_id)} | MemberAuditAdapter.get_user_declared_character_ids(user)
        character_ids.discard(None)
        ordered_character_ids = sorted(character_ids)
        unit_count = max(len(ordered_character_ids), 1)
        character_name_map = self.esi.resolve_names(ordered_character_ids) if ordered_character_ids else {}

        alt_ids = set(ordered_character_ids) - {character_id}
        per_alt_state = {alt_id: {"combat": False, "plus_ten": False, "wallet": False, "contracts": False, "corp_history": False} for alt_id in alt_ids}

        def _per_alt_progress_details():
            refs = []
            for alt_id in sorted(alt_ids):
                state = per_alt_state[alt_id]
                completed = sum(1 for v in state.values() if v)
                refs.append({
                    "id": alt_id,
                    "name": character_name_map.get(alt_id) or str(alt_id),
                    "total": 5,
                    "completed": completed,
                    "done": completed >= 5,
                })
            return {"per_alt_progress": refs}

        def _range_progress(start, end, completed, total, message, details=None):
            safe_total = max(int(total or 0), 1)
            safe_completed = max(0, min(int(completed or 0), safe_total))
            value = start + int(((end - start) * safe_completed) / safe_total)
            if details is None:
                details = _per_alt_progress_details()
            self._progress(value, message, details)

        score = 0
        summary_parts = []

        self._progress(25, "Analyzing corporation history")
        corp_history = MemberAuditAdapter.get_character_corp_history(
            character_name=target.character_name,
            character_id=character_id,
            user=user,
        )
        if not corp_history:
            corp_history = self.esi.get_character_corp_history(character_id)
        hop_windows = self._find_hop_windows(corp_history)
        if hop_windows:
            all_corp_ids = set()
            for w in hop_windows:
                for row in w:
                    corp_id = row.get("corporation_id")
                    if corp_id:
                        all_corp_ids.add(corp_id)
            names = self.esi.resolve_names(all_corp_ids)

            evidence = []
            for idx, w in enumerate(reversed(hop_windows), start=1):
                first = w[0]["start_date"]
                last = w[-1]["start_date"]
                days = (last - first).days
                count = len(w)

                corp_entries = []
                for row in reversed(w):
                    corp_id = row["corporation_id"]
                    corp_name = names.get(corp_id) or str(corp_id)
                    logo_url = MemberAuditAdapter._corp_logo_url(corp_id)
                    corp_entries.append(
                        f'<a href="https://zkillboard.com/corporation/{corp_id}/" '
                        f'target="_blank" rel="noopener" class="d-inline-flex align-items-center gap-1 me-2">'
                        f'<img src="{logo_url}" alt="" width="24" height="24" class="rounded"> '
                        f'{corp_name}</a>'
                    )

                value = (
                    f"<strong>Window {idx}</strong>: {count} corp{'s' if count != 1 else ''} "
                    f"in {days} day{'s' if days != 1 else ''} "
                    f"({first.strftime('%Y-%m-%d')} to {last.strftime('%Y-%m-%d')}): "
                    f"{''.join(corp_entries)}"
                )
                evidence.append(("hop_window", value))

            self._create_finding(
                audit_run,
                AuditFinding.TYPE_FLIGHT_RISK,
                AuditFinding.SEVERITY_HIGH,
                "High corp hopping frequency",
                f"{len(hop_windows)} instance(s) of rapid corporation hopping detected.",
                20,
                evidence=evidence,
            )
            score += 20
            summary_parts.append("corp hopping")

        self._progress(40, "Checking enemy and affiliation links")
        enemy_match = self._has_enemy_connections(character, corp_history, character_id=character_id)
        if enemy_match:
            details = enemy_match.get("reason") or (
                f"Character has a direct connection to enemy {enemy_match['entity_type']}: "
                f"{enemy_match['name']}."
            )
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_ENEMY_CONNECTION,
                AuditFinding.SEVERITY_CRITICAL,
                "Connection to configured enemy IDs",
                details,
                45,
                evidence=[("enemy_connection", json.dumps(enemy_match))],
            )
            score += 45
            summary_parts.append("enemy connection")

        _range_progress(45, 55, 0, unit_count, "Analyzing combat behavior")
        all_kills = []
        seen_kill_ids = set()
        max_attackers = int(self.policy.killmail_max_attacker_count or 0)
        kill_pages = int(self.policy.zkill_kill_pages)
        for idx, char_id in enumerate(ordered_character_ids, start=1):
            for kill in self.zkill.get_recent_kills(char_id, max_pages=kill_pages):
                kill_id = kill.get("killmail_id")
                if not kill_id or kill_id in seen_kill_ids:
                    continue
                attackers = kill.get("attackers") or []
                if not any(attacker.get("character_id") == char_id for attacker in attackers):
                    continue
                if max_attackers > 0 and len(attackers) > max_attackers:
                    continue
                seen_kill_ids.add(kill_id)
                kill["__source_character_id"] = char_id
                all_kills.append(kill)
            if char_id in per_alt_state:
                per_alt_state[char_id]["combat"] = True
            char_name = character_name_map.get(char_id) or str(char_id)
            _range_progress(45, 55, idx, unit_count, f"Analyzing combat behavior for {char_name} ({idx}/{unit_count})")

        self._progress(48, "Inventorying capital/super/titan ship usage")
        if self._audit_option_enabled("check_capital_observations"):
            self._record_capital_ship_observations(
                audit_run=audit_run,
                character_ids=ordered_character_ids,
                character_name_map=character_name_map,
            )
        self._progress(49, "Inventorying capital ship ownership from MemberAudit")

        collusion_result = self._has_enemy_collusion_pattern(character_id, all_kills)
        if collusion_result:
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_SPY_ACTIVITY,
                AuditFinding.SEVERITY_MEDIUM,
                "Enemy collusion activity detected",
                collusion_result["details"],
                20,
                evidence=collusion_result["evidence"],
            )
            score += 20
            summary_parts.append("enemy collusion")

        awox_result = None
        if self._audit_option_enabled("check_awox"):
            awox_result = self._detect_awox(
                audit_run,
                character_id,
                ordered_character_ids,
                character_name_map,
                all_kills,
            )
        if awox_result:
            severity_map = {
                "critical": AuditFinding.SEVERITY_CRITICAL,
                "high": AuditFinding.SEVERITY_HIGH,
                "medium": AuditFinding.SEVERITY_MEDIUM,
                "low": AuditFinding.SEVERITY_LOW,
            }
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_AWOX,
                severity_map.get(awox_result["severity"], AuditFinding.SEVERITY_MEDIUM),
                "Awox / friendly fire detected",
                awox_result["details"],
                awox_result["score"],
                evidence=awox_result["evidence"],
            )
            score += awox_result["score"]
            summary_parts.append("awox / friendly fire")

        plus_ten_result = self._record_plus_ten_counterparties(
            audit_run=audit_run,
            character_ids=ordered_character_ids,
            kills=all_kills,
            progress_callback=lambda completed, total, progress_char_id=None: (
                per_alt_state[progress_char_id].update({"plus_ten": True})
                if progress_char_id in per_alt_state
                else None,
                _range_progress(
                    55,
                    66,
                    completed,
                    total,
                    (
                        f"Evaluating +10 contacts for "
                        f"{character_name_map.get(progress_char_id) or progress_char_id} ({completed}/{total})"
                        if progress_char_id is not None
                        else f"Evaluating +10 contacts ({completed}/{total})"
                    ),
                ),
            )[1],
        )
        if plus_ten_result:
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_OTHER,
                AuditFinding.SEVERITY_HIGH,
                "High-standing contacts linked to enemy/blacklist activity",
                plus_ten_result["details"],
                20,
                evidence=plus_ten_result["evidence"],
            )
            score += 20
            score += 10 * plus_ten_result.get("blacklist_adjacent_count", 0)
            summary_parts.append("risky +10 contacts")

        self._progress(70, "Correlating declared and undisclosed alts")
        undisclosed_alts = []
        if self._audit_option_enabled("check_undisclosed_alts"):
            undisclosed_alts = self._find_undisclosed_alts(user)
        if undisclosed_alts:
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_UNDISCLOSED_ALTS,
                AuditFinding.SEVERITY_HIGH,
                "Potential undisclosed alt characters",
                "Characters linked in auth context that are not declared as expected for this main.",
                100,
                evidence=[("characters", ", ".join(undisclosed_alts))],
            )
            score += 100
            summary_parts.append("undisclosed alts")

        _range_progress(66, 78, 0, unit_count, "Evaluating wallet and transactional signals")
        missing_scopes, tx_score = self._process_transactional_signals(
            audit_run,
            ordered_character_ids,
            progress_callback=lambda completed, total, progress_char_id=None: (
                per_alt_state[progress_char_id].update({"wallet": True})
                if progress_char_id in per_alt_state
                else None,
                _range_progress(
                    66,
                    78,
                    completed,
                    total,
                    (
                        f"Evaluating wallet and transactional signals for "
                        f"{character_name_map.get(progress_char_id) or progress_char_id} ({completed}/{total})"
                        if progress_char_id is not None
                        else f"Evaluating wallet and transactional signals ({completed}/{total})"
                    ),
                ),
            )[1],
        )
        score += tx_score

        _range_progress(78, 88, 0, unit_count, "Checking free item-exchange contracts")
        contract_missing, contract_score = self._process_contract_signals(
            audit_run,
            ordered_character_ids,
            progress_callback=lambda completed, total, progress_char_id=None: (
                per_alt_state[progress_char_id].update({"contracts": True})
                if progress_char_id in per_alt_state
                else None,
                _range_progress(
                    78,
                    88,
                    completed,
                    total,
                    (
                        f"Checking free item-exchange contracts for "
                        f"{character_name_map.get(progress_char_id) or progress_char_id} ({completed}/{total})"
                        if progress_char_id is not None
                        else f"Checking free item-exchange contracts ({completed}/{total})"
                    ),
                ),
            )[1],
        )
        missing_scopes = sorted(set(missing_scopes) | set(contract_missing))
        score += contract_score

        self._progress(88, "Checking allianceauth-blacklist matches")
        main_or_alt_blacklist_hits, interaction_blacklist_hits = self._check_blacklist_signals(
            audit_run=audit_run,
            character_id=character_id,
            character_name=target.character_name,
            user=user,
            kills=all_kills,
        )

        all_blacklist_ids = main_or_alt_blacklist_hits | interaction_blacklist_hits
        resolved_blacklist = self.esi.resolve_names(all_blacklist_ids) if all_blacklist_ids else {}

        if main_or_alt_blacklist_hits:
            named = ", ".join(resolved_blacklist.get(i) or str(i) for i in sorted(main_or_alt_blacklist_hits))
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_OTHER,
                AuditFinding.SEVERITY_CRITICAL,
                "Main or declared alt appears on blacklist",
                f"Main or declared alt appears on blacklist: {named}",
                60,
                evidence=[
                    ("blacklisted_ids", ", ".join(str(x) for x in sorted(main_or_alt_blacklist_hits))),
                    ("blacklisted_names", named),
                ],
            )
            score += 60
            summary_parts.append("blacklisted character")

        if interaction_blacklist_hits:
            named = ", ".join(resolved_blacklist.get(i) or str(i) for i in sorted(interaction_blacklist_hits))
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_OTHER,
                AuditFinding.SEVERITY_HIGH,
                "Contacts/interactions include blacklisted characters",
                f"Observed contacts or interaction counterparties include allianceauth-blacklist entries: {named}",
                35,
                evidence=[
                    ("interaction_blacklisted_ids", ", ".join(str(x) for x in sorted(interaction_blacklist_hits))),
                    ("interaction_blacklisted_names", named),
                ],
            )
            score += 35
            summary_parts.append("blacklisted interactions")

        alt_corp_result = self._detect_alt_corp_history(
            audit_run,
            character_id,
            user,
            all_kills,
            progress_callback=lambda completed, total, candidate_id, details: (
                [
                    per_alt_state[ref["id"]].update({"corp_history": True})
                    for ref in (details or {}).get("corphistory_references", [])
                    if ref.get("done") and ref.get("id") in per_alt_state
                ],
                _range_progress(
                    90,
                    95,
                    completed,
                    total,
                    f"Comparing corp histories of possible associates ({completed}/{total})",
                ),
            )[1],
        )
        if alt_corp_result:
            score += alt_corp_result["score"]
            summary_parts.append(alt_corp_result["summary"])

        self._progress(95, "Finalizing risk assessment")
        risk_level = self._risk_level(score)
        summary = "No major findings" if not summary_parts else ", ".join(summary_parts)
        return AuditResult(
            risk_score=score,
            risk_level=risk_level,
            summary=summary,
            missing_scopes=missing_scopes,
        )

    def _run_corporation(self, audit_run: AuditRun) -> AuditResult:
        target = audit_run.target
        self._progress(20, "Loading corporation profile")
        if not target.corp_id:
            raise ValueError("Corporation ID is required for corporation audits")

        if not target.corp_name:
            corp = self.esi.get_corporation(target.corp_id)
            target.corp_name = corp.get("name", target.corp_name)
            target.save(update_fields=["corp_name"])

        score = 0
        summary_parts = []
        child_run_ids = []

        self._progress(45, "Resolving corporation mains")
        main_ids = MemberAuditAdapter.get_main_character_ids_for_corp(target.corp_id)
        if main_ids:
            for char_id, char_name in main_ids:
                child_target, _ = AuditTarget.objects.get_or_create(
                    target_type=AuditTarget.TARGET_INDIVIDUAL,
                    character_id=char_id,
                    defaults={
                        "character_name": char_name,
                        "corp_id": target.corp_id,
                        "corp_name": target.corp_name,
                    },
                )
                child_run = AuditRun.objects.create(
                    target=child_target,
                    parent_run=audit_run,
                    started_by=audit_run.started_by,
                    automated=audit_run.automated,
                    status=AuditRun.STATUS_QUEUED,
                )
                child_run_ids.append(child_run.id)
            summary_parts.append(f"spawned {len(main_ids)} individual audits")
        else:
            summary_parts.append("no known corporation mains")

        self._progress(65, "Checking enemy registry matches")
        if self._is_enemy_corp(target.corp_id):
            self._create_finding(
                audit_run,
                AuditFinding.TYPE_ENEMY_CONNECTION,
                AuditFinding.SEVERITY_CRITICAL,
                "Corporation matches configured enemy corp",
                "Audited corporation appears in the enemy corporation list.",
                60,
            )
            score += 60
            summary_parts.append("enemy corp")

        self._progress(95, "Finalizing risk assessment")
        return AuditResult(
            risk_score=score,
            risk_level=self._risk_level(score),
            summary="No major findings" if not summary_parts else ", ".join(summary_parts),
            missing_scopes=[],
            child_run_ids=child_run_ids,
        )