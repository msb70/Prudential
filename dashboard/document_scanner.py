from __future__ import annotations

import base64
from dataclasses import dataclass
from calendar import monthrange
from datetime import datetime, timezone
import csv
import io
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, Request, build_opener

try:
    import pdfplumber
except ModuleNotFoundError:  # pragma: no cover - depends on local runtime
    pdfplumber = None

try:
    from pypdf import PdfReader
except ModuleNotFoundError:  # pragma: no cover - depends on local runtime
    PdfReader = None


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "Data"
STATE_PATH = DATA_DIR / "scanner_state.json"
SHEET_ROWS_PATH = DATA_DIR / "scanner_google_sheet_rows.csv"
HISTORY_ROWS_PATH = DATA_DIR / "scanner_history_rows.csv"
PMP_ROWS_PATH = DATA_DIR / "scanner_pmp_rows.csv"
PMP_POLICIES_PATH = DATA_DIR / "pmp_policies.csv"
PMP_SOURCE_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "13q76_ri1EcVprHcmBYgoAMWWaynGWFscqSCUON8OC7E/export?format=csv&gid=674567918"
)
DEFAULT_GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1yMkfCsuZplCqzpnyCYcCkM_AP4J3fNmFCPlTR5FSlgs"
DEFAULT_SERVICE_ACCOUNT_FILE = DATA_DIR / "credentials" / "prudential-scanner-service-account.json"
BUILT_IN_TEMPLATE_INSURERS = ("Allianz",)
GOOGLE_SHEETS_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
)


DEFAULT_FIELD_PATTERNS = {
    "policy": r"(?:pol(?:i|í)za|n[úu]mero\s+de\s+p[óo]liza|certificado)\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{4,})",
    "holder": r"(?:tomador|cliente|asegurado|contratante)\s*[:#-]?\s*([^\n\r]{3,90})",
    "netPremium": r"(?:prima\s+neta|prima|neto)\s*[:#-]?\s*(?:EUR|€)?\s*([0-9.,]+)",
    "liquidationDate": r"(?:fecha\s+(?:de\s+)?liquidaci(?:o|ó)n|liquidaci(?:o|ó)n\s+fecha|fecha)\s*[:#-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
}


@dataclass(frozen=True)
class ScanSource:
    document_id: str
    download_url: str
    original_url: str


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_state() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        payload = {
            "templates": {},
            "scans": {},
            "sheetRows": [],
            "historyRows": [],
            "googleSheetUrl": os.environ.get("GOOGLE_SHEET_URL", DEFAULT_GOOGLE_SHEET_URL),
        }
        _ensure_builtin_templates(payload)
        return payload
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload.setdefault("templates", {})
    _ensure_builtin_templates(payload)
    payload.setdefault("scans", {})
    payload.setdefault("sheetRows", [])
    payload.setdefault("historyRows", [])
    configured_sheet_url = os.environ.get("GOOGLE_SHEET_URL", DEFAULT_GOOGLE_SHEET_URL)
    if not payload.get("googleSheetUrl") or "1yMkfCsuZplCqzpnyCYcCkM_AP4J3fNmFCPlTR5FSlgs" not in payload.get("googleSheetUrl", ""):
        payload["googleSheetUrl"] = configured_sheet_url
    return payload


def _ensure_builtin_templates(state: dict[str, Any]) -> None:
    templates = state.setdefault("templates", {})
    for insurer in BUILT_IN_TEMPLATE_INSURERS:
        templates.setdefault(insurer, build_default_template(insurer))


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    tmp_path.replace(STATE_PATH)
    write_csv_exports(state)


def write_csv_exports(state: dict[str, Any]) -> None:
    sheet_columns = ["ID Hoja de Calculo", "Aseguradora", "Poliza", "Fecha", "Tomador", "Prima", "Recibo", "PMP"]
    pmp_columns = ["ID Hoja de Calculo", "Poliza", "Tomador", "PMP"]
    history_columns = [
        "ultima fecha de escaneo",
        "id del documento",
        "total polizas",
        "total monto prima neta",
        "nombre de la aseguradora",
        "mes y año del documento escaneado",
    ]

    with SHEET_ROWS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sheet_columns)
        writer.writeheader()
        for row in state.get("sheetRows", []):
            writer.writerow({column: row.get(column, "") for column in sheet_columns})

    with PMP_ROWS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=pmp_columns)
        writer.writeheader()
        for row in state.get("sheetRows", []):
            writer.writerow({column: row.get(column, "") for column in pmp_columns})

    with HISTORY_ROWS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=history_columns)
        writer.writeheader()
        for row in state.get("historyRows", []):
            writer.writerow({column: row.get(column, "") for column in history_columns})


def parse_google_drive_source(raw_url: str) -> ScanSource:
    parsed = urlparse(raw_url)
    query = parse_qs(parsed.query)
    document_id = ""

    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        document_id = match.group(1)
    elif "id" in query and query["id"]:
        document_id = query["id"][0]
    elif parsed.netloc.endswith("drive.google.com") and parsed.path:
        document_id = parsed.path.strip("/")

    if not document_id:
        raise ValueError("No pude identificar el ID del documento de Google Drive.")

    download_url = f"https://drive.google.com/uc?export=download&id={document_id}"
    return ScanSource(document_id=document_id, download_url=download_url, original_url=raw_url)


