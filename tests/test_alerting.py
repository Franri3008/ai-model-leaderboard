import unittest
import json
import tempfile
from pathlib import Path

from scripts.alerting import (
    coerce_seen_registry,
    register_untracked_models,
    select_new_tracking_issues,
)
from scripts.firebase_upload import _build_payloads


class AlertDeltaTests(unittest.TestCase):
    @staticmethod
    def signature(issue):
        return f"{issue['model_id']}|{issue['source']}|{issue['lookup']}"

    def test_tracking_email_contains_only_new_issue(self):
        old = {"model_id": "old", "source": "AA", "lookup": "Old"}
        new = {"model_id": "new", "source": "LB", "lookup": "New"}

        actual = select_new_tracking_issues(
            [old, new], [self.signature(old)], self.signature, baseline_ready=True
        )

        self.assertEqual(actual, [new])

    def test_missing_tracking_baseline_fails_quiet(self):
        issue = {"model_id": "model", "source": "AA", "lookup": "Model"}

        actual = select_new_tracking_issues(
            [issue], [], self.signature, baseline_ready=False
        )

        self.assertEqual(actual, [])

    def test_untracked_model_is_not_replayed_after_leaving_top_30(self):
        seen = {"returning-model": "2026-01-01"}
        returning = {"norm_name": "returning-model", "instances": []}

        actual = register_untracked_models(
            [returning], seen, "2026-07-28", baseline_ready=True
        )

        self.assertEqual(actual, [])
        self.assertEqual(seen["returning-model"], "2026-01-01")

    def test_new_untracked_model_is_registered_once(self):
        seen = {}
        new = {"norm_name": "new-model", "instances": []}

        first = register_untracked_models(
            [new], seen, "2026-07-28", baseline_ready=True
        )
        second = register_untracked_models(
            [new], seen, "2026-07-29", baseline_ready=True
        )

        self.assertEqual(first, [new])
        self.assertEqual(second, [])
        self.assertEqual(seen["new-model"], "2026-07-28")

    def test_alert_state_is_included_in_firebase_payload(self):
        state = {
            "version": 1,
            "tracking_issues": ["model|AA|Model"],
            "seen_untracked": [
                {"key": "new-model", "first_seen": "2026-07-28"}
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            data_dir.mkdir()
            (data_dir / "alert_state.json").write_text(json.dumps(state))

            payloads = _build_payloads(directory)

        self.assertEqual(payloads["alert_state"], state)

    def test_firebase_safe_seen_records_preserve_unusual_model_names(self):
        records = [{"key": "vendor/model#preview", "first_seen": "2026-07-28"}]

        self.assertEqual(
            coerce_seen_registry(records),
            {"vendor/model#preview": "2026-07-28"},
        )


if __name__ == "__main__":
    unittest.main()
