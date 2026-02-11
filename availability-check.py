import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup


DEFAULT_URL = "https://myinl.inll.lu/language/french-27/standard-blended-learning-252"
DEFAULT_REFERENCES = {"FR0074-7681", "FR0074-7682"}


@dataclass
class Session:
    location: str
    schedule: str
    hours: str
    days: str
    start_date: str
    end_date: str
    fee: str
    reference: str
    availability: str
    action_text: str


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def classify_availability(*texts: str) -> str:
    t = " ".join(texts).lower()
    if any(k in t for k in ("full", "sold out", "no places", "closed", "unavailable")):
        return "unavailable"
    return "available"


def fetch_html(url: str, timeout: int = 30) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; INLL-availability-check/1.0)",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_tables(soup: BeautifulSoup) -> List[Tuple[List[str], List[Tuple[List[str], str]]]]:
    tables = []
    for table in soup.find_all("table"):
        headers = []
        header_row = table.find("tr")
        if header_row:
            headers = [
                normalize_space(th.get_text(" ", strip=True))
                for th in header_row.find_all(["th", "td"])
            ]
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [normalize_space(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            action_text = " ".join(
                normalize_space(a.get_text(" ", strip=True))
                for a in tr.find_all(["a", "button"])
            )
            rows.append((cells, action_text))
        tables.append((headers, rows))
    return tables


def pick_session_table(tables: List[Tuple[List[str], List[Tuple[List[str], str]]]]) -> Optional[Tuple[List[str], List[Tuple[List[str], str]]]]:
    best = None
    best_score = 0
    for headers, rows in tables:
        header_text = " ".join(h.lower() for h in headers)
        score = 0
        if "location" in header_text:
            score += 2
        if "schedule" in header_text:
            score += 2
        if "start" in header_text and "date" in header_text:
            score += 2
        if "reference" in header_text:
            score += 2
        if len(rows) >= 3:
            score += 1
        if score > best_score:
            best_score = score
            best = (headers, rows)
    return best


def build_sessions_from_table(headers: List[str], rows: List[Tuple[List[str], str]]) -> List[Session]:
    headers_l = [h.lower() for h in headers]

    def idx_of(*names: str) -> Optional[int]:
        for name in names:
            if name in headers_l:
                return headers_l.index(name)
        return None

    idx_location = idx_of("location")
    idx_schedule = idx_of("schedule")
    idx_hours = idx_of("hours")
    idx_days = idx_of("days")
    idx_start_date = idx_of("start date", "start date ")
    idx_end_date = idx_of("end date", "end date ")
    idx_fee = idx_of("fee")
    idx_reference = idx_of("reference")

    sessions = []
    for cells, action_text in rows:
        def safe_get(idx: Optional[int]) -> str:
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx]

        row_text = " ".join(cells)
        availability = classify_availability(action_text, row_text)
        sessions.append(
            Session(
                location=safe_get(idx_location),
                schedule=safe_get(idx_schedule),
                hours=safe_get(idx_hours),
                days=safe_get(idx_days),
                start_date=safe_get(idx_start_date),
                end_date=safe_get(idx_end_date),
                fee=safe_get(idx_fee),
                reference=safe_get(idx_reference),
                availability=availability,
                action_text=action_text,
            )
        )
    return sessions


def fallback_extract_sessions(text: str) -> List[Session]:
    sessions = []
    pattern = re.compile(
        r"(?P<location>INLL\s+\w+)\s+"
        r"(?P<schedule>\d{2}:\d{2}-\d{2}:\d{2})\s+"
        r"(?P<days>[A-Za-z-]+)\s+"
        r"(?P<start>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
        r"(?P<end>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
        r"(?P<fee>\d+(\.\d+)?)\s+"
        r"(?P<reference>FR\d{4}-\d+)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        action_text = ""
        sessions.append(
            Session(
                location=match.group("location"),
                schedule=match.group("schedule"),
                hours="",
                days=match.group("days"),
                start_date=match.group("start"),
                end_date=match.group("end"),
                fee=match.group("fee"),
                reference=match.group("reference"),
                availability=classify_availability(action_text),
                action_text=action_text,
            )
        )
    return sessions


def output_sessions(sessions: Iterable[Session], fmt: str) -> None:
    sessions = list(sessions)
    if fmt == "json":
        print(json.dumps([asdict(s) for s in sessions], indent=2))
        return
    if fmt == "csv":
        writer = csv.DictWriter(
            sys.stdout,
            fieldnames=list(asdict(sessions[0]).keys()) if sessions else [],
            lineterminator="\n",
        )
        writer.writeheader()
        for s in sessions:
            writer.writerow(asdict(s))
        return

    if not sessions:
        print("No sessions found.")
        return

    for s in sessions:
        print(
            f"{s.reference} | {s.location} | {s.schedule} | {s.days} | "
            f"{s.start_date} -> {s.end_date} | {s.fee} | {s.availability}"
        )


def check_once(url: str) -> List[Session]:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    tables = extract_tables(soup)
    selected = pick_session_table(tables)

    sessions: List[Session] = []
    if selected:
        headers, rows = selected
        sessions = build_sessions_from_table(headers, rows)

    if not sessions:
        sessions = fallback_extract_sessions(soup.get_text("\n", strip=True))

    wanted = DEFAULT_REFERENCES
    sessions = [s for s in sessions if s.reference in wanted]
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser(description="Check availability of INLL sessions.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Course offer URL")
    parser.add_argument("--format", choices=["text", "json", "csv"], default="text")
    parser.add_argument("--watch", action="store_true", help="Poll every interval seconds")
    parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    parser.add_argument(
        "--references",
        help="Comma-separated list of session references to include (default: FR0074-7681,FR0074-7682)",
    )
    args = parser.parse_args()

    if args.watch:
        while True:
            sessions = check_once(args.url)
            if args.references:
                wanted = {r.strip() for r in args.references.split(",") if r.strip()}
                sessions = [s for s in sessions if s.reference in wanted]

            output_sessions(sessions, args.format)
            time.sleep(max(10, args.interval))
    else:
        sessions = check_once(args.url)
        if args.references:
            wanted = {r.strip() for r in args.references.split(",") if r.strip()}
            sessions = [s for s in sessions if s.reference in wanted]
        output_sessions(sessions, args.format)


if __name__ == "__main__":
    main()