def download_pdf(raw_url: str) -> tuple[ScanSource, bytes]:
    source = parse_google_drive_source(raw_url)
    cached_path = DATA_DIR / f"drive_{source.document_id}.pdf"
    if cached_path.exists():
        return source, cached_path.read_bytes()

    try:
        response = _http_get(source.download_url)
        text = response["body"].decode("utf-8", errors="ignore")
        token = _confirm_token(text)
        if token:
            response = _http_get(f"{source.download_url}&confirm={token}")

        content_type = response["headers"].get("Content-Type", "")
        content = response["body"]
        if "pdf" in content_type.lower() or content.startswith(b"%PDF"):
            return source, content
    except Exception:
        pass

    raise ValueError(
        "El enlace no devolvió un PDF directo. Abre la app desde el servidor local y revisa permisos de Drive."
    )


def _http_get(url: str) -> dict[str, Any]:
    opener = build_opener()
    request = Request(url, headers={"User-Agent": "PrudentialScanner/1.0"})
    try:
        response = opener.open(request, timeout=30)
    except Exception as error:
        if "CERTIFICATE_VERIFY_FAILED" not in str(error):
            raise
        opener = build_opener(HTTPSHandler(context=ssl._create_unverified_context()))  # noqa: S323
        response = opener.open(request, timeout=30)
    with response:
        return {"body": response.read(), "headers": dict(response.headers), "status": response.status}


def _normalize_policy_key(raw: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(raw or "").upper())


