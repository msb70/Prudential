from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from dashboard.data_loader import DashboardDataset, parse_mixed_number


ROOT_DIR = Path(__file__).resolve().parents[2]
EXCEL_PATH = ROOT_DIR / "Data" / "listadopolizasexcel_20260420_174106.xlsx"


class DashboardDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = DashboardDataset.from_excel(str(EXCEL_PATH))

    def test_parse_mixed_number(self) -> None:
        self.assertEqual(parse_mixed_number("0,00"), 0.0)
        self.assertEqual(parse_mixed_number("347"), 347.0)
        self.assertEqual(parse_mixed_number("363.45"), 363.45)
        self.assertEqual(parse_mixed_number("1.234,56"), 1234.56)

    def test_active_clients_metric_matches_policy_logic(self) -> None:
        payload = self.dataset.dashboard_payload()
        expected = len({policy.clientId for policy in self.dataset.policies if policy.isActive})
        self.assertEqual(payload["metrics"]["activeClients"], expected)

    def test_former_clients_have_no_active_policies(self) -> None:
        summaries = self.dataset.build_client_summaries(self.dataset.policies)
        for summary in summaries:
            if summary.isFormerClient:
                self.assertFalse(summary.isActiveClient)

    def test_cross_sell_only_returns_one_active_policy_per_client(self) -> None:
        listing = self.dataset.cross_sell_listing()
        lookup = {summary.clientName: summary for summary in self.dataset.build_client_summaries(self.dataset.policies)}
        self.assertTrue(listing["rows"])
        for row in listing["rows"][:100]:
            summary = lookup[row["clientName"]]
            self.assertEqual(summary.activePolicyCount, 1)
            self.assertTrue(summary.isActiveClient)

    def test_next_month_listing_respects_calendar_window(self) -> None:
        listing = self.dataset.expiring_next_month_listing(today=date(2026, 4, 20))
        self.assertTrue(listing["rows"])
        self.assertEqual(listing["window"]["from"], "2026-05-01")
        self.assertEqual(listing["window"]["to"], "2026-05-31")
        for row in listing["rows"][:50]:
            self.assertTrue("2026-05-" in row["expirationDate"])

    def test_filters_change_metrics(self) -> None:
        unfiltered = self.dataset.dashboard_payload()
        filtered = self.dataset.dashboard_payload(office_ids=["2"], insurance_types=["AUTOS"])
        self.assertLess(filtered["metrics"]["totalPolicies"], unfiltered["metrics"]["totalPolicies"])
        self.assertLessEqual(filtered["metrics"]["activeClients"], unfiltered["metrics"]["activeClients"])

    def test_chat_handles_query_with_type_and_office(self) -> None:
        response = self.dataset.chat_response("cuántos autos activos hay en oficina 2")
        self.assertIn("pólizas activas", response["answer"].lower())


if __name__ == "__main__":
    unittest.main()
