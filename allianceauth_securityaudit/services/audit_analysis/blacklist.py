from ..blacklist_adapter import BlacklistAdapter
from ..memberaudit_adapter import MemberAuditAdapter

class BlacklistMixin:

    @staticmethod
    def _character_identity_set(user):
        ids = set()
        names = set()
        for char in MemberAuditAdapter.get_declared_characters(user):
            char_id = MemberAuditAdapter._extract_int(char, "character_id", "id")
            if char_id:
                ids.add(char_id)
            char_name = MemberAuditAdapter._extract_text(char, "character_name", "name", "character")
            if char_name:
                names.add(char_name)
        return ids, names

    def _check_blacklist_signals(self, audit_run, character_id, character_name, user, kills):
        if not BlacklistAdapter.is_available():
            return set(), set()

        declared_ids, declared_names = self._character_identity_set(user)
        if character_id:
            declared_ids.add(character_id)
        if character_name:
            declared_names.add(character_name)

        matched_ids = BlacklistAdapter.get_blacklisted_character_ids(declared_ids)
        matched_names = BlacklistAdapter.get_blacklisted_character_names(declared_names)

        if matched_names:
            for declared_char in MemberAuditAdapter.get_declared_characters(user):
                declared_name = MemberAuditAdapter._extract_text(declared_char, "character_name", "name", "character")
                if not declared_name or declared_name not in matched_names:
                    continue
                declared_id = MemberAuditAdapter._extract_int(declared_char, "character_id", "id")
                if declared_id:
                    matched_ids.add(declared_id)

        interaction_ids = set(MemberAuditAdapter.get_contact_character_ids(character_id))
        interaction_ids.update(self._killmail_counterparty_ids(kills))
        interaction_ids.update(
            audit_run.counterparties.exclude(character_id__isnull=True).values_list("character_id", flat=True)
        )
        interaction_ids -= declared_ids
        if character_id:
            interaction_ids.discard(character_id)

        interaction_matches = BlacklistAdapter.get_blacklisted_character_ids(interaction_ids)
        return matched_ids, interaction_matches

    @staticmethod
    def _killmail_counterparty_ids(kills):
        ids = set()
        for kill in kills or []:
            victim = kill.get("victim") or {}
            victim_id = victim.get("character_id")
            if victim_id:
                ids.add(victim_id)
            for attacker in kill.get("attackers") or []:
                attacker_id = attacker.get("character_id")
                if attacker_id:
                    ids.add(attacker_id)
        return ids