def load_pmp_policy_index(refresh: bool = True) -> set[str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if refresh or not PMP_POLICIES_PATH.exists():
        try:
            response = _http_get(PMP_SOURCE_CSV_URL)
            if response["body"]:
                PMP_POLICIES_PATH.write_bytes(response["body"])
        except Exception:
            if not PMP_POLICIES_PATH.exists():
                return set()

    try:
        with PMP_POLICIES_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            policy_field = next((field for field in (reader.fieldnames or []) if field.strip().lower() == "póliza"), "Póliza")
            return {
                key
                for row in reader
                if (key := _normalize_policy_key(row.get(policy_field, "")))
            }
    except OSError:
        return set()


def mark_pmp_rows(rows: list[dict[str, Any]], pmp_index: set[str] | None = None) -> list[dict[str, Any]]:
    index = pmp_index if pmp_index is not None else load_pmp_policy_index()
    for row in rows:
        row["PMP"] = "Si" if _normalize_policy_key(row.get("poliza")) in index else "No"
    return rows


def _confirm_token(html: str) -> str | None:
    patterns = [
        r"confirm=([0-9A-Za-z_]+)",
        r'name="confirm"\s+value="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as temp:
        temp.write(pdf_bytes)
        temp.flush()
        if pdfplumber is not None:
            pages: list[str] = []
            with pdfplumber.open(temp.name) as pdf:
                for page in pdf.pages:
                    pages.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
            return "\n\n".join(pages), len(pages)
        if PdfReader is None:
            raise RuntimeError("No hay extractor PDF instalado. Instala pdfplumber o pypdf.")
        reader = PdfReader(temp.name)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages), len(reader.pages)


def normalize_money(raw: str | int | float | None) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return round(float(raw), 2)
    value = str(raw).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not value:
        return 0.0
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return round(float(value), 2)
    except ValueError:
        return 0.0


def normalize_date(raw: str | None) -> str:
    if not raw:
        return ""
    value = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def normalize_for_match(value: str) -> str:
    normalized = value.lower()
    replacements = str.maketrans("áéíóúüñ", "aeiouun")
    normalized = normalized.translate(replacements)
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def month_year(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return value[:7]
    return parsed.strftime("%Y-%m")


def infer_insurer(text: str, fallback: str = "") -> str:
    if fallback:
        return fallback.strip()
    if "Reale Seguros Generales" in text:
        return "Reale Seguros Generales, S.A."
    if re.search(r"\ballianz\b", text, re.IGNORECASE):
        return "Allianz"
    for line in text.splitlines()[:20]:
        clean = re.sub(r"\s+", " ", line).strip()
        if len(clean) >= 4 and not re.search(r"\d{2}[/-]\d{2}[/-]\d{2,4}", clean):
            return clean[:80]
    return "Aseguradora sin identificar"


def build_default_template(insurer: str) -> dict[str, Any]:
    return {
        "insurer": insurer,
        "fields": DEFAULT_FIELD_PATTERNS.copy(),
        "recordMode": _record_mode_for_insurer(insurer),
        "updatedAt": now_iso(),
    }


def _record_mode_for_insurer(insurer: str, fallback: str = "line") -> str:
    normalized = (insurer or "").lower()
    if "reale" in normalized:
        return "reale-table"
    if "allianz" in normalized:
        return "allianz-table"
    return fallback


def extract_with_template(text: str, template: dict[str, Any]) -> dict[str, Any]:
    fields = template.get("fields", {})
    liquidation_date = normalize_date(_first_group(text, fields.get("liquidationDate", DEFAULT_FIELD_PATTERNS["liquidationDate"])))
    record_mode = template.get("recordMode", "line")
    if record_mode == "reale-table":
        liquidation_date = _extract_reale_liquidation_date(text) or liquidation_date
    rows = _extract_reale_rows(text) if record_mode == "reale-table" or "RAMO PÓLIZA RECIBO" in text else []
    if record_mode == "allianz-table":
        rows = _extract_allianz_rows(text)

    if not rows:
        rows = _extract_line_rows(text, fields)

    if not rows:
        rows = _extract_cluster_rows(text, fields)

    if rows and not liquidation_date:
        liquidation_date = normalize_date(_first_group(text, r"\b(\d{1,2}/\d{1,2}/\d{4})\b"))

    for row in rows:
        row["primaNeta"] = normalize_money(row.get("primaNeta"))
        row.setdefault("tomador", "")

    total_premium = round(sum(row["primaNeta"] for row in rows), 2)
    populated_fields = sum(1 for row in rows for key in ("poliza", "tomador", "primaNeta") if row.get(key))
    possible_fields = max(len(rows) * 3, 1)
    confidence = min(0.98, round(populated_fields / possible_fields, 2)) if rows else 0.0

    return {
        "liquidationDate": liquidation_date,
        "rows": rows,
        "totals": {"policies": len(rows), "netPremium": total_premium},
        "confidence": confidence,
    }


def _first_group(text: str, pattern: str | None) -> str:
    if not pattern:
        return ""
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _extract_line_rows(text: str, fields: dict[str, str]) -> list[dict[str, Any]]:
    policy_pattern = fields.get("policy", DEFAULT_FIELD_PATTERNS["policy"])
    holder_pattern = fields.get("holder", DEFAULT_FIELD_PATTERNS["holder"])
    premium_pattern = fields.get("netPremium", DEFAULT_FIELD_PATTERNS["netPremium"])
    rows: list[dict[str, Any]] = []

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        policy = _first_group(line, policy_pattern)
        premium = _first_group(line, premium_pattern)
        if not policy:
            policy_candidates = re.findall(r"\b[A-Z0-9][A-Z0-9./-]{5,}\b", line)
            policy = policy_candidates[0] if policy_candidates else ""
        if not premium:
            money_candidates = re.findall(r"(?:€|EUR)?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+\.\d{2}", line)
            premium = money_candidates[-1] if money_candidates else ""
        if not policy or not premium:
            continue
        holder = _first_group(line, holder_pattern)
        if not holder:
            holder = _infer_holder_from_line(line, policy, premium)
        rows.append({"poliza": policy.strip(), "tomador": holder.strip(), "primaNeta": premium})

    return _dedupe_rows(rows)


def _extract_reale_rows(text: str) -> list[dict[str, Any]]:
    vertical_rows = _extract_reale_vertical_rows(text)
    if vertical_rows:
        return vertical_rows

    rows: list[dict[str, Any]] = []
    pending: str | None = None
    line_pattern = re.compile(
        r"^(?P<ramo>\d{3})\s+"
        r"(?P<poliza>\d{10,14})\s+"
        r"(?P<recibo>\d{10,14})\s*"
        r"(?P<rest>.+?)\s+"
        r"(?P<fecha>\d{2}[/-]\d{2}[/-]\d{4})\s+"
        r"(?P<tipo>[A-Z]{3})\s+"
        r"(?P<prima>-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})"
        r"(?:\s|$)"
    )

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if "Total Primas Cobradas" in line:
            break
        if pending:
            candidate = f"{pending} {line}"
            match = line_pattern.match(candidate)
            if match:
                rows.append(_reale_match_to_row(match))
                pending = None
                continue
            pending = None

        match = line_pattern.match(line)
        if match:
            rows.append(_reale_match_to_row(match))
            continue

        if re.match(r"^\d{3}\s+\d{10,14}\s+\d{10,14}\s+[A-ZÁÉÍÓÚÄÖÜÑ.,&' -]+$", line):
            pending = line

    return rows


def _extract_reale_liquidation_date(text: str) -> str:
    patterns = [
        r"FECHA\s+EXPEDICI[ÓO]N\s+FACTURA\s*:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"PERIODO\s+FACTURADO\s*:\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+a\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"N[ºO]\s*FACTURA\s*:\s*RS\d+/\d{2}(\d{2})(\d{2})",
    ]
    for pattern in patterns[:2]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_date(match.group(1))
    match = re.search(patterns[2], text, re.IGNORECASE)
    if match:
        year = int(f"20{match.group(1)}")
        month = int(match.group(2))
        return f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"
    return ""


def _extract_reale_vertical_rows(text: str) -> list[dict[str, Any]]:
    lines = [re.sub(r"\s+", " ", raw_line).strip() for raw_line in text.splitlines()]
    rows: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if "Total Primas Cobradas" in line:
            break
        if not re.fullmatch(r"\d{3}", line or ""):
            index += 1
            continue
        if index + 2 >= len(lines):
            break
        poliza = lines[index + 1]
        recibo = lines[index + 2]
        if not re.fullmatch(r"\d{10,14}", poliza or "") or not re.fullmatch(r"\d{10,14}", recibo or ""):
            index += 1
            continue

        holder_parts: list[str] = []
        cursor = index + 3
        while cursor < len(lines) and not re.fullmatch(r"\d{2}[/-]\d{2}[/-]\d{4}", lines[cursor] or ""):
            if lines[cursor] and not lines[cursor].startswith("Página "):
                holder_parts.append(lines[cursor])
            cursor += 1
        if cursor + 2 >= len(lines):
            index += 1
            continue
        receipt_date = lines[cursor]
        row_type = lines[cursor + 1]
        premium = lines[cursor + 2]
        if not re.fullmatch(r"[A-Z]{3}", row_type or "") or not re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}", premium or ""):
            index += 1
            continue

        rows.append(
            {
                "ramo": line,
                "poliza": poliza,
                "recibo": recibo,
                "tomador": " ".join(holder_parts).strip(),
                "fechaRecibo": normalize_date(receipt_date),
                "tipo": row_type,
                "primaNeta": premium,
            }
        )
        index = cursor + 6

    return rows


def _reale_match_to_row(match: re.Match[str]) -> dict[str, Any]:
    return {
        "ramo": match.group("ramo"),
        "poliza": match.group("poliza"),
        "recibo": match.group("recibo"),
        "tomador": match.group("rest").strip(),
        "fechaRecibo": normalize_date(match.group("fecha")),
        "tipo": match.group("tipo"),
        "primaNeta": match.group("prima"),
    }


def _extract_allianz_rows(text: str) -> list[dict[str, Any]]:
    table_text = _text_after_allianz_policy_header(text)
    if not table_text:
        return []
    return _dedupe_rows(_extract_allianz_horizontal_rows(table_text) + _extract_allianz_vertical_rows(table_text))


def _text_after_allianz_policy_header(text: str) -> str:
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        line = normalize_for_match(raw_line)
        if "poliza" in line and "recibo" in line and ("venc" in line or "vto" in line):
            return "\n".join(lines[index + 1 :])
    return ""


def _extract_allianz_horizontal_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    money_pattern = r"-?\d{1,3}(?:[.\s]\d{3})*,\d{2}|-?\d+,\d{2}|-?\d+\.\d{2}"
    vencimiento_pattern = r"\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}"
    line_pattern = re.compile(
        rf"(?P<poliza>[A-Z0-9][A-Z0-9./-]{{5,24}})\s+"
        rf"(?P<recibo>[A-Z0-9][A-Z0-9./-]{{4,24}})\s+"
        rf"(?P<vencimiento>{vencimiento_pattern})\s+"
        rf"(?P<body>.+)\s+"
        rf"(?P<prima>{money_pattern})"
        rf"(?:\s|$)",
        re.IGNORECASE,
    )

    pending = ""
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if _looks_like_table_total(line) and not re.match(r"^[A-Z0-9][A-Z0-9./-]{5,24}\s+", line):
            pending = ""
            continue
        candidate = f"{pending} {line}".strip() if pending else line
        match = line_pattern.search(candidate)
        if match:
            rows.append(_allianz_match_to_row(match))
            pending = ""
            continue
        pending = candidate if re.search(r"\b[A-Z0-9][A-Z0-9./-]{5,24}\b", candidate) else ""
    return rows


def _extract_allianz_vertical_rows(text: str) -> list[dict[str, Any]]:
    lines = [re.sub(r"\s+", " ", raw_line).strip() for raw_line in text.splitlines()]
    rows: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        if _looks_like_table_total(lines[index]):
            break
        poliza = lines[index]
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9./-]{5,24}", poliza or ""):
            index += 1
            continue
        if index + 4 >= len(lines):
            break
        recibo = lines[index + 1]
        vencimiento = lines[index + 2]
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9./-]{4,24}", recibo or "") or not _allianz_due_date(vencimiento):
            index += 1
            continue
        holder_parts: list[str] = []
        cursor = index + 3
        while cursor < len(lines) and not re.fullmatch(r"-?\d{1,3}(?:[.\s]\d{3})*,\d{2}|-?\d+,\d{2}|-?\d+\.\d{2}", lines[cursor] or ""):
            if lines[cursor]:
                holder_parts.append(lines[cursor])
            cursor += 1
        if cursor >= len(lines):
            index += 1
            continue
        rows.append(
            {
                "poliza": _normalize_allianz_policy(poliza),
                "recibo": recibo,
                "fechaRecibo": _allianz_due_date(vencimiento),
                "tomador": " ".join(holder_parts).strip(),
                "primaNeta": lines[cursor],
            }
        )
        index = cursor + 1
    return rows


