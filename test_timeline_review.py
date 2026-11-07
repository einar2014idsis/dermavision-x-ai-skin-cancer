import unittest
from datetime import datetime
from longitudinal_insights import trend_series, trend_figure
from longitudinal_review import visit_review_rows
from longitudinal_insights import comparison_conclusion
class TimelineReviewTests(unittest.TestCase):
    def test_explains_both_individual_predictions_separately(self):
        result = dict(previous_date="2026-01-01", current_date="2026-07-01", comparable=True,
                      change_index=38.9, changes=dict(area=318.3),
                      previous_classification=dict(state="accepted", label="malignant", score=.8),
                      current_classification=dict(state="accepted", label="benign", score=.215))
        text = comparison_conclusion(result)
        self.assertIn("Fotografía anterior: patrón maligno", text)
        self.assertIn("Fotografía posterior: patrón benigno", text)
        self.assertIn("21.5 %", text)
        self.assertIn("no determina malignidad", text)
        self.assertIn("+318.3 %", text)

    def test_conclusion_does_not_publish_rejected_index_or_mislabel_score(self):
        rejected = dict(previous_date="2026-01-01", current_date="2026-02-01", comparable=False,
                        change_index=88, warnings=["Contorno insuficiente"],
                        current_classification=dict(state="uncertain"))
        description = comparison_conclusion(rejected)
        self.assertIn("no evaluable", description.lower())
        self.assertNotIn("88", description)
        self.assertIn("no concluyente", description)
        accepted = dict(previous_date="2026-01-01", current_date="2026-02-01", comparable=True,
                        change_index=12, changes=dict(area=4),
                        current_classification=dict(state="accepted", label="malignant", score=.8))
        description = comparison_conclusion(accepted)
        self.assertIn("80.0 %", description)
        self.assertIn("no es precisión", description)
        self.assertIn("+4.0 %", description)
    def test_intervals_are_not_accumulated_and_missing_metrics_remain_visible(self):
        records=[dict(id=str(i),captured_at=f'2026-0{i+1}-01',metadata={}) for i in range(3)]
        rows=[dict(id='pair', previous_id='1',current_id='2',result=dict(comparable=True,change_index=12,changes=dict(area=4)))]
        fixed=trend_series(rows,records,'0','area')
        consecutive=trend_series(rows,records,'0','area','consecutive')
        self.assertFalse(fixed['points'])
        self.assertEqual(consecutive['points'][0]['value'],4)
        self.assertEqual(len(trend_figure(consecutive).timeline_points),3)
        self.assertEqual([r['state'] for r in visit_review_rows(rows,records,'consecutive')],['reference','pending','available'])
    def test_rejected_residual_is_never_a_measurement(self):
        records=[dict(id=str(i),captured_at=f'2026-0{i+1}-01',metadata={}) for i in range(2)]
        rows=[dict(id='pair',previous_id='0',current_id='1',result=dict(comparable=False,change_index=20))]
        self.assertFalse(trend_series(rows,records,'0')['points'])
        self.assertEqual(visit_review_rows(rows,records)[1]['state'],'invalid')
