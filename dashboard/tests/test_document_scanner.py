from __future__ import annotations

import unittest
from unittest.mock import patch

from dashboard.document_scanner import (
    DEFAULT_GOOGLE_SHEET_URL,
    PMP_SOURCE_CSV_URL,
    commit_scan,
    extract_with_template,
    mark_pmp_rows,
    normalize_money,
    parse_google_drive_source,
    scan_document,
    sync_google_sheet,
    sync_google_sheet_with_api,
)


class DocumentScannerTests(unittest.TestCase):
    def test_parse_google_drive_file_url(self) -> None:
        source = parse_google_drive_source(
            "https://drive.google.com/file/d/1yTBvJZtWIuE_CRfAe8BMyF9JPFxeusGE/view?usp=sharing"
        )
        self.assertEqual(source.document_id, "1yTBvJZtWIuE_CRfAe8BMyF9JPFxeusGE")
        self.assertIn("export=download", source.download_url)

    def test_normalize_money_accepts_spanish_format(self) -> None:
        self.assertEqual(normalize_money("1.234,56"), 1234.56)
        self.assertEqual(normalize_money("EUR 345,20"), 345.2)
        self.assertEqual(normalize_money("363.45"), 363.45)

    def test_extract_with_template_returns_policy_rows_and_totals(self) -> None:
        text = """
        Aseguradora Demo
        Fecha liquidación: 20/04/2026
        Póliza: AUTO-12345 Tomador: MARIA LOPEZ Prima neta: 1.234,56
        Póliza: HOG-99881 Tomador: JUAN PEREZ Prima neta: 345,20
        """
        template = {
            "fields": {
                "policy": r"p[óo]liza:\s*([A-Z0-9-]+)",
                "holder": r"tomador:\s*([A-ZÁÉÍÓÚÑ ]+?)\s+prima",
                "netPremium": r"prima\s+neta:\s*([0-9.,]+)",
                "liquidationDate": r"fecha\s+liquidaci[óo]n:\s*(\d{1,2}/\d{1,2}/\d{4})",
            }
        }
        result = extract_with_template(text, template)
        self.assertEqual(result["liquidationDate"], "2026-04-20")
        self.assertEqual(result["totals"]["policies"], 2)
        self.assertEqual(result["totals"]["netPremium"], 1579.76)
        self.assertEqual(result["rows"][0]["tomador"], "MARIA LOPEZ")

    def test_reale_cached_drive_document_extracts_table_rows(self) -> None:
        result = scan_document(
            {"driveUrl": "https://drive.google.com/file/d/1yTBvJZtWIuE_CRfAe8BMyF9JPFxeusGE/view?usp=drive_link"}
        )
        self.assertEqual(result["insurer"], "Reale Seguros Generales, S.A.")
        self.assertEqual(result["liquidationDate"], "2025-01-31")
        self.assertEqual(result["totals"]["policies"], 159)
        self.assertEqual(result["totals"]["netPremium"], 33343.71)

    def test_reale_table_accepts_slash_dates_and_invoice_date(self) -> None:
        text = """
        DETALLE LIQUIDACIÓN DE COMISIONES
        RAMO PÓLIZA RECIBO NOMBRE DEL TOMADOR EF.RBO. TIP PRIMA NETA % COMISIÓN I.R.P.F. LÍQUIDO
        133 1332400012180 690032016510 GRAND HORIZON, S.L. 20/04/2025 CNO 327,82 15,0 49,17 0,00 49,17
        302 3021300099286 690034273077 ARTHUR MATTHEW COATES 01/04/2025 CNO 466,69 12,3 57,36 0,00 57,36
        FECHA EXPEDICIÓN FACTURA :
        30/04/2025
        """
        result = extract_with_template(text, {"recordMode": "reale-table", "fields": {}})
        self.assertEqual(result["liquidationDate"], "2025-04-30")
        self.assertEqual(result["totals"]["policies"], 2)
        self.assertEqual(result["totals"]["netPremium"], 794.51)

    def test_allianz_table_starts_after_policy_header_and_uses_due_month_end(self) -> None:
        text = """
        Allianz resumen previo
        9999999999 8888888888 01/2026 NO DEBE SALIR 999,99
        Póliza Recibo Vencimiento Tomador T.Recibo
        AZ1234567 RC987654 05/2026 CLIENTE UNO SL 123,45
        BZ7654321 RC123456 02/26 MARIA GARCIA 1.234,56
        Total 1.358,01
        """
        result = extract_with_template(text, {"recordMode": "allianz-table", "fields": {}})
        self.assertEqual(result["totals"]["policies"], 2)
        self.assertEqual(result["totals"]["netPremium"], 1358.01)
        self.assertEqual(result["rows"][0]["poliza"], "AZ1234567")
        self.assertEqual(result["rows"][0]["recibo"], "RC987654")
        self.assertEqual(result["rows"][0]["fechaRecibo"], "2026-05-31")
        self.assertEqual(result["rows"][1]["fechaRecibo"], "2026-02-28")
        self.assertEqual(result["rows"][0]["tomador"], "CLIENTE UNO SL")

    def test_commit_scan_uses_allianz_row_due_date_without_changing_global_date(self) -> None:
        payload = {
            "insurer": "Allianz",
            "documentId": "DOC-ALLIANZ",
            "liquidationDate": "2026-01-15",
            "rows": [
                {
                    "poliza": "05704573900000",
                    "recibo": "RC987654",
                    "fechaRecibo": "2026-05-31",
                    "tomador": "Cliente Uno",
                    "primaNeta": "123,45",
                }
            ],
        }
        with (
            patch("dashboard.document_scanner.ensure_state", return_value={"templates": {}, "scans": {}, "sheetRows": [], "historyRows": [], "googleSheetUrl": DEFAULT_GOOGLE_SHEET_URL}),
            patch("dashboard.document_scanner.save_state"),
            patch("dashboard.document_scanner.sync_google_sheet", return_value={"mode": "test"}),
            patch("dashboard.document_scanner.mark_pmp_rows", side_effect=lambda rows: rows),
        ):
            result = commit_scan(payload)
        self.assertEqual(result["sheetRows"][0]["Fecha"], "2026-05-31")
        self.assertEqual(result["sheetRows"][0]["Aseguradora"], "Allianz")
        self.assertEqual(result["sheetRows"][0]["Poliza"], "057045739")

    def test_mark_pmp_rows_flags_policy_presence(self) -> None:
        rows = [{"poliza": "032512697"}, {"poliza": "NO-EXISTE"}]
        marked = mark_pmp_rows(rows, {"032512697"})
        self.assertEqual(marked[0]["PMP"], "Si")
        self.assertEqual(marked[1]["PMP"], "No")

    def test_configured_google_sheets_are_current_targets(self) -> None:
        self.assertIn("13q76_ri1EcVprHcmBYgoAMWWaynGWFscqSCUON8OC7E", PMP_SOURCE_CSV_URL)
        self.assertIn("1yMkfCsuZplCqzpnyCYcCkM_AP4J3fNmFCPlTR5FSlgs", DEFAULT_GOOGLE_SHEET_URL)

    def test_google_sheet_sync_replaces_liquidaciones_for_same_document_id(self) -> None:
        calls: list[tuple[str, str, list[list[object]] | None]] = []

        def fake_get_values(_spreadsheet_id: str, sheet_range: str, _token: str) -> list[list[object]]:
            if sheet_range == "Log!A:E":
                return [["ID Hoja de Calculo", "Fecha", "Registros", "Total Prima", "Empresa"]]
            if sheet_range == "Liquidaciones!A:H":
                return [
                    ["ID Hoja de Calculo", "Aseguradora", "Poliza", "Fecha", "Tomador", "Prima", "Recibo", "PMP"],
                    ["DOC-1", "Demo", "ANTERIOR", "2026-01-01", "Cliente viejo", 1, "R-1", "No"],
                    ["DOC-2", "Demo", "OTRA", "2026-01-01", "Cliente otro", 2, "R-2", "Si"],
                ]
            return []

        def fake_append(_spreadsheet_id: str, sheet_range: str, values: list[list[object]], _token: str) -> None:
            calls.append(("append", sheet_range, values))

        def fake_clear(_spreadsheet_id: str, sheet_range: str, _token: str) -> None:
            calls.append(("clear", sheet_range, None))

        def fake_put(_spreadsheet_id: str, sheet_range: str, values: list[list[object]], _token: str) -> None:
            calls.append(("put", sheet_range, values))

        sheet_rows = [
            {
                "ID Hoja de Calculo": "DOC-1",
                "Aseguradora": "Demo",
                "Poliza": "NUEVA",
                "Fecha": "2026-05-12",
                "Tomador": "Cliente nuevo",
                "Prima": 123.45,
                "Recibo": "R-9",
                "PMP": "Si",
            }
        ]
        history_row = {
            "id del documento": "DOC-1",
            "total polizas": 1,
            "total monto prima neta": 123.45,
            "nombre de la aseguradora": "Demo",
        }
        with (
            patch("dashboard.document_scanner._google_access_token", return_value="token"),
            patch("dashboard.document_scanner._get_sheet_values", side_effect=fake_get_values),
            patch("dashboard.document_scanner._append_sheet_values", side_effect=fake_append),
            patch("dashboard.document_scanner._clear_sheet_values", side_effect=fake_clear),
            patch("dashboard.document_scanner._put_sheet_values", side_effect=fake_put),
        ):
            result = sync_google_sheet_with_api(sheet_rows, history_row, DEFAULT_GOOGLE_SHEET_URL)

        self.assertEqual(result["mode"], "google-api")
        put_values = [call[2] for call in calls if call[0] == "put" and call[1] == "Liquidaciones!A1:H"][0]
        self.assertEqual(put_values[1][0], "DOC-2")
        self.assertEqual(put_values[2][2], "'NUEVA")
        self.assertNotIn("ANTERIOR", [row[2] for row in put_values])

    def test_google_sheet_sync_reports_permission_error(self) -> None:
        with patch("dashboard.document_scanner.sync_google_sheet_with_api", side_effect=RuntimeError("Google Sheets API 403")):
            result = sync_google_sheet([], {"id del documento": "DOC-1"}, DEFAULT_GOOGLE_SHEET_URL)

        self.assertEqual(result["mode"], "error")
        self.assertIn("No se pudo actualizar Google Sheet", result["message"])


if __name__ == "__main__":
    unittest.main()