def _allianz_match_to_row(match: re.Match[str]) -> dict[str, Any]:
    return {
        "poliza": _normalize_allianz_policy(match.group("poliza")),
        "recibo": match.group("recibo").strip(),
        "fechaRecibo": _allianz_due_date(match.group("vencimiento")),
        "tomador": _clean_allianz_holder(match.group("body")),
        "primaNeta": match.group("prima"),
    }


def _normalize_allianz_policy(raw: str) -> str:
    policy = re.sub(r"\s+", "", raw or "").strip()
    if policy.isdigit() and policy.endswith("00000") and len(policy) > 5:
        return policy[:-5]
    return policy


def _allianz_due_date(raw: str) -> str:
    value = re.sub(r"\s+", "", raw or "")
    patterns = [
        ("%m/%Y", r"^\d{1,2}/\d{4}$"),
        ("%m-%Y", r"^\d{1,2}-\d{4}$"),
        ("%m/%y", r"^\d{1,2}/\d{2}$"),
        ("%m-%y", r"^\d{1,2}-\d{2}$"),
        ("%d/%m/%Y", r"^\d{1,2}/\d{1,2}/\d{4}$"),
        ("%d-%m-%Y", r"^\d{1,2}-\d{1,2}-\d{4}$"),
        ("%Y/%m", r"^\d{4}/\d{1,2}$"),
        ("%Y-%m", r"^\d{4}-\d{1,2}$"),
    ]
    for fmt, pattern in patterns:
        if not re.fullmatch(pattern, value):
            continue
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        year = parsed.year
        month = parsed.month
        return f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"
    return ""


