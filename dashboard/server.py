from __future__ import annotations

import argparse
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dashboard.data_loader import DashboardDataset, parse_excel_date
from dashboard.document_scanner import (
    commit_scan,
    list_templates,
    parse_json_body,
    save_template,
    scan_document,
    scanner_summary,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_EXCEL = ROOT_DIR / "Data" / "listadopolizasexcel_20260420_174106.xlsx"
DEFAULT_PORTFOLIO_SHEET_ID = "13q76_ri1EcVprHcmBYgoAMWWaynGWFscqSCUON8OC7E"
DEFAULT_PORTFOLIO_SHEET_GID = "674567918"


def json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


def parse_filters(query: dict[str, list[str]]) -> dict[str, Any]:
    office_ids = []
    for raw in query.get("officeIds", []):
        office_ids.extend([item.strip() for item in raw.split(",") if item.strip()])

    statuses = []
    for raw in query.get("statuses", []):
        statuses.extend([item.strip() for item in raw.split(",") if item.strip()])

    insurance_types = []
    for raw in query.get("insuranceTypes", []):
        insurance_types.extend([item.strip() for item in raw.split(",") if item.strip()])

    insurers = []
    for raw in query.get("insurers", []):
        insurers.extend([item.strip() for item in raw.split(",") if item.strip()])

    expiration_month = query.get("expirationMonth", [""])[0]
    expiration_from = parse_excel_date(query.get("expirationFrom", [None])[0])
    expiration_to = parse_excel_date(query.get("expirationTo", [None])[0])
    if expiration_month:
        month_start = parse_excel_date(f"{expiration_month}-01")
        if month_start:
            if month_start.month == 12:
                next_month = date(month_start.year + 1, 1, 1)
            else:
                next_month = date(month_start.year, month_start.month + 1, 1)
            expiration_from = month_start
            expiration_to = date.fromordinal(next_month.toordinal() - 1)
    return {
        "office_ids": office_ids,
        "statuses": statuses,
        "insurers": insurers,
        "insurance_types": insurance_types,
        "expiration_from": expiration_from,
        "expiration_to": expiration_to,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    dataset: DashboardDataset | None = None

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/api/health":
            json_response(self, {"ok": True})
            return

        if route == "/api/dashboard":
            filters = parse_filters(query)
            payload = self.dataset.dashboard_payload(**filters)
            json_response(self, payload)
            return

        if route == "/api/listings/expiring-next-month":
            filters = parse_filters(query)
            payload = self.dataset.expiring_next_month_listing(**filters)
            json_response(self, payload)
            return

        if route == "/api/listings/former-clients":
            filters = parse_filters(query)
            payload = self.dataset.former_clients_listing(**filters)
            json_response(self, payload)
            return

        if route == "/api/listings/cross-sell":
            filters = parse_filters(query)
            payload = self.dataset.cross_sell_listing(**filters)
            json_response(self, payload)
            return

        if route == "/api/listings/insurers":
            filters = parse_filters(query)
            payload = self.dataset.insurers_listing(**filters)
            json_response(self, payload)
            return

        if route == "/api/chat":
            filters = parse_filters(query)
            question = query.get("q", [""])[0]
            payload = self.dataset.chat_response(question, **filters, today=date.today())
            json_response(self, payload)
            return

        if route == "/api/scanner/summary":
            json_response(self, scanner_summary())
            return

        if route == "/api/scanner/templates":
            json_response(self, {"templates": list_templates()})
            return

        if route == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        self.serve_static(route)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        content_length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = parse_json_body(self.rfile.read(content_length))
            if route == "/api/scanner/scan":
                json_response(self, scan_document(payload))
                return
            if route == "/api/scanner/templates":
                json_response(self, save_template(payload))
                return
            if route == "/api/scanner/commit":
                json_response(self, commit_scan(payload))
                return
            json_response(self, {"error": "Ruta no encontrada"}, status=HTTPStatus.NOT_FOUND)
        except Exception as error:  # noqa: BLE001
            json_response(self, {"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def serve_static(self, route: str) -> None:
        target = STATIC_DIR / "index.html" if route == "/" else STATIC_DIR / route.lstrip("/")
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        content = target.read_bytes()
        content_type, _ = mimetypes.guess_type(str(target))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard local de pólizas")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--excel", default=str(DEFAULT_EXCEL))
    parser.add_argument("--sheet-id", default=DEFAULT_PORTFOLIO_SHEET_ID)
    parser.add_argument("--sheet-gid", default=DEFAULT_PORTFOLIO_SHEET_GID)
    args = parser.parse_args()

    dataset = DashboardDataset.from_google_sheet(args.sheet_id, args.sheet_gid) if args.sheet_id else DashboardDataset.from_excel(args.excel)
    DashboardHandler.dataset = dataset

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard listo en http://{args.host}:{args.port}")
    print(f"Fuente cartera: {dataset.source_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
