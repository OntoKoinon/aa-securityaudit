from ..memberaudit_adapter import MemberAuditAdapter

class AltMixin:

    def _find_undisclosed_alts(self, user):
        declared_ids = MemberAuditAdapter.get_user_declared_character_ids(user)
        declared = MemberAuditAdapter.get_declared_characters(user)
        unresolved = []
        for char in declared:
            char_id = MemberAuditAdapter._extract_int(char, "character_id", "id")
            if char_id and char_id in declared_ids:
                continue
            name = getattr(char, "character_name", None) or getattr(char, "name", None)
            if not name:
                continue
            if "alt" in name.lower():
                unresolved.append(name)
        return unresolved