def _clean_allianz_holder(raw: str) -> str:
    clean = re.sub(r"\s+", " ", raw or "").strip()
    clean = re.sub(r"^(?:Prod|Cart|Anul|Ext|Dev)(?:\s+\*)?(?:\s+\d{1,2}[/-]\d{2,4})?\s+", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+-?\d{1,3}(?:[.\s]\d{3})*,\d{2}(?:\s+-?\d{1,3}(?:[.\s]\d{3})*,\d{2})*$", "", clean)
    clean = re.sub(
        r"^(?:ACC\.\s*COLECTIVO|R\.C\.GENERAL|R\.C\.PYME|R\.C\.\s*GENERAL|R\.C\.\s*PYME|MULT\.\s*COMERCIO|MULTIRRIESGO|EMBARCACIONES\s+RECREO|EMBARCACIONES|RECREO|EMBARC)\s+",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+\(R\d+\)$", "", clean)
    clean = re.sub(r"\b(?:EUR|€|T\.?\s*RECIBO|TOTAL)\b.*$", "", clean, flags=re.IGNORECASE).strip()
    return clean[:120]


def _looks_like_table_total(line: str) -> bool:
    return bool(re.search(r"\b(total|subtotal|suma)\b", line or "", re.IGNORECASE))


def _extract_cluster_rows(text: str, fields: dict[str, str]) -> list[dict[str, Any]]:
    policies = re.findall(fields.get("policy", DEFAULT_FIELD_PATTERNS["policy"]), text, re.IGNORECASE)
    holders = re.findall(fields.get("holder", DEFAULT_FIELD_PATTERNS["holder"]), text, re.IGNORECASE)
    premiums = re.findall(fields.get("netPremium", DEFAULT_FIELD_PATTERNS["netPremium"]), text, re.IGNORECASE)
    total = min(len(policies), len(premiums))
    rows = []
    for index in range(total):
        rows.append(
            {
                "poliza": str(policies[index]).strip(),
                "tomador": str(holders[index]).strip() if index < len(holders) else "",
                "primaNeta": premiums[index],
            }
        )
    return _dedupe_rows(rows)


def _infer_holder_from_line(line: str, policy: str, premium: str) -> str:
    clean = line.replace(policy, " ").replace(str(premium), " ")
    clean = re.sub(r"(pol(?:i|í)za|prima\s+neta|prima|neto|tomador|cliente|asegurado|EUR|€)", " ", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" :-#")
    return clean[:90]


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for row in rows:
        key = str(row.get("poliza", "")).strip().upper()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def scan_document(payload: dict[str, Any]) -> dict[str, Any]:
    state = ensure_state()
    source, pdf_bytes = download_pdf(payload["driveUrl"])
    text, page_count = extract_pdf_text(pdf_bytes)
    insurer = infer_insurer(text, payload.get("insurer", ""))
    template = (payload.get("template") or state["templates"].get(insurer) or build_default_template(insurer)).copy()
    template["recordMode"] = _record_mode_for_insurer(insurer, template.get("recordMode", "line"))
    extraction = extract_with_template(text, template)
    mark_pmp_rows(extraction["rows"])
    return {
        "documentId": source.document_id,
        "sourceUrl": source.original_url,
        "pageCount": page_count,
        "insurer": insurer,
        "template": template,
        "textPreview": text[:6000],
        **extraction,
    }


def save_template(payload: dict[str, Any]) -> dict[str, Any]:
    state = ensure_state()
    insurer = payload.get("insurer", "").strip()
    if not insurer:
        raise ValueError("La aseguradora es obligatoria para guardar la plantilla.")
    template = payload.get("template") or build_default_template(insurer)
    template["insurer"] = insurer
    template["recordMode"] = _record_mode_for_insurer(insurer, template.get("recordMode", "line"))
    template["updatedAt"] = now_iso()
    state["templates"][insurer] = template
    save_state(state)
    return {"ok": True, "template": template, "templates": list_templates()}


def list_templates() -> list[dict[str, Any]]:
    state = ensure_state()
    return sorted(state["templates"].values(), key=lambda item: item.get("insurer", ""))


def commit_scan(payload: dict[str, Any]) -> dict[str, Any]:
    state = ensure_state()
    insurer = payload.get("insurer", "").strip() or "Aseguradora sin identificar"
    liquidation_date = payload.get("liquidationDate", "")
    document_id = payload.get("documentId", "")
    scanned_at = now_iso()

    use_row_date = "allianz" in insurer.lower()
    rows = _normalize_rows_before_pmp(payload.get("rows", []), use_row_date)
    rows = mark_pmp_rows(rows)
    sheet_rows = [
        {
            "ID Hoja de Calculo": document_id,
            "Aseguradora": insurer,
            "Poliza": row.get("poliza", ""),
            "Fecha": (row.get("fechaRecibo") if use_row_date else "") or liquidation_date,
            "Tomador": row.get("tomador", ""),
            "Prima": normalize_money(row.get("primaNeta")),
            "Recibo": row.get("recibo", ""),
            "PMP": row.get("PMP", "No"),
        }
        for row in rows
    ]
    total_premium = round(sum(float(row["Prima"]) for row in sheet_rows), 2)
    history_row = {
        "ultima fecha de escaneo": scanned_at,
        "id del documento": document_id,
        "total polizas": len(sheet_rows),
        "total monto prima neta": total_premium,
        "nombre de la aseguradora": insurer,
        "mes y año del documento escaneado": month_year(liquidation_date),
    }

    state["sheetRows"] = [
        row
        for row in state["sheetRows"]
        if row.get("_documentId") != document_id and row.get("ID Hoja de Calculo") != document_id
    ]
    for row in sheet_rows:
        row["_documentId"] = document_id
    state["sheetRows"].extend(sheet_rows)
    state["historyRows"] = [row for row in state["historyRows"] if row.get("id del documento") != document_id]
    state["historyRows"].append(history_row)
    state["scans"][document_id] = {
        "documentId": document_id,
        "insurer": insurer,
        "liquidationDate": liquidation_date,
        "pageCount": payload.get("pageCount", ""),
        "rows": rows,
        "totals": {"policies": len(sheet_rows), "netPremium": total_premium},
        "scannedAt": scanned_at,
    }
    save_state(state)
    sync_status = sync_google_sheet(sheet_rows, history_row, state.get("googleSheetUrl", ""))
    return {"ok": True, "sheetRows": sheet_rows, "historyRow": history_row, "sync": sync_status, "summary": scanner_summary()}


def sync_google_sheet(sheet_rows: list[dict[str, Any]], history_row: dict[str, Any], sheet_url: str = "") -> dict[str, Any]:
    webhook_url = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
    if not webhook_url:
        try:
            return sync_google_sheet_with_api(sheet_rows, history_row, sheet_url)
        except Exception as error:  # noqa: BLE001
            return {
                "mode": "error",
                "sheetUrl": sheet_url,
                "message": f"No se pudo actualizar Google Sheet. El escaneo quedó guardado localmente. Detalle: {error}",
            }
    payload = {"rows": sheet_rows, "history": history_row}
    request = Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "PrudentialScanner/1.0"},
        method="POST",
    )
    with build_opener().open(request, timeout=30) as response:
        response.read()
        return {"mode": "webhook", "status": response.status, "sheetUrl": sheet_url}


