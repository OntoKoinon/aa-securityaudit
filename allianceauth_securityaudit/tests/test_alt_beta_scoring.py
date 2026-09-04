from django.test import SimpleTestCase

from allianceauth_securityaudit.services.audit_analysis.corp_history import score_beta_overlap_rule


class BetaOverlapScoringTests(SimpleTestCase):
    def test_rule_1_minimum(self):
        result = score_beta_overlap_rule([{"corp_id": 1, "any_close": True, "both_close": True}])
        self.assertEqual(result, ("rule_1", 60))

    def test_rule_1_with_additional_bonus(self):
        result = score_beta_overlap_rule(
            [
                {"corp_id": 1, "any_close": True, "both_close": True},
                {"corp_id": 2, "any_close": True, "both_close": True},
                {"corp_id": 3, "any_close": True, "both_close": False},
            ]
        )
        self.assertEqual(result, ("rule_1", 85))

    def test_rule_2_scoring(self):
        result = score_beta_overlap_rule(
            [
                {"corp_id": 1, "any_close": True, "both_close": False},
                {"corp_id": 2, "any_close": False, "both_close": False},
                {"corp_id": 3, "any_close": False, "both_close": False},
                {"corp_id": 4, "any_close": True, "both_close": False},
            ]
        )
        self.assertEqual(result, ("rule_2", 50))

    def test_rule_3_scoring(self):
        result = score_beta_overlap_rule(
            [
                {"corp_id": 1, "any_close": False, "both_close": False},
                {"corp_id": 2, "any_close": False, "both_close": False},
                {"corp_id": 3, "any_close": False, "both_close": False},
                {"corp_id": 4, "any_close": False, "both_close": False},
                {"corp_id": 5, "any_close": False, "both_close": False},
                {"corp_id": 6, "any_close": False, "both_close": False},
            ]
        )
        self.assertEqual(result, ("rule_3", 20))

    def test_no_rule_match(self):
        result = score_beta_overlap_rule(
            [
                {"corp_id": 1, "any_close": False, "both_close": False},
                {"corp_id": 2, "any_close": False, "both_close": False},
            ]
        )
        self.assertIsNone(result)

    def test_present_corp_exclusion_shape(self):
        corp_stats = []
        result = score_beta_overlap_rule(corp_stats)
        self.assertIsNone(result)

    def test_rule_2_respects_custom_threshold(self):
        corp_stats = [
            {"corp_id": 1, "any_close": True, "both_close": False},
            {"corp_id": 2, "any_close": True, "both_close": False},
        ]
        self.assertEqual(score_beta_overlap_rule(corp_stats, rule2_min=2), ("rule_2", 40))
        self.assertIsNone(score_beta_overlap_rule(corp_stats))

    def test_rule_3_respects_custom_threshold(self):
        corp_stats = [
            {"corp_id": 1, "any_close": False, "both_close": False},
            {"corp_id": 2, "any_close": False, "both_close": False},
            {"corp_id": 3, "any_close": False, "both_close": False},
            {"corp_id": 4, "any_close": False, "both_close": False},
        ]
        self.assertEqual(score_beta_overlap_rule(corp_stats, rule3_min=4), ("rule_3", 15))
        self.assertIsNone(score_beta_overlap_rule(corp_stats))

    def test_rule_1_respects_custom_threshold(self):
        corp_stats = [
            {"corp_id": 1, "any_close": True, "both_close": True},
            {"corp_id": 2, "any_close": True, "both_close": True},
        ]
        self.assertEqual(score_beta_overlap_rule(corp_stats, rule1_min=2), ("rule_1", 60))
        self.assertEqual(score_beta_overlap_rule(corp_stats), ("rule_1", 75))
