"""Awox (deliberate friendly-fire) detection.

Flags an audited character (main or declared alt) killing a friendly victim
(same corp/alliance at kill time, or blue-scouting where the attacker is in
an NPC corp but the main/other alts share corp/alliance with the victim)
with high kill ownership — including tackle-only contribution (warp
scrambler/disruptor/HIC infinipoint) and HIC pilots regardless of damage —
while strictly excluding large-fleet crossfire, whoring, structure-bash
kills, and throwaway-ship sparring.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from ...constants import (
    AWOX_HIGH_VALUE_VICTIM_GROUPS,
    AWOX_SCORE_CAP,
    AWOX_SUPER_CAPITAL_GROUPS,
    AWOX_TACKLE_MODULE_GROUPS,
    CAPSULE_GROUP_ID,
    HEAVY_INTERDICTOR_CRUISER_GROUP_ID,
    THROWAWAY_VICTIM_SHIP_GROUPS,
)
from ...models import EnemyEntity
from ..blacklist_adapter import BlacklistAdapter
from ..esi_client import EsiClient
from ..memberaudit_adapter import MemberAuditAdapter
from .capital_ships import CAPITAL_SHIP_GROUPS

KIND_LABELS = {
    "friendly_fire_damage": "Friendly Fire (Damage)",
    "friendly_fire_tackle": "Friendly Fire (Tackle)",
    "friendly_fire_hic": "Friendly Fire (HIC)",
    "blue_scouting_damage": "Blue Scouting (Damage)",
    "blue_scouting_tackle": "Blue Scouting (Tackle)",
    "blue_scouting_hic": "Blue Scouting (HIC)",
}


class AwoxDetectionMixin:
    def _detect_awox(self, audit_run, character_id, ordered_character_ids, character_name_map, all_kills):
        if not all_kills or not character_id:
            return None

        character_id_set = set(ordered_character_ids)
        min_damage_share = float(self.policy.awox_min_damage_share or Decimal("0"))
        lookback_days = int(self.policy.awox_lookback_days or 0)
        large_fleet_threshold = int(self.policy.awox_large_fleet_attacker_threshold or 0)
        solo_threshold = int(self.policy.awox_solo_attacker_threshold or 0)
        min_victim_value = Decimal(self.policy.awox_min_victim_value or Decimal("0"))
        blue_scouting_bonus = int(self.policy.awox_blue_scouting_bonus or 0)

        # Enemy/blacklist entity sets for crossfire detection.
        enemy_character_ids = set(
            EnemyEntity.objects.filter(
                entity_type=EnemyEntity.TYPE_CHARACTER,
                is_active=True,
            ).values_list("entity_id", flat=True)
        )
        enemy_corp_ids = set(
            EnemyEntity.objects.filter(
                entity_type=EnemyEntity.TYPE_CORP,
                is_active=True,
            ).values_list("entity_id", flat=True)
        )
        enemy_alliance_ids = set(
            EnemyEntity.objects.filter(
                entity_type=EnemyEntity.TYPE_ALLIANCE,
                is_active=True,
            ).values_list("entity_id", flat=True)
        )

        # NPC corp set (reuse the shared cache populated by corp_history).
        npc_corp_ids = cache.get("securityaudit:npc_corp_ids")
        if npc_corp_ids is None:
            try:
                npc_corp_ids = set(self.esi.get_npc_corporations())
            except Exception:
                npc_corp_ids = set()
            cache.set("securityaudit:npc_corp_ids", npc_corp_ids, 86400 * 7)

        # Affiliation cache for blue-scouting checks (char_id -> (corp_id, alliance_id)).
        affiliation_cache = {}

        def _affiliations(char_id):
            if char_id in affiliation_cache:
                return affiliation_cache[char_id]
            corp_id = None
            alliance_id = None
            try:
                char = self.esi.get_character(char_id)
                corp_id = char.get("corporation_id")
                alliance_id = char.get("alliance_id")
            except Exception:
                pass
            affiliation_cache[char_id] = (corp_id, alliance_id)
            return affiliation_cache[char_id]

        # Type info cache for the current run (group_id + name).
        type_info_cache = {}

        def _type_info(type_id):
            if type_id is None:
                return None
            try:
                type_id = int(type_id)
            except (TypeError, ValueError):
                return None
            if type_id in type_info_cache:
                return type_info_cache[type_id]
            info = self.esi.get_type_info(type_id)
            type_info_cache[type_id] = info
            return info

        def _type_group(type_id):
            info = _type_info(type_id)
            if info and info.get("group_id"):
                return int(info["group_id"])
            return None

        def _type_name(type_id):
            info = _type_info(type_id)
            if info and info.get("name"):
                return info["name"]
            return ""

        now = timezone.now()
        lookback_cutoff = now - timedelta(days=lookback_days) if lookback_days > 0 else None
        ninety_days_ago = now - timedelta(days=90)

        qualifying_kills = []

        for kill in all_kills:
            victim = kill.get("victim") or {}

            # 1. Structure exclusion — no character victim means it's a structure kill.
            victim_char_id = victim.get("character_id")
            if not victim_char_id:
                continue

            # 2. Find audited-character attacker entries and pick the
            # strongest *friendly* contributor on this mail.
            attackers = kill.get("attackers") or []
            audited_attackers = []
            for attacker in attackers:
                attacker = attacker or {}
                aid = attacker.get("character_id")
                if aid and aid in character_id_set:
                    audited_attackers.append(attacker)
            if not audited_attackers:
                continue

            # 3. Friendly-victim gate.
            # Skip self-kills across declared alts.
            if victim_char_id in character_id_set:
                continue

            friendly_candidates = []
            for attacker_entry in audited_attackers:
                attacker_char_id = attacker_entry.get("character_id")
                attacker_corp_id = attacker_entry.get("corporation_id")
                attacker_alliance_id = attacker_entry.get("alliance_id")

                friendly_path = None
                friendly_link_char_id = None
                friendly_link_type = None

                # Primary path: same corp or same alliance at kill time.
                if (
                    attacker_corp_id
                    and victim.get("corporation_id")
                    and attacker_corp_id == victim.get("corporation_id")
                ):
                    friendly_path = "direct"
                elif (
                    attacker_alliance_id
                    and victim.get("alliance_id")
                    and attacker_alliance_id == victim.get("alliance_id")
                ):
                    friendly_path = "direct"

                # Blue-scouting path: attacker in NPC corp + main/other alts
                # share corp/alliance with victim.
                if friendly_path is None and attacker_corp_id and attacker_corp_id in npc_corp_ids:
                    victim_corp_id = victim.get("corporation_id")
                    victim_alliance_id = victim.get("alliance_id")
                    for other_char_id in ordered_character_ids:
                        if other_char_id == attacker_char_id:
                            continue
                        other_corp_id, other_alliance_id = _affiliations(other_char_id)
                        if victim_corp_id and other_corp_id == victim_corp_id:
                            friendly_path = "blue_scouting"
                            friendly_link_char_id = other_char_id
                            friendly_link_type = "corporation"
                            break
                        if victim_alliance_id and other_alliance_id == victim_alliance_id:
                            friendly_path = "blue_scouting"
                            friendly_link_char_id = other_char_id
                            friendly_link_type = "alliance"
                            break

                if friendly_path is None:
                    continue

                damage_done = float(attacker_entry.get("damage_done") or 0)
                final_blow = bool(attacker_entry.get("final_blow"))
                friendly_candidates.append(
                    (
                        1 if final_blow else 0,
                        damage_done,
                        attacker_char_id or 0,
                        attacker_entry,
                        friendly_path,
                        friendly_link_char_id,
                        friendly_link_type,
                    )
                )

            if not friendly_candidates:
                continue
            _, _, _, attacker_entry, friendly_path, friendly_link_char_id, friendly_link_type = max(
                friendly_candidates
            )
            attacker_char_id = attacker_entry.get("character_id")
            friendly_attacker_entries = [candidate[3] for candidate in friendly_candidates]

            # 4. Throwaway-ship sparring exclusion.
            victim_ship_type_id = victim.get("ship_type_id")
            victim_ship_group_id = _type_group(victim_ship_type_id)
            zkb = kill.get("zkb") or {}
            zkb_value = Decimal(str(zkb.get("totalValue") or 0))
            if (
                victim_ship_group_id
                and victim_ship_group_id in THROWAWAY_VICTIM_SHIP_GROUPS
                and victim_ship_group_id != CAPSULE_GROUP_ID
                and zkb_value < min_victim_value
            ):
                continue

            # 5. Compute ownership and tackle context.
            # Treat declared main+alts as one audited entity for damage
            # ownership on a killmail. This avoids under-reporting when
            # multiple audited characters are on the same awox mail.
            damage_done = sum(
                float(entry.get("damage_done") or 0) for entry in friendly_attacker_entries
            )
            damage_taken = float(victim.get("damage_taken") or 0)
            damage_share = damage_done / damage_taken if damage_taken > 0 else 0.0
            final_blow = any(bool(entry.get("final_blow")) for entry in friendly_attacker_entries)
            attacker_count = len(attackers)
            weapon_type_id = attacker_entry.get("weapon_type_id")
            ship_type_id = attacker_entry.get("ship_type_id")
            weapon_group_id = _type_group(weapon_type_id)
            ship_group_id = _type_group(ship_type_id)

            # Determine if enemy/blacklist attackers are present on the mail.
            enemy_attackers_present = False
            all_attacker_ids = set()
            for a in attackers:
                a = a or {}
                aid = a.get("character_id")
                if aid:
                    all_attacker_ids.add(aid)
                a_corp = a.get("corporation_id")
                a_alliance = a.get("alliance_id")
                if aid and aid in enemy_character_ids:
                    enemy_attackers_present = True
                if a_corp and a_corp in enemy_corp_ids:
                    enemy_attackers_present = True
                if a_alliance and a_alliance in enemy_alliance_ids:
                    enemy_attackers_present = True
            if not enemy_attackers_present and BlacklistAdapter.is_available():
                blacklisted_on_mail = BlacklistAdapter.get_blacklisted_character_ids(all_attacker_ids)
                if blacklisted_on_mail:
                    enemy_attackers_present = True

            # 6. Determine qualification.
            is_tackle = any(
                (_type_group(entry.get("weapon_type_id")) in AWOX_TACKLE_MODULE_GROUPS)
                for entry in friendly_attacker_entries
            )
            is_hic = any(
                (_type_group(entry.get("ship_type_id")) == HEAVY_INTERDICTOR_CRUISER_GROUP_ID)
                for entry in friendly_attacker_entries
            )
            has_damage_ownership = (damage_share >= min_damage_share) or final_blow

            if not (has_damage_ownership or is_tackle or is_hic):
                continue  # whoring exclusion

            # 7. Generalized large-fleet crossfire exclusion.
            # Blue-scouting kills bypass this exclusion.
            if (
                friendly_path != "blue_scouting"
                and large_fleet_threshold > 0
                and attacker_count >= large_fleet_threshold
                and enemy_attackers_present
                and damage_share < min_damage_share
                and not final_blow
                and not is_tackle
                and not is_hic
            ):
                continue

            # 8. Record qualifying awox kill.
            # Determine kind.
            if friendly_path == "blue_scouting":
                if is_hic:
                    kind = "blue_scouting_hic"
                elif is_tackle:
                    kind = "blue_scouting_tackle"
                else:
                    kind = "blue_scouting_damage"
            else:
                if is_hic:
                    kind = "friendly_fire_hic"
                elif is_tackle:
                    kind = "friendly_fire_tackle"
                else:
                    kind = "friendly_fire_damage"

            # Check recency.
            kill_time = EsiClient.parse_esi_time(kill.get("killmail_time"))
            if lookback_cutoff and kill_time and kill_time < lookback_cutoff:
                continue
            if kill_time and kill_time < ninety_days_ago:
                recency_weight = 0.5
            else:
                recency_weight = 1.0

            # Score this kill.
            if final_blow and damage_share >= min_damage_share:
                base = 25
            elif final_blow or damage_share >= min_damage_share:
                base = 18
            else:
                base = 15  # tackle or HIC override

            # High-value victim bonus.
            high_value_bonus = 0
            if victim_ship_group_id:
                if victim_ship_group_id in AWOX_SUPER_CAPITAL_GROUPS:
                    high_value_bonus = 25
                elif victim_ship_group_id in AWOX_HIGH_VALUE_VICTIM_GROUPS or victim_ship_group_id in CAPITAL_SHIP_GROUPS:
                    high_value_bonus = 15

            solo_bonus = 10 if (solo_threshold > 0 and attacker_count <= solo_threshold) else 0
            no_enemy_bonus = 5 if not enemy_attackers_present else 0
            blue_scouting_score = blue_scouting_bonus if friendly_path == "blue_scouting" else 0

            kill_score = int((base + high_value_bonus + solo_bonus + no_enemy_bonus + blue_scouting_score) * recency_weight)

            # Resolve names for evidence.
            victim_name = character_name_map.get(victim_char_id) or ""
            if not victim_name:
                resolved = self.esi.resolve_names({victim_char_id}) if victim_char_id else {}
                victim_name = resolved.get(victim_char_id) or str(victim_char_id)

            audited_char_name = character_name_map.get(attacker_char_id) or str(attacker_char_id)
            contributing_audited_ids = sorted(
                {
                    int(entry.get("character_id"))
                    for entry in friendly_attacker_entries
                    if entry.get("character_id")
                }
            )
            contributing_audited_names = [
                character_name_map.get(cid) or str(cid) for cid in contributing_audited_ids
            ]
            victim_ship_name = _type_name(victim_ship_type_id) or ""
            weapon_name = _type_name(weapon_type_id) or ""
            audited_ship_name = _type_name(ship_type_id) or ""

            friendly_link_char_name = ""
            if friendly_link_char_id:
                friendly_link_char_name = character_name_map.get(friendly_link_char_id) or str(friendly_link_char_id)

            # Resolve victim corp/alliance names.
            victim_corp_id = victim.get("corporation_id")
            victim_alliance_id = victim.get("alliance_id")
            ids_to_resolve = set()
            if victim_corp_id:
                ids_to_resolve.add(victim_corp_id)
            if victim_alliance_id:
                ids_to_resolve.add(victim_alliance_id)
            resolved_names = self.esi.resolve_names(ids_to_resolve) if ids_to_resolve else {}
            victim_corp_name = resolved_names.get(victim_corp_id) or str(victim_corp_id) if victim_corp_id else ""
            victim_alliance_name = resolved_names.get(victim_alliance_id) or str(victim_alliance_id) if victim_alliance_id else ""

            killmail_id = kill.get("killmail_id")
            entry = {
                "killmail_id": str(killmail_id) if killmail_id else "",
                "date": kill_time.strftime("%Y-%m-%d %H:%M") if kill_time else "unknown date",
                "kind": kind,
                "friendly_path": friendly_path,
                "friendly_link_char_id": friendly_link_char_id,
                "friendly_link_char_name": friendly_link_char_name,
                "friendly_link_type": friendly_link_type or "",
                "victim": {
                    "character_id": victim_char_id,
                    "character_name": victim_name,
                    "corporation_id": victim_corp_id,
                    "corporation_name": victim_corp_name,
                    "alliance_id": victim_alliance_id,
                    "alliance_name": victim_alliance_name,
                    "ship_type_id": victim_ship_type_id,
                    "ship_name": victim_ship_name,
                    "ship_group_id": victim_ship_group_id,
                    "image_url": MemberAuditAdapter._portrait_url(victim_char_id),
                },
                "audited_char": {
                    "character_id": attacker_char_id,
                    "character_name": audited_char_name,
                    "ship_type_id": ship_type_id,
                    "ship_name": audited_ship_name,
                    "ship_group_id": ship_group_id,
                },
                "audited_contributors": contributing_audited_names,
                "damage_done": int(damage_done),
                "damage_taken": int(damage_taken),
                "damage_share": round(damage_share, 4),
                "final_blow": final_blow,
                "attacker_count": attacker_count,
                "weapon_type_id": weapon_type_id,
                "weapon_name": weapon_name,
                "weapon_group_id": weapon_group_id,
                "zkb_value": float(zkb_value),
                "zkill_url": f"https://zkillboard.com/kill/{killmail_id}/" if killmail_id else "",
                "enemy_attackers_present": enemy_attackers_present,
                "kill_score": kill_score,
            }
            qualifying_kills.append(entry)

        if not qualifying_kills:
            return None

        # Aggregate scoring.
        total_score = min(sum(k["kill_score"] for k in qualifying_kills), AWOX_SCORE_CAP)

        # Severity by qualifying-kill count.
        kill_count = len(qualifying_kills)
        if kill_count >= 4:
            severity = "critical"
        elif kill_count >= 2:
            severity = "high"
        else:
            severity = "medium"

        # Kind breakdown for details string.
        kind_counts = {}
        for k in qualifying_kills:
            kind_counts[k["kind"]] = kind_counts.get(k["kind"], 0) + 1
        kind_breakdown_parts = []
        for kind in sorted(kind_counts):
            label = KIND_LABELS.get(kind, kind)
            # Simplify: "Friendly Fire (Damage)" -> "friendly-fire (damage)"
            short = label.lower().replace(" ", "-")
            kind_breakdown_parts.append(f"{kind_counts[kind]} {short}")
        kind_breakdown = ", ".join(kind_breakdown_parts)

        # Recency summary.
        recent_90 = sum(1 for k in qualifying_kills if k["date"] != "unknown date")
        blue_scouting_count = sum(1 for k in qualifying_kills if k["friendly_path"] == "blue_scouting")
        max_kill_score = max(k["kill_score"] for k in qualifying_kills)

        details = (
            f"{kill_count} awox kill(s) detected ({kind_breakdown}). "
            f"{recent_90} occurred in the lookback window. "
            f"Highest single-kill score: {max_kill_score}."
        )
        if blue_scouting_count > 0:
            details += f" Blue-scouting pattern: yes, {blue_scouting_count} kill(s)."
        else:
            details += " Blue-scouting pattern: no."

        # Sort kills by date descending for evidence.
        sorted_kills = sorted(qualifying_kills, key=lambda x: x["date"], reverse=True)

        summary_text = (
            f"Total awox kills: {kill_count}. "
            f"Total score: {total_score} (capped at {AWOX_SCORE_CAP}). "
            f"Severity: {severity}. "
            f"Kind breakdown: {kind_breakdown}. "
            f"Blue-scouting kills: {blue_scouting_count}."
        )

        evidence = [
            ("awox_killmails", json.dumps(sorted_kills[:20])),
            ("awox_summary", summary_text),
        ]

        return {
            "details": details,
            "score": total_score,
            "severity": severity,
            "evidence": evidence,
        }
