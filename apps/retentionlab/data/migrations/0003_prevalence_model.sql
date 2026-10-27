-- D-09 (R10-14): a fourth model, the prevalence-constant baseline, may be stored, scored and published. The model_name checks of
-- 0001 are widened; nothing else changes. Idempotent: every constraint is dropped by name before it is added.
ALTER TABLE model_coefficients DROP CONSTRAINT IF EXISTS model_coefficients_model_name_check;
ALTER TABLE model_coefficients ADD CONSTRAINT model_coefficients_model_name_check
    CHECK (model_name IN ('random_baseline', 'business_rule', 'logistic_regression', 'prevalence_baseline'));
ALTER TABLE predictions DROP CONSTRAINT IF EXISTS predictions_model_name_check;
ALTER TABLE predictions ADD CONSTRAINT predictions_model_name_check
    CHECK (model_name IN ('random_baseline', 'business_rule', 'logistic_regression', 'prevalence_baseline'));
ALTER TABLE scoring_publications DROP CONSTRAINT IF EXISTS scoring_publications_model_name_check;
ALTER TABLE scoring_publications ADD CONSTRAINT scoring_publications_model_name_check
    CHECK (model_name IN ('random_baseline', 'business_rule', 'logistic_regression', 'prevalence_baseline'));