def sync_google_sheet_with_api(
    sheet_rows: list[dict[str, Any]], history_row: dict[str, Any], sheet_url: str
) -> dict[str, Any]:
    spreadsheet_id = _spreadsheet_id_from_url(sheet_url)
    if not spreadsheet_id:
        raise ValueError("No hay Google Sheet destino configurado.")
    if not sheet_rows:
        raise ValueError("No hay filas para sincronizar.")

    token = _google_access_token()
    document_id = str(history_row.get("id del documento", ""))
    log_values = _get_sheet_values(spreadsheet_id, "Log!A:E", token)
    if not log_values:
        _put_sheet_values(
            spreadsheet_id,
            "Log!A1:E1",
            [["ID Hoja de Calculo", "Fecha", "Registros", "Total Prima", "Empresa"]],
            token,
        )
    _append_sheet_values(
        spreadsheet_id,
        "Log!A:E",
        [
            [
                document_id,
                datetime.now().date().isoformat(),
                history_row.get("total polizas", 0),
                history_row.get("total monto prima neta", 0),
                history_row.get("nombre de la aseguradora", ""),
            ]
        ],
        token,
    )

    liquidation_values = _get_sheet_values(spreadsheet_id, "Liquidaciones!A:H", token)
    header = ["ID Hoja de Calculo", "Aseguradora", "Poliza", "Fecha", "Tomador", "Prima", "Recibo", "PMP"]
    existing_header = liquidation_values[0] if liquidation_values else header
    existing_rows = [_normalize_liquidation_sheet_row(existing_header, row) for row in liquidation_values[1:]] if liquidation_values else []
    filtered_rows = [row for row in existing_rows if (row[0] if row else "") != document_id]
    new_rows = [
        [
            row.get("ID Hoja de Calculo", document_id),
            row.get("Aseguradora", row.get("aseguradora", "")),
            _sheet_text(row.get("Poliza", "")),
            row.get("Fecha", ""),
            row.get("Tomador", ""),
            row.get("Prima", ""),
            row.get("Recibo", ""),
            row.get("PMP", "No"),
        ]
        for row in sheet_rows
    ]
    _clear_sheet_values(spreadsheet_id, "Liquidaciones!A:H", token)
    _put_sheet_values(spreadsheet_id, "Liquidaciones!A1:H", [header, *filtered_rows, *new_rows], token, value_input_option="RAW")
    return {
        "mode": "google-api",
        "sheetUrl": sheet_url,
        "message": "Google Sheet actualizado: Log agregado y Liquidaciones reemplazadas para el ID escaneado.",
    }


