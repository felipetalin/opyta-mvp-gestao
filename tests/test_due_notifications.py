from datetime import date
import unittest

from scripts.notifications.send_due_alerts import (
    NotificationCandidate,
    add_candidate,
    alert_for_due,
    group_by_recipient,
    parse_email_list,
)


class DueNotificationTests(unittest.TestCase):
    def test_alert_windows(self):
        today = date(2026, 7, 1)
        windows = {0, 1, 3, 7}

        self.assertEqual(alert_for_due(date(2026, 6, 30), today, windows), ("OVERDUE", -1))
        self.assertEqual(alert_for_due(date(2026, 7, 1), today, windows), ("TODAY", 0))
        self.assertEqual(alert_for_due(date(2026, 7, 4), today, windows), ("DAYS_BEFORE", 3))
        self.assertIsNone(alert_for_due(date(2026, 7, 5), today, windows))

    def test_group_by_recipient(self):
        due = date(2026, 7, 1)
        items = [
            NotificationCandidate("gantt", "1", "A", "P1", "", "Felipe", "a@opyta.com.br", due, "TODAY", 0),
            NotificationCandidate("laboratorio", "2", "B", "P2", "", "Felipe", "a@opyta.com.br", due, "TODAY", 0),
            NotificationCandidate("produtos", "3", "C", "P3", "", "Yuri", "b@opyta.com.br", due, "TODAY", 0),
        ]

        grouped = group_by_recipient(items)

        self.assertEqual(set(grouped.keys()), {"a@opyta.com.br", "b@opyta.com.br"})
        self.assertEqual(len(grouped["a@opyta.com.br"]), 2)
        self.assertEqual(len(grouped["b@opyta.com.br"]), 1)

    def test_parse_email_list_normalizes_and_deduplicates(self):
        emails = parse_email_list(" YuriSimoes@opyta.com.br, felipetalin@opyta.com.br, yurisimoes@opyta.com.br ")

        self.assertEqual(emails, ["yurisimoes@opyta.com.br", "felipetalin@opyta.com.br"])

    def test_forced_recipients_create_one_candidate_per_email(self):
        candidates = []
        missing = []

        add_candidate(
            candidates,
            missing,
            source="reembolsos",
            source_id="1",
            title="Despesa",
            project_code="OPYADM",
            project_name="Administrativo",
            responsible=None,
            fallback_recipient="",
            forced_recipients=["yurisimoes@opyta.com.br", "felipetalin@opyta.com.br"],
            due_date=date(2026, 7, 1),
            today=date(2026, 7, 1),
            windows={0},
        )

        self.assertEqual(missing, [])
        self.assertEqual({item.recipient_email for item in candidates}, {"yurisimoes@opyta.com.br", "felipetalin@opyta.com.br"})


if __name__ == "__main__":
    unittest.main()
