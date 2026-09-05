import json
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from ...models import AuditRelationshipCounterparty
from ..blacklist_adapter import BlacklistAdapter
from ..memberaudit_adapter import MemberAuditAdapter

class PlusTenMixin:

    def _record_plus_ten_counterparties(self, audit_run, character_ids, kills, progress_callback=None):
        ordered_character_ids = list(character_ids)
        character_id_set = set(ordered_character_ids)
        merged = {}
        total_chars = max(len(ordered_character_ids), 1)
        for idx, char_id in enumerate(ordered_character_ids, start=1):
            standings = MemberAuditAdapter.get_contact_character_standings(char_id)
            for contact_id, standing in (standings or {}).items():
                try:
                    contact_id_int = int(contact_id)
                    standing_value = float(standing)
                except (TypeError, ValueError):
                    continue
                if standing_value < 10:
                    continue
                entry = merged.setdefault(contact_id_int, {"standing": standing_value, "source_chars": set()})
                entry["source_chars"].add(char_id)
                if standing_value > entry["standing"]:
                    entry["standing"] = standing_value
            if callable(progress_callback):
                progress_callback(idx, total_chars, char_id)

        if not merged:
            return None

        plus_ten_ids = set(merged.keys()) - character_id_set
        if not plus_ten_ids:
            return None

        # Enemy entity sets (cached per run via base mixin).
        enemy_character_ids, enemy_corp_ids, enemy_alliance_ids = self._get_enemy_sets()

        blacklisted_ids = set()
        if BlacklistAdapter.is_available():
            blacklisted_ids = BlacklistAdapter.get_blacklisted_character_ids(plus_ten_ids)
        blacklist_reasons = BlacklistAdapter.get_blacklist_reasons(blacklisted_ids)
        blacklist_adjacent_count = 0

        names = self.esi.resolve_names(plus_ten_ids)
        source_names = self.esi.resolve_names(character_id_set)
        affiliation_cache = {}

        def _affiliations(entity_id):
            if entity_id in affiliation_cache:
                return affiliation_cache[entity_id]
            corp_id = None
            alliance_id = None
            try:
                char = self.esi.get_character(entity_id)
                corp_id = char.get("corporation_id")
                alliance_id = char.get("alliance_id")
            except Exception:
                pass
            affiliation_cache[entity_id] = (corp_id, alliance_id)
            return affiliation_cache[entity_id]

        killmail_links = {contact_id: [] for contact_id in plus_ten_ids}
        if kills:
            now = timezone.now()

            # Pre-collect all participant IDs across all relevant kills so we
            # can do a single batched blacklist lookup instead of one query
            # per killmail.
            all_participant_ids = set()
            relevant_kills = []
            for kill in kills:
                kill_time = self.esi.parse_esi_time(kill.get("killmail_time"))
                if not kill_time or (now - kill_time).days > 180:
                    continue

                participants = []
                victim = kill.get("victim") or {}
                if victim.get("character_id"):
                    participants.append(victim)
                participants.extend(kill.get("attackers") or [])

                participant_ids = {
                    (item or {}).get("character_id")
                    for item in participants
                    if (item or {}).get("character_id")
                }
                contact_ids_in_kill = plus_ten_ids.intersection(participant_ids)
                if not contact_ids_in_kill:
                    continue

                relevant_kills.append((kill, participants, participant_ids, contact_ids_in_kill))
                all_participant_ids |= participant_ids

            # One batched blacklist query for all participants across all kills.
            all_blacklisted_participants = set()
            if all_participant_ids and BlacklistAdapter.is_available():
                all_blacklisted_participants = BlacklistAdapter.get_blacklisted_character_ids(
                    all_participant_ids
                )

            for kill, participants, participant_ids, contact_ids_in_kill in relevant_kills:
                enemy_participant_present = False
                for participant in participants:
                    participant = participant or {}
                    participant_id = participant.get("character_id")
                    if participant_id and participant_id in enemy_character_ids:
                        enemy_participant_present = True
                        break
                    corp_id = participant.get("corporation_id")
                    alliance_id = participant.get("alliance_id")
                    if corp_id and corp_id in enemy_corp_ids:
                        enemy_participant_present = True
                        break
                    if alliance_id and alliance_id in enemy_alliance_ids:
                        enemy_participant_present = True
                        break

                for contact_id in contact_ids_in_kill:
                    has_killmail_reason = enemy_participant_present
                    if not has_killmail_reason:
                        for participant_id in participant_ids:
                            if participant_id != contact_id and participant_id in all_blacklisted_participants:
                                has_killmail_reason = True
                                break
                    if has_killmail_reason and kill.get("killmail_id"):
                        killmail_links[contact_id].append(str(kill.get("killmail_id")))

        created_contacts = []
        matched_blacklist_ids = []
        matched_enemy_ids = []
        matched_killmail_ids = []
        counterparties_to_create = []

        for contact_id in sorted(plus_ten_ids):
            in_blacklist = contact_id in blacklisted_ids
            corp_id, alliance_id = _affiliations(contact_id)
            in_enemy_entity = (
                contact_id in enemy_character_ids
                or (corp_id in enemy_corp_ids if corp_id else False)
                or (alliance_id in enemy_alliance_ids if alliance_id else False)
            )
            killmail_ids = killmail_links.get(contact_id, [])
            if not (in_blacklist or in_enemy_entity or killmail_ids):
                continue

            if in_blacklist:
                matched_blacklist_ids.append(contact_id)
                blacklist_adjacent_count += 1
            if in_enemy_entity:
                matched_enemy_ids.append(contact_id)
            if killmail_ids:
                matched_killmail_ids.extend(killmail_ids)

            source_chars = merged[contact_id]["source_chars"]
            source_name_list = sorted(str(source_names.get(s) or s) for s in source_chars)
            notes = (
                f"+{merged[contact_id]['standing']:g} standing; "
                f"source alts: {', '.join(source_name_list)}; "
                f"{len(killmail_ids)} related killmails"
            )
            reason = blacklist_reasons.get(contact_id)
            if reason:
                notes += f"; blacklist reason: {reason}"

            counterparties_to_create.append(AuditRelationshipCounterparty(
                audit_run=audit_run,
                counterparty_type=AuditRelationshipCounterparty.COUNTERPARTY_PLUS_TEN,
                character_id=contact_id,
                character_name=names.get(contact_id) or str(contact_id),
                total_amount=Decimal("0"),
                event_count=max(1, len(killmail_ids)),
                notes=notes,
            ))
            created_contacts.append(contact_id)

        if counterparties_to_create:
            AuditRelationshipCounterparty.objects.bulk_create(counterparties_to_create, batch_size=500)

        if not created_contacts:
            return None

        unique_killmail_ids = sorted(set(matched_killmail_ids), key=lambda x: int(x) if str(x).isdigit() else x)
        return {
            "details": (
                f"{len(created_contacts)} +10 contacts matched blacklist/enemy/killmail criteria; "
                f"{len(unique_killmail_ids)} related killmails were observed in the last 180 days."
            ),
            "evidence": [
                ("plus_ten_contact_ids", ", ".join(str(x) for x in created_contacts)),
                ("plus_ten_contact_standings", "; ".join(
                    f"{names.get(cid) or cid}: +{merged[cid]['standing']:g}"
                    for cid in created_contacts
                )),
                ("plus_ten_source_alts", "; ".join(
                    f"{names.get(cid) or cid} (from {', '.join(sorted(str(source_names.get(s) or s) for s in merged[cid]['source_chars']))})"
                    for cid in created_contacts
                )),
                ("plus_ten_blacklist_contact_ids", ", ".join(str(x) for x in sorted(matched_blacklist_ids)) or "none"),
                ("plus_ten_enemy_entity_contact_ids", ", ".join(str(x) for x in sorted(matched_enemy_ids)) or "none"),
                ("plus_ten_relevant_killmail_ids", ", ".join(unique_killmail_ids[:50]) or "none"),
            ],
            "blacklist_adjacent_count": blacklist_adjacent_count,
        }