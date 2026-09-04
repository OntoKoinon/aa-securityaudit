import logging

from django.apps import apps

LOGGER = logging.getLogger(__name__)


class AutogroupsAdapter:
    """
    Resilient adapter for allianceauth.eveonline.autogroups ManagedCorpGroup.
    Falls back to an empty set if the app/models are not installed.
    """

    @staticmethod
    def _get_model(app_label, model_name):
        try:
            return apps.get_model(app_label, model_name)
        except (LookupError, ValueError):
            return None

    @staticmethod
    def _extract_int(obj, *names):
        for name in names:
            value = getattr(obj, name, None)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def get_managed_corp_ids():
        """
        Return a set of corporation IDs across all ManagedCorpGroup entries.
        Returns an empty set if the autogroups app is not installed.
        """
        for app_label in ("eve_autogroups", "eveonline"):
            ManagedCorpGroup = AutogroupsAdapter._get_model(app_label, "ManagedCorpGroup")
            if ManagedCorpGroup is not None:
                break
        else:
            return set()

        ids = set()
        try:
            groups = ManagedCorpGroup.objects.select_related("corp")
        except Exception:
            try:
                groups = ManagedCorpGroup.objects.prefetch_related("corporations")
            except Exception:
                return set()

        for group in groups.iterator():
            # Alliance Auth's ManagedCorpGroup uses a single `corp` FK.
            corp = getattr(group, "corp", None)
            if corp is not None:
                corp_id = AutogroupsAdapter._extract_int(
                    corp, "corporation_id", "corp_id", "id"
                )
                if corp_id:
                    ids.add(corp_id)
                continue

            # Fallback for any M2M/related `corporations` field.
            corp_rel = getattr(group, "corporations", None)
            if corp_rel is None:
                continue
            try:
                queryset = corp_rel.all() if hasattr(corp_rel, "all") else corp_rel
            except Exception:
                continue
            for c in queryset:
                corp_id = AutogroupsAdapter._extract_int(
                    c, "corporation_id", "corp_id", "id"
                )
                if corp_id:
                    ids.add(corp_id)

        return ids