def _spreadsheet_id_from_url(raw: str) -> str:
    match = re.search(r"/spreadsheets/d/([^/]+)", raw or "")
    return match.group(1) if match else raw.strip()


def _sheet_text(value: Any) -> str:
    return str(value or "").lstrip("'")


def _normalize_rows_before_pmp(rows: list[dict[str, Any]], is_allianz: bool) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        if is_allianz:
            next_row["poliza"] = _normalize_allianz_policy(next_row.get("poliza", ""))
        normalized_rows.append(next_row)
    return normalized_rows


def _normalize_liquidation_sheet_row(header: list[Any], row: list[Any]) -> list[Any]:
    values = list(row) + [""] * max(0, 8 - len(row))
    normalized_header = [normalize_for_match(str(item)) for item in header]

    if len(values) >= 8 and _looks_like_policy(values[1]) and _looks_like_insurer(values[7]):
        return [values[0], values[7], _sheet_text(values[1]), values[2], values[3], values[4], values[5], values[6]]

    if "aseguradora" in normalized_header:
        index = {name: normalized_header.index(name) for name in normalized_header}
        return [
            values[index.get("id hoja de calculo", 0)],
            values[index.get("aseguradora", 1)],
            _sheet_text(values[index.get("poliza", 2)]),
            values[index.get("fecha", 3)],
            values[index.get("tomador", 4)],
            values[index.get("prima", 5)],
            values[index.get("recibo", 6)],
            values[index.get("pmp", 7)],
        ]

    return [values[0], values[7], _sheet_text(values[1]), values[2], values[3], values[4], values[5], values[6]]


def _looks_like_policy(value: Any) -> bool:
    return bool(re.fullmatch(r"'?[A-Z0-9][A-Z0-9./-]{5,24}", str(value or "").strip()))


def _looks_like_insurer(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(name in text for name in ("reale", "allianz", "axa", "zurich", "mapfre", "generali", "sanitas"))


def _google_access_token() -> str:
    env_token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if service_account_json:
        return _service_account_access_token_from_json(service_account_json)

    service_account_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "").strip()
    if service_account_b64:
        decoded = base64.b64decode(service_account_b64).decode("utf-8")
        return _service_account_access_token_from_json(decoded)

    service_account_file = Path(os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", DEFAULT_SERVICE_ACCOUNT_FILE)).expanduser()
    if service_account_file.exists():
        return _service_account_access_token(service_account_file)

    scoped_command = [
        "gcloud",
        "auth",
        "application-default",
        "print-access-token",
        f"--scopes={','.join(GOOGLE_SHEETS_SCOPES)}",
    ]
    try:
        return subprocess.check_output(scoped_command, text=True, stderr=subprocess.STDOUT).strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as scoped_error:
        try:
            return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True, stderr=subprocess.STDOUT).strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as fallback_error:
            scoped_output = getattr(scoped_error, "output", str(scoped_error))
            fallback_output = getattr(fallback_error, "output", str(fallback_error))
            raise RuntimeError(
                "No hay credenciales de Google Sheets disponibles. Ejecuta "
                "`gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive.file` "
                f"y vuelve a intentar. Detalle: {scoped_output or fallback_output}"
            ) from fallback_error


def _service_account_access_token(credentials_path: Path) -> str:
    with credentials_path.open("r", encoding="utf-8") as handle:
        credentials = json.load(handle)
    return _service_account_access_token_from_credentials(credentials)


def _service_account_access_token_from_json(credentials_json: str) -> str:
    try:
        credentials = json.loads(credentials_json)
    except json.JSONDecodeError as error:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON no contiene un JSON válido.") from error
    return _service_account_access_token_from_credentials(credentials)


def _service_account_access_token_from_credentials(credentials: dict[str, Any]) -> str:
    now = int(time.time())
    claim = {
        "iss": credentials["client_email"],
        "scope": " ".join(GOOGLE_SHEETS_SCOPES),
        "aud": credentials.get("token_uri", "https://oauth2.googleapis.com/token"),
        "iat": now,
        "exp": now + 3600,
    }
    assertion = _signed_jwt({"alg": "RS256", "typ": "JWT"}, claim, credentials["private_key"])
    request = Request(
        credentials.get("token_uri", "https://oauth2.googleapis.com/token"),
        data=urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "PrudentialScanner/1.0"},
        method="POST",
    )
    opener = build_opener()
    try:
        response = opener.open(request, timeout=30)
    except Exception as error:
        if "CERTIFICATE_VERIFY_FAILED" not in str(error):
            raise _google_sheet_error(error) from error
        opener = build_opener(HTTPSHandler(context=ssl._create_unverified_context()))  # noqa: S323
        try:
            response = opener.open(request, timeout=30)
        except Exception as retry_error:
            raise _google_sheet_error(retry_error) from retry_error
    with response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["access_token"]


def _signed_jwt(header: dict[str, Any], claim: dict[str, Any], private_key_pem: str) -> str:
    signing_input = f"{_base64url_json(header)}.{_base64url_json(claim)}".encode("ascii")
    with tempfile.NamedTemporaryFile("wb", delete=False) as input_file:
        input_file.write(signing_input)
        input_path = input_file.name
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as key_file:
        key_file.write(private_key_pem)
        key_path = key_file.name
    try:
        signature = subprocess.check_output(["openssl", "dgst", "-sha256", "-sign", key_path, input_path])
    finally:
        Path(input_path).unlink(missing_ok=True)
        Path(key_path).unlink(missing_ok=True)
    return f"{signing_input.decode('ascii')}.{_base64url(signature)}"


def _base64url_json(payload: dict[str, Any]) -> str:
    return _base64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _base64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _google_sheets_request(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "PrudentialScanner/1.0",
        },
        method=method,
    )
    opener = build_opener()
    try:
        response = opener.open(request, timeout=30)
    except Exception as error:
        if "CERTIFICATE_VERIFY_FAILED" not in str(error):
            raise _google_sheet_error(error) from error
        opener = build_opener(HTTPSHandler(context=ssl._create_unverified_context()))  # noqa: S323
        try:
            response = opener.open(request, timeout=30)
        except Exception as retry_error:
            raise _google_sheet_error(retry_error) from retry_error
    with response:
        body = response.read()
    return json.loads(body.decode("utf-8")) if body else {}


def _google_sheet_error(error: Exception) -> Exception:
    if not isinstance(error, HTTPError):
        return error
    body = error.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
        message = payload.get("error", {}).get("message", body)
        reason = payload.get("error", {}).get("status", "")
    except json.JSONDecodeError:
        message = body
        reason = ""
    if "insufficient authentication scopes" in message.lower():
        message = (
            "El usuario de gcloud no tiene permisos de Google Sheets. Ejecuta "
            "`gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive.file` "
            "con la cuenta que tiene acceso a la hoja."
        )
    return RuntimeError(f"Google Sheets API {error.code} {reason}: {message}")


def _sheet_values_url(spreadsheet_id: str, sheet_range: str, suffix: str = "") -> str:
    encoded_range = quote(sheet_range, safe="")
    return f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}{suffix}"


def _get_sheet_values(spreadsheet_id: str, sheet_range: str, token: str) -> list[list[Any]]:
    payload = _google_sheets_request("GET", _sheet_values_url(spreadsheet_id, sheet_range), token)
    return payload.get("values", [])


def _put_sheet_values(
    spreadsheet_id: str,
    sheet_range: str,
    values: list[list[Any]],
    token: str,
    value_input_option: str = "USER_ENTERED",
) -> None:
    _google_sheets_request(
        "PUT",
        _sheet_values_url(spreadsheet_id, sheet_range, f"?valueInputOption={quote(value_input_option)}"),
        token,
        {"range": sheet_range, "majorDimension": "ROWS", "values": values},
    )


def _append_sheet_values(spreadsheet_id: str, sheet_range: str, values: list[list[Any]], token: str) -> None:
    _google_sheets_request(
        "POST",
        _sheet_values_url(spreadsheet_id, sheet_range, ":append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"),
        token,
        {"range": sheet_range, "majorDimension": "ROWS", "values": values},
    )


def _clear_sheet_values(spreadsheet_id: str, sheet_range: str, token: str) -> None:
    _google_sheets_request("POST", _sheet_values_url(spreadsheet_id, sheet_range, ":clear"), token, {})


def scanner_summary() -> dict[str, Any]:
    state = ensure_state()
    rows = state.get("sheetRows", [])
    history = sorted(state.get("historyRows", []), key=lambda item: item.get("ultima fecha de escaneo", ""), reverse=True)
    last_scan = None
    if history:
        last_scan = state.get("scans", {}).get(history[0].get("id del documento"))
    return {
        "templates": list_templates(),
        "historyRows": history,
        "sheetRows": rows,
        "lastScan": last_scan,
        "googleSheetUrl": state.get("googleSheetUrl", ""),
        "totals": {
            "templates": len(state.get("templates", {})),
            "scans": len(history),
            "policies": len(rows),
            "netPremium": round(sum(normalize_money(row.get("Prima", row.get("prima neta"))) for row in rows), 2),
        },
        "exports": {
            "sheetCsv": str(SHEET_ROWS_PATH),
            "pmpCsv": str(PMP_ROWS_PATH),
            "historyCsv": str(HISTORY_ROWS_PATH),
        },
    }


def parse_json_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def csv_text(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()
