#!/usr/bin/env python3
"""
calculate_probability.py

CLI calculator tool for Georgian National Unified Examinations (NAEC 2026) Admission Predictor.
- Takes: University, Program, and raw exam scores (Georgian, Foreign Language, 3rd elective subject).
- Checks minimum threshold requirements (both State and Program-specific thresholds from Cnobari).
- Calculates official scaled scores: Z = (X - E) / SD, Scaled = 15 * Z + 150.
- Calculates weighted competition score using program coefficients.
- Compares the candidate against actual historical cutoff and ranking distributions from admission_data.db.
- Outputs: Eligibility status, scaled scores breakdown, total weighted score, historical comparison, and admission probability percentage.
"""

import os
import re
import sys
import json
import math
import ctypes
import sqlite3
import argparse

# Configure UTF-8 console input/output on Windows so Georgian script works reliably
if os.name == "nt":
    try:
        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "admission_data.db")

# Valid NAEC general elective subjects (mapped to 8th/9th program code digits)
VALID_ELECTIVE_SUBJECTS = {
    "მათემატიკა",          # 4
    "ისტორია",             # 5
    "გეოგრაფია",           # 6
    "ლიტერატურა",          # 7
    "ფიზიკა",              # 8
    "ქიმია",               # 9
    "ბიოლოგია",            # 10
    "ხელოვნება",           # 12
    "სამოქალაქო განათლება", # 14
}

# Common university aliases for convenient CLI lookup
UNI_ALIASES = {
    "თსუ": "001",
    "tsu": "001",
    "ჯავახიშვილი": "001",
    "javakhishvili": "001",
    "კონსერვატორია": "002",
    "სტუ": "003",
    "gtu": "003",
    "გეპეი": "003",
    "ტექნიკური": "003",
    "თეატრალური": "004",
    "აგრუნი": "005",
    "agruni": "005",
    "აგრარული": "005",
    "თსსუ": "006",
    "tsmu": "006",
    "სამედიცინო": "006",
    "აწსუ": "009",
    "atsu": "009",
    "წერეთელი": "009",
    "ილიაუნი": "010",
    "iliauni": "010",
    "ილია": "010",
    "ilia": "010",
    "სოხუმი": "012",
    "რობაქიძე": "033",
    "ალმა მატერი": "033",
    "ფრიუნი": "036",
    "freeuni": "036",
    "თავისუფალი": "036",
    "ტვილდიანი": "052",
    "აიეტ": "052",
    "შავი ზღვის": "064",
    "ibsu": "064",
    "იბსუ": "064",
    "თელავი": "071",
    "ალტე": "085",
    "alte": "085",
    "საბაუნი": "088",
    "sabauni": "088",
    "სამხატვრო": "098",
    "ბსუ": "114",
    "bsu": "114",
    "კსუ": "115",
    "ciu": "115",
    "გაუ": "120",
    "gau": "120",
    "საქართველოს უნივერსიტეტი": "121",
    "ug": "121",
    "კავკასიის უნივერსიტეტი": "122",
    "cu": "122",
    "საავიაციო": "131",
    "გორი": "133",
    "სეუ": "143",
    "seu": "143",
    "ეროვნული უნივერსიტეტი": "143",
    "ჯიპა": "149",
    "gipa": "149",
    "ნიუ ვიჟენ": "190",
    "new vision": "190",
    "ბიზნესისა და ტექნოლოგიების": "195",
    "btu": "195",
    "ბტუ": "195",
    "ქუთაისის საერთაშორისო": "197",
    "kiu": "197",
    "კიუ": "197",
}

# English / Latin transliteration keywords for program search
PROGRAM_SEARCH_ALIASES = {
    "english philology": "ინგლისური ფილოლოგია",
    "inglisuri filologia": "ინგლისური ფილოლოგია",
    "georgian philology": "ქართული ფილოლოგია",
    "qartuli filologia": "ქართული ფილოლოგია",
    "german philology": "გერმანული ფილოლოგია",
    "french philology": "ფრანგული ფილოლოგია",
    "russian philology": "რუსული ფილოლოგია",
    "philology": "ფილოლოგია",
    "filologia": "ფილოლოგია",
    "english": "ინგლისური",
    "inglisuri": "ინგლისური",
    "law": "სამართალი",
    "samartali": "სამართალი",
    "international law": "საერთაშორისო სამართალი",
    "economics": "ეკონომიკა",
    "ekonomika": "ეკონომიკა",
    "business": "ბიზნესის ადმინისტრირება",
    "business administration": "ბიზნესის ადმინისტრირება",
    "biznesi": "ბიზნესის ადმინისტრირება",
    "computer science": "კომპიუტერული მეცნიერება",
    "kompiuteruli": "კომპიუტერული მეცნიერება",
    "psychology": "ფსიქოლოგია",
    "fsiqologia": "ფსიქოლოგია",
    "international relations": "საერთაშორისო ურთიერთობები",
    "journalism": "ჟურნალისტიკა",
    "history": "ისტორია",
    "istoria": "ისტორია",
    "mathematics": "მათემატიკა",
    "math": "მათემატიკა",
    "matematika": "მათემატიკა",
    "physics": "ფიზიკა",
    "fizika": "ფიზიკა",
    "chemistry": "ქიმია",
    "qimia": "ქიმია",
    "biology": "ბიოლოგია",
    "biologia": "ბიოლოგია",
    "medicine": "მედიკოსი",
    "tourism": "ტურიზმი",
    "turizmi": "ტურიზმი",
    "sociology": "სოციოლოგია",
    "philosophy": "ფილოსოფია",
    "archaeology": "არქეოლოგია",
}

# Strict subject aliases -> canonical subject name
SUBJECT_ALIASES = {
    # 4 = Math
    "4": "მათემატიკა",
    "math": "მათემატიკა",
    "maths": "მათემატიკა",
    "mathematics": "მათემატიკა",
    "matematika": "მათემატიკა",
    "mat": "მათემატიკა",
    "მათ": "მათემატიკა",
    "მათემატიკა": "მათემატიკა",
    # 5 = History
    "5": "ისტორია",
    "hist": "ისტორია",
    "history": "ისტორია",
    "istoria": "ისტორია",
    "ist": "ისტორია",
    "ისტ": "ისტორია",
    "ისტორია": "ისტორია",
    # 6 = Geography
    "6": "გეოგრაფია",
    "geo": "გეოგრაფია",
    "geography": "გეოგრაფია",
    "geografia": "გეოგრაფია",
    "გეო": "გეოგრაფია",
    "გეოგრაფია": "გეოგრაფია",
    # 7 = Literature
    "7": "ლიტერატურა",
    "lit": "ლიტერატურა",
    "literature": "ლიტერატურა",
    "literatura": "ლიტერატურა",
    "ლიტ": "ლიტერატურა",
    "ლიტერატურა": "ლიტერატურა",
    # 8 = Physics
    "8": "ფიზიკა",
    "phys": "ფიზიკა",
    "physics": "ფიზიკა",
    "fizika": "ფიზიკა",
    "fiz": "ფიზიკა",
    "ფიზ": "ფიზიკა",
    "ფიზიკა": "ფიზიკა",
    # 9 = Chemistry
    "9": "ქიმია",
    "chem": "ქიმია",
    "chemistry": "ქიმია",
    "qimia": "ქიმია",
    "kimia": "ქიმია",
    "ქიმ": "ქიმია",
    "ქიმია": "ქიმია",
    # 10 = Biology
    "10": "ბიოლოგია",
    "bio": "ბიოლოგია",
    "biology": "ბიოლოგია",
    "biologia": "ბიოლოგია",
    "ბიო": "ბიოლოგია",
    "ბიოლოგია": "ბიოლოგია",
    # 12 = Art
    "12": "ხელოვნება",
    "art": "ხელოვნება",
    "xelovneba": "ხელოვნება",
    "khelovneba": "ხელოვნება",
    "ხელ": "ხელოვნება",
    "ხელოვნება": "ხელოვნება",
    "სახვითი და გამოყენებითი ხელოვნება": "ხელოვნება",
    # 14 = Civics
    "14": "სამოქალაქო განათლება",
    "civ": "სამოქალაქო განათლება",
    "civics": "სამოქალაქო განათლება",
    "civic": "სამოქალაქო განათლება",
    "samoqalaqo": "სამოქალაქო განათლება",
    "samokalako": "სამოქალაქო განათლება",
    "სამოქალაქო": "სამოქალაქო განათლება",
    "სამოქალაქო განათლება": "სამოქალაქო განათლება",
}

FOREIGN_LANG_ALIASES = {
    "eng": "ინგლისური ენა",
    "english": "ინგლისური ენა",
    "ინგ": "ინგლისური ენა",
    "ინგ.": "ინგლისური ენა",
    "ინგლისური": "ინგლისური ენა",
    "ინგლისური ენა": "ინგლისური ენა",
    "rus": "რუსული ენა",
    "russian": "რუსული ენა",
    "რუს": "რუსული ენა",
    "რუს.": "რუსული ენა",
    "რუსული": "რუსული ენა",
    "რუსული ენა": "რუსული ენა",
    "ger": "გერმანული ენა",
    "deu": "გერმანული ენა",
    "german": "გერმანული ენა",
    "გერ": "გერმანული ენა",
    "გერ.": "გერმანული ენა",
    "გერმანული": "გერმანული ენა",
    "გერმანული ენა": "გერმანული ენა",
    "fra": "ფრანგული ენა",
    "fre": "ფრანგული ენა",
    "french": "ფრანგული ენა",
    "ფრან": "ფრანგული ენა",
    "ფრან.": "ფრანგული ენა",
    "ფრანგული": "ფრანგული ენა",
    "ფრანგული ენა": "ფრანგული ენა",
    "უცხოური ენა": "უცხოური ენა",
}


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function Phi(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def resolve_elective_subject(subj_input: str | None) -> str | None:
    """
    Strictly resolves an elective subject name, code, or prefix to its canonical NAEC name.
    Never performs loose inner-substring matching that could confuse subjects.
    """
    if not subj_input:
        return None
    s = subj_input.strip().lower().rstrip(".")
    if not s:
        return None

    # 1. Exact alias or code match
    if s in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[s]

    # 2. Prefix match (only when input has at least 3 characters)
    if len(s) >= 3:
        for canon in VALID_ELECTIVE_SUBJECTS:
            if canon.lower().startswith(s):
                return canon
        for alias_key, canon in SUBJECT_ALIASES.items():
            if len(alias_key) >= 4 and alias_key.startswith(s):
                return canon

    return None


def get_valid_program_electives(prog_subjects: list[dict]) -> list[dict]:
    """
    Filters a program's subjects from the database to ONLY the valid general elective
    subjects officially defined in the handbook for that program.
    """
    # First check subjects explicitly marked as elective (is_mandatory=False) in VALID_ELECTIVE_SUBJECTS
    electives = [
        s
        for s in prog_subjects
        if not s["is_mandatory"] and s["canonical_subject"] in VALID_ELECTIVE_SUBJECTS
    ]
    if electives:
        return electives

    # If a 3-subject program has a single 3rd subject (e.g. Math in Economics) where seats weren't split
    single_third = [
        s
        for s in prog_subjects
        if s["canonical_subject"] in VALID_ELECTIVE_SUBJECTS
    ]
    return single_third


def resolve_university(cur: sqlite3.Cursor, uni_query: str | None) -> list[tuple[str, str]]:
    """Resolves a university query (code, alias, or substring) to matching (uni_code, uni_name) rows."""
    if not uni_query:
        return []
    q = uni_query.strip()
    q_low = q.lower()

    if q_low in UNI_ALIASES:
        code = UNI_ALIASES[q_low]
        rows = cur.execute(
            "SELECT uni_code, uni_name FROM universities WHERE uni_code = ?", (code,)
        ).fetchall()
        if rows:
            return rows

    if q.isdigit() and len(q) <= 3:
        code = q.zfill(3)
        rows = cur.execute(
            "SELECT uni_code, uni_name FROM universities WHERE uni_code = ?", (code,)
        ).fetchall()
        if rows:
            return rows

    all_unis = cur.execute(
        "SELECT uni_code, uni_name FROM universities ORDER BY uni_code"
    ).fetchall()
    exact = [u for u in all_unis if u[1].lower() == q_low]
    if exact:
        return exact

    sub = [u for u in all_unis if q_low in u[1].lower()]
    if sub:
        return sub

    for alias, code in UNI_ALIASES.items():
        if len(alias) >= 3 and alias in q_low:
            rows = [u for u in all_unis if u[0] == code]
            if rows:
                return rows

    return []


def resolve_program(
    cur: sqlite3.Cursor, uni_query: str | None, prog_query: str
) -> tuple[dict, str | None]:
    """
    Resolves (uni_query, prog_query) to a program row dict and optional elective_code
    (if prog_query was an 8-to-10 digit full program code like '00101125').
    """
    pq = prog_query.strip()
    inferred_elective_code = None

    # Check if prog_query starts with a 7-10 digit code
    m_code = re.match(r"^(\d{7})(\d{1,3})?$", pq)
    if m_code:
        base_code = m_code.group(1)
        if m_code.group(2):
            inferred_elective_code = m_code.group(2)
        row = cur.execute(
            """
            SELECT program_code, program_name, uni_code, uni_name, total_seats,
                   accreditation, language, tuition, page_number
            FROM programs WHERE program_code = ?
            """,
            (base_code,),
        ).fetchone()
        if row:
            return (
                {
                    "program_code": row[0],
                    "program_name": row[1],
                    "uni_code": row[2],
                    "uni_name": row[3],
                    "total_seats": row[4],
                    "accreditation": row[5],
                    "language": row[6],
                    "tuition": row[7],
                    "page_number": row[8],
                },
                inferred_elective_code,
            )

    uni_matches = resolve_university(cur, uni_query) if uni_query else []
    uni_codes = [u[0] for u in uni_matches]

    if uni_query and not uni_codes:
        raise ValueError(
            f"უნივერსიტეტი ვერ მოიძებნა / University not found for query: '{uni_query}'"
        )

    if uni_codes:
        placeholders = ",".join("?" for _ in uni_codes)
        candidates = cur.execute(
            f"""
            SELECT program_code, program_name, uni_code, uni_name, total_seats,
                   accreditation, language, tuition, page_number
            FROM programs
            WHERE uni_code IN ({placeholders})
            ORDER BY program_code
            """,
            uni_codes,
        ).fetchall()
    else:
        candidates = cur.execute(
            """
            SELECT program_code, program_name, uni_code, uni_name, total_seats,
                   accreditation, language, tuition, page_number
            FROM programs
            ORDER BY program_code
            """
        ).fetchall()

    pq_low = pq.lower()
    # Translate English/Latin query if applicable
    if pq_low in PROGRAM_SEARCH_ALIASES:
        pq_low = PROGRAM_SEARCH_ALIASES[pq_low].lower()

    # 1. Exact match on program_name
    exact = [r for r in candidates if r[1].lower() == pq_low]
    if not exact:
        # 2. Starts-with match on program_name
        exact = [r for r in candidates if r[1].lower().startswith(pq_low)]
    if not exact:
        # 3. Substring match on program_name
        exact = [r for r in candidates if pq_low in r[1].lower()]
    if not exact:
        # 4. Token match (including English-to-Georgian token translation)
        raw_tokens = [t for t in pq_low.split() if t]
        tokens = [PROGRAM_SEARCH_ALIASES.get(t, t) for t in raw_tokens]
        exact = [
            r for r in candidates if all(tok in r[1].lower() for tok in tokens)
        ]
    if not exact:
        # 5. Stemmed token match (first 6 chars of each word appear in program_name)
        raw_tokens = [t for t in pq_low.split() if len(t) >= 2]
        tokens = [PROGRAM_SEARCH_ALIASES.get(t, t) for t in raw_tokens]
        stems = [t[:6] for t in tokens if len(t) >= 2]
        if stems:
            exact = [
                r for r in candidates if all(st in r[1].lower() for st in stems)
            ]

    if not exact:
        uni_desc = f" (University: {uni_matches[0][1]})" if uni_matches else ""
        sample_progs = ", ".join(f"{r[0]}:{r[1]}" for r in candidates[:6])
        hint = f" Available programs include: {sample_progs}..." if sample_progs else ""
        raise ValueError(
            f"პროგრამა ვერ მოიძებნა / Program not found for '{prog_query}'{uni_desc}.{hint}"
        )

    best = exact[0]
    return (
        {
            "program_code": best[0],
            "program_name": best[1],
            "uni_code": best[2],
            "uni_name": best[3],
            "total_seats": best[4],
            "accreditation": best[5],
            "language": best[6],
            "tuition": best[7],
            "page_number": best[8],
        },
        inferred_elective_code,
    )


def calculate_scaled_score(raw_score: float, mean: float, sd: float) -> tuple[float, float, float]:
    """
    Applies the official NAEC scaling formula:
      Z = (X - E) / SD
      Scaled_exact = 15 * Z + 150
      Scaled_official = round(Scaled_exact, 1)
    """
    z = (raw_score - mean) / sd
    scaled_exact = 15.0 * z + 150.0
    scaled_rounded = round(scaled_exact + 1e-12, 1)
    return z, scaled_exact, scaled_rounded


def estimate_admission_probability(
    is_eligible: bool,
    total_weighted_score: float,
    cutoff_info: dict | None,
    historical_scores: list[float],
) -> tuple[float, dict]:
    """
    Computes admission probability percentage and ranking analytics by comparing
    the candidate's total weighted competition score against historical cutoffs
    and candidate score distributions in admission_data.db.
    """
    if not cutoff_info or not historical_scores:
        if not is_eligible:
            return 0.0, {
                "status_note": "ჩაჭრილია (მინიმალური კომპეტენციის ზღვარი ვერ გადალახა) / Failed minimum competency threshold",
                "simulated_rank": None,
                "admitted_count": 0,
                "seats": cutoff_info["seats"] if cutoff_info else 0,
                "vacancy_count": cutoff_info["seats"] if cutoff_info else 0,
                "cutoff_score": 0.0,
                "mean_score": 0.0,
                "sd_score": 0.0,
                "median_score": 0.0,
                "max_score": 0.0,
                "beaten_percentile": 0.0,
                "diff_from_cutoff": 0.0,
                "diff_from_mean": 0.0,
            }
        return 95.0, {
            "status_note": "რანჟირებულ სიაში კონკურსი დაბალია (ვაკანტური ადგილები) / Low competition (vacant seats available)",
            "simulated_rank": 1,
            "admitted_count": 0,
            "seats": cutoff_info["seats"] if cutoff_info else 0,
            "vacancy_count": cutoff_info["seats"] if cutoff_info else 0,
            "cutoff_score": 0.0,
            "mean_score": 0.0,
            "sd_score": 0.0,
            "median_score": 0.0,
            "max_score": 0.0,
            "beaten_percentile": 100.0,
            "diff_from_cutoff": 0.0,
            "diff_from_mean": 0.0,
        }

    seats = cutoff_info["seats"]
    admitted = cutoff_info["admitted_count"]
    vacancy = cutoff_info["vacancy_count"]
    cutoff = cutoff_info["cutoff_score"]
    mean_sc = cutoff_info["mean_score"]
    sd_sc = cutoff_info["sd_score"]
    max_sc = cutoff_info["max_score"]
    median_sc = cutoff_info["median_score"]

    higher_count = sum(1 for s in historical_scores if s > total_weighted_score)
    sim_rank = higher_count + 1
    beaten_pct = (
        100.0 * sum(1 for s in historical_scores if s <= total_weighted_score) / len(historical_scores)
    )

    if not is_eligible:
        return 0.0, {
            "status_note": "ჩაჭრილია (მინიმალური კომპეტენციის ზღვარი ვერ გადალახა) / Failed minimum competency threshold",
            "simulated_rank": None,
            "admitted_count": admitted,
            "seats": seats,
            "vacancy_count": vacancy,
            "cutoff_score": cutoff,
            "mean_score": mean_sc,
            "sd_score": sd_sc,
            "median_score": median_sc,
            "max_score": max_sc,
            "beaten_percentile": round(beaten_pct, 1),
            "diff_from_cutoff": round(total_weighted_score - cutoff, 1),
            "diff_from_mean": round(total_weighted_score - mean_sc, 1),
        }

    # Case 1: Program had unfilled seats (admitted < seats)
    if seats > 0 and admitted < seats:
        diff_from_cutoff = total_weighted_score - cutoff
        scale = max(sd_sc, 25.0)
        if diff_from_cutoff >= 0:
            prob = 92.0 + 7.5 * normal_cdf(diff_from_cutoff / scale)
        else:
            prob = 75.0 + 17.0 * normal_cdf(diff_from_cutoff / (1.5 * scale))
        prob = max(5.0, min(99.9, prob))
        note = (
            f"პროგრამაზე დარჩა თავისუფალი ადგილები ({admitted} ჩარიცხული / {seats} ადგილი) — "
            f"ზღვრის გადალახვის შემთხვევაში ჩარიცხვის შანსი ძალიან მაღალია."
        )
    else:
        # Case 2: Competitive program (all seats filled, admitted >= seats)
        sigma_cutoff = max(0.65 * sd_sc, 18.0)
        z_cut = (total_weighted_score - cutoff) / sigma_cutoff
        cdf_prob = 100.0 * normal_cdf(z_cut)

        if total_weighted_score >= cutoff:
            emp_boost = 50.0 + 0.495 * beaten_pct
            prob = 0.55 * cdf_prob + 0.45 * emp_boost
        else:
            prob = cdf_prob

        prob = max(0.1, min(99.9, prob))
        if total_weighted_score >= mean_sc:
            note = "საკონკურსო ქულა აღემატება ჩარიცხულთა საშუალო ქულას (მაღალი შანსი)."
        elif total_weighted_score >= cutoff:
            note = "საკონკურსო ქულა აღემატება მინიმალურ გამსვლელ ქულას (კონკურენტული ზონა)."
        else:
            note = "საკონკურსო ქულა ჩამორჩება გასული წლის გამსვლელ ქულას (რისკის ზონა)."

    return round(prob, 1), {
        "status_note": note,
        "simulated_rank": sim_rank,
        "admitted_count": admitted,
        "seats": seats,
        "vacancy_count": vacancy,
        "cutoff_score": cutoff,
        "mean_score": mean_sc,
        "sd_score": sd_sc,
        "median_score": median_sc,
        "max_score": max_sc,
        "beaten_percentile": round(beaten_pct, 1),
        "diff_from_cutoff": round(total_weighted_score - cutoff, 1),
        "diff_from_mean": round(total_weighted_score - mean_sc, 1),
    }


def evaluate_candidate(
    uni_query: str | None,
    prog_query: str,
    georgian_raw: float,
    foreign_raw: float,
    elective_subject_query: str | None,
    elective_raw: float,
    foreign_lang_query: str = "უცხოური ენა",
    elective2_subject_query: str | None = None,
    elective2_raw: float | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    """
    Core calculation engine:
    1. Resolves University and Program in admission_data.db.
    2. Extracts mandatory subjects (Georgian, Foreign Language) and valid general elective subjects
       officially defined in the handbook for that program.
    3. Pairs each entered raw score with that exact subject's coefficient, minimum threshold,
       mean (E), and standard deviation (SD) from admission_data.db.
    4. Computes Z-scores, official scaled scores, and total weighted competition score.
    5. Compares against historical cutoffs and candidate distributions for that exact elective track.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"Database file not found at '{db_path}'. Please run 'python build_database.py' first."
        )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    prog, inferred_elec_code = resolve_program(cur, uni_query, prog_query)
    pcode = prog["program_code"]

    # Fetch subject stats lookup
    stats_rows = cur.execute(
        """
        SELECT subject_key, subject_name, elective_code, max_score,
               min_competency_score, mean, sd, empirical_mean, empirical_sd
        FROM subject_stats
        """
    ).fetchall()
    subject_stats = {
        r[0]: {
            "subject_key": r[0],
            "subject_name": r[1],
            "elective_code": r[2],
            "max_score": r[3],
            "min_competency_score": r[4],
            "mean": r[5],
            "sd": r[6],
            "empirical_mean": r[7],
            "empirical_sd": r[8],
        }
        for r in stats_rows
    }

    # Fetch program subjects
    ps_rows = cur.execute(
        """
        SELECT subject_name, canonical_subject, is_mandatory, elective_code,
               coefficient, min_threshold_str, min_threshold_pct, min_raw_required,
               priority, seats
        FROM program_subjects
        WHERE program_code = ?
        ORDER BY id
        """,
        (pcode,),
    ).fetchall()

    prog_subjects = [
        {
            "subject_name": r[0],
            "canonical_subject": r[1],
            "is_mandatory": bool(r[2]),
            "elective_code": r[3],
            "coefficient": float(r[4]),
            "min_threshold_str": r[5],
            "min_threshold_pct": float(r[6]),
            "min_raw_required": int(r[7]),
            "priority": int(r[8]),
            "seats": int(r[9]),
        }
        for r in ps_rows
    ]

    # Identify mandatory Georgian, mandatory Foreign Language, and valid general Elective subjects
    georgian_req = next(
        (s for s in prog_subjects if s["canonical_subject"] == "ქართული ენა და ლიტერატურა"),
        None,
    )
    foreign_req = next(
        (s for s in prog_subjects if s["canonical_subject"] == "უცხოური ენა"),
        None,
    )
    valid_electives = get_valid_program_electives(prog_subjects)

    # Also check if there is a mandatory 3rd subject in a 4-subject program (e.g. Biology in Medicine)
    mandatory_third_reqs = [
        s
        for s in prog_subjects
        if s["is_mandatory"]
        and s["canonical_subject"] in VALID_ELECTIVE_SUBJECTS
        and s not in valid_electives
    ]

    # Resolve candidate's chosen elective subject strictly against valid_electives
    chosen_elec_req = None
    sq = (elective_subject_query or "").strip()

    # Allow 1-based menu index (e.g., "1", "2") when matching valid_electives
    if sq.isdigit() and 1 <= int(sq) <= len(valid_electives):
        chosen_elec_req = valid_electives[int(sq) - 1]
    else:
        canon_elective = resolve_elective_subject(sq)
        if not canon_elective and inferred_elec_code:
            for s in valid_electives:
                if s["elective_code"] == inferred_elec_code or inferred_elec_code.endswith(
                    s["elective_code"] or ""
                ):
                    canon_elective = s["canonical_subject"]
                    break

        if not canon_elective and len(valid_electives) == 1 and not sq:
            chosen_elec_req = valid_electives[0]
        elif canon_elective:
            chosen_elec_req = next(
                (s for s in valid_electives if s["canonical_subject"] == canon_elective),
                None,
            )

    if valid_electives and chosen_elec_req is None:
        avail = ", ".join(
            f"{idx}. {s['canonical_subject']} (კოდი {s['elective_code']}, კოეფ. x{s['coefficient']:g}, ადგილები: {s['seats']})"
            for idx, s in enumerate(valid_electives, start=1)
        )
        conn.close()
        raise ValueError(
            f"არჩევითი საგანი '{sq or 'უცნობი'}' არ ბარდება პროგრამაზე '{pcode} - {prog['program_name']}'. "
            f"ამ პროგრამის ოფიციალური არჩევითი საგნებია: {avail}"
        )

    # Build exact (requirement_row, raw_score, stats_key) list
    eval_items = []
    if georgian_req:
        eval_items.append((georgian_req, float(georgian_raw), "ქართული ენა და ლიტერატურა"))

    if foreign_req:
        # Determine if program requires a single specific foreign language or general foreign language
        fl_stat_key = "უცხოური ენა"
        if foreign_lang_query and foreign_lang_query.strip().lower() in FOREIGN_LANG_ALIASES:
            mapped_fl = FOREIGN_LANG_ALIASES[foreign_lang_query.strip().lower()]
            if mapped_fl in subject_stats:
                fl_stat_key = mapped_fl
        eval_items.append((foreign_req, float(foreign_raw), fl_stat_key))

    if mandatory_third_reqs and elective2_raw is not None:
        # 4-subject program where user provided both mandatory 3rd score (elective_raw) and 4th elective score (elective2_raw)
        mand_req = mandatory_third_reqs[0]
        eval_items.append((mand_req, float(elective_raw), mand_req["canonical_subject"]))
        if chosen_elec_req:
            eval_items.append(
                (chosen_elec_req, float(elective2_raw), chosen_elec_req["canonical_subject"])
            )
    elif chosen_elec_req:
        # Pair candidate's elective_raw directly with their selected elective subject's exact parameters
        if mandatory_third_reqs:
            # If 4-subject program but only 1 elective score was given, use mandatory 3rd subject at its min passing or same score
            mand_req = mandatory_third_reqs[0]
            eval_items.append((mand_req, float(elective_raw), mand_req["canonical_subject"]))
        eval_items.append(
            (chosen_elec_req, float(elective_raw), chosen_elec_req["canonical_subject"])
        )

    breakdown = []
    all_passed = True
    total_weighted = 0.0

    for req_item, raw_sc, stat_key in eval_items:
        # Always pull mean (E), SD, and max_score from the exact subject's statistics
        st = subject_stats.get(req_item["canonical_subject"]) or subject_stats.get(stat_key)
        max_sc = int(st["max_score"]) if st else 60
        mean_val = float(st["mean"]) if st else 30.0
        sd_val = float(st["sd"]) if st else 12.0
        state_min_comp = float(st["min_competency_score"]) if st else 15.0

        min_raw_req = int(req_item["min_raw_required"])
        passed = (raw_sc >= min_raw_req) and (0.0 <= raw_sc <= max_sc)
        if not passed:
            all_passed = False

        z_val, scaled_exact, scaled_rounded = calculate_scaled_score(
            raw_sc, mean_val, sd_val
        )
        coeff = float(req_item["coefficient"])
        weighted_sc = round(coeff * scaled_rounded, 2)
        total_weighted = round(total_weighted + weighted_sc, 2)

        breakdown.append(
            {
                "subject_name": req_item["subject_name"],
                "canonical_subject": req_item["canonical_subject"],
                "elective_code": req_item["elective_code"],
                "raw_score": raw_sc,
                "max_score": max_sc,
                "min_threshold_str": req_item["min_threshold_str"],
                "min_raw_required": min_raw_req,
                "state_min_competency": state_min_comp,
                "passed_threshold": passed,
                "mean_e": round(mean_val, 2),
                "sd": round(sd_val, 2),
                "z_score": round(z_val, 4),
                "scaled_score_exact": round(scaled_exact, 2),
                "scaled_score": scaled_rounded,
                "coefficient": coeff,
                "weighted_score": weighted_sc,
                "seats_for_subject": req_item["seats"],
            }
        )

    # Determine primary elective track code for historical comparison
    track_elec_code = chosen_elec_req["elective_code"] if chosen_elec_req else "ALL"
    track_elec_subj = (
        chosen_elec_req["canonical_subject"] if chosen_elec_req else "ყველა საგანი"
    )

    cutoff_row = cur.execute(
        """
        SELECT full_program_code, elective_code, elective_subject, seats,
               admitted_count, vacancy_count, cutoff_score, max_score,
               mean_score, sd_score, median_score, p10_score, p25_score, p75_score, p90_score
        FROM program_cutoffs
        WHERE base_program_code = ? AND (elective_code = ? OR elective_subject = ?)
        ORDER BY admitted_count DESC
        LIMIT 1
        """,
        (pcode, track_elec_code, track_elec_subj),
    ).fetchone()

    if not cutoff_row:
        cutoff_row = cur.execute(
            """
            SELECT full_program_code, elective_code, elective_subject, seats,
                   admitted_count, vacancy_count, cutoff_score, max_score,
                   mean_score, sd_score, median_score, p10_score, p25_score, p75_score, p90_score
            FROM program_cutoffs
            WHERE base_program_code = ? AND elective_code = 'ALL'
            LIMIT 1
            """,
            (pcode,),
        ).fetchone()

    cutoff_info = None
    historical_scores = []

    if cutoff_row:
        cutoff_info = {
            "full_program_code": cutoff_row[0],
            "elective_code": cutoff_row[1],
            "elective_subject": cutoff_row[2],
            "seats": chosen_elec_req["seats"] if chosen_elec_req else cutoff_row[3],
            "admitted_count": cutoff_row[4],
            "vacancy_count": cutoff_row[5],
            "cutoff_score": cutoff_row[6],
            "max_score": cutoff_row[7],
            "mean_score": cutoff_row[8],
            "sd_score": cutoff_row[9],
            "median_score": cutoff_row[10],
            "p10_score": cutoff_row[11],
            "p25_score": cutoff_row[12],
            "p75_score": cutoff_row[13],
            "p90_score": cutoff_row[14],
        }
        if cutoff_row[1] != "ALL":
            sc_rows = cur.execute(
                """
                SELECT competitive_score FROM ranked_candidates
                WHERE base_program_code = ? AND full_program_code = ? AND competitive_score IS NOT NULL
                ORDER BY competitive_score DESC
                """,
                (pcode, cutoff_row[0]),
            ).fetchall()
        else:
            sc_rows = cur.execute(
                """
                SELECT competitive_score FROM ranked_candidates
                WHERE base_program_code = ? AND competitive_score IS NOT NULL
                ORDER BY competitive_score DESC
                """,
                (pcode,),
            ).fetchall()
        historical_scores = [float(r[0]) for r in sc_rows]
    else:
        seats_fallback = (
            chosen_elec_req["seats"] if chosen_elec_req else prog["total_seats"]
        )
        cutoff_info = {
            "full_program_code": f"{pcode}{track_elec_code or ''}",
            "elective_code": track_elec_code or "",
            "elective_subject": track_elec_subj,
            "seats": seats_fallback,
            "admitted_count": 0,
            "vacancy_count": seats_fallback,
            "cutoff_score": 0.0,
            "max_score": 0.0,
            "mean_score": 0.0,
            "sd_score": 0.0,
            "median_score": 0.0,
            "p10_score": 0.0,
            "p25_score": 0.0,
            "p75_score": 0.0,
            "p90_score": 0.0,
        }

    prob_pct, comparison = estimate_admission_probability(
        all_passed, total_weighted, cutoff_info, historical_scores
    )

    conn.close()

    return {
        "university": {
            "uni_code": prog["uni_code"],
            "uni_name": prog["uni_name"],
        },
        "program": {
            "program_code": prog["program_code"],
            "full_track_code": cutoff_info["full_program_code"],
            "program_name": prog["program_name"],
            "selected_elective": track_elec_subj,
            "total_seats": prog["total_seats"],
            "track_seats": cutoff_info["seats"],
            "language": prog["language"],
            "tuition": prog["tuition"],
            "accreditation": prog["accreditation"],
        },
        "eligible": all_passed,
        "eligibility_status": (
            "ELIGIBLE (მინიმალური კომპეტენციის ზღვარი გადალახულია)"
            if all_passed
            else "INELIGIBLE (მინიმალური კომპეტენციის ზღვარი ვერ გადალახა)"
        ),
        "subjects_breakdown": breakdown,
        "total_weighted_score": total_weighted,
        "historical_comparison": comparison,
        "admission_probability_pct": prob_pct,
    }


def print_report(result: dict) -> None:
    """Formats and prints the admission probability report to stdout."""
    uni = result["university"]
    prog = result["program"]
    comp = result["historical_comparison"]

    print("=" * 84)
    print("  NAEC 2026 ADMISSION PROBABILITY CALCULATOR / ჩარიცხვის ალბათობის კალკულატორი")
    print("=" * 84)
    print(f"  უნივერსიტეტი (University) : [{uni['uni_code']}] {uni['uni_name']}")
    print(
        f"  პროგრამა (Program)        : [{prog['program_code']}] {prog['program_name']} (Track: {prog['full_track_code']} - {prog['selected_elective']})"
    )
    print(
        f"  ადგილები (Quota / Seats)  : {prog['track_seats']} ადგილი ამ საგნით (სულ პროგრამაზე: {prog['total_seats']}) | ენა: {prog['language'] or 'ქართული ენა'}"
    )
    print("-" * 84)
    print(f"  სტატუსი (Eligibility)     : {result['eligibility_status']}")
    print("-" * 84)
    print("  საგნების სკალირებული ქულები (SCALED SCORES BREAKDOWN):")
    print(
        f"  {'საგანი (Subject)':<28} | {'ნედლი (Raw)':<11} | {'ზღვარი (Min)':<14} | {'E / SD':<13} | {'Z-Score':<7} | {'სკალ.(Scaled)':<13} | {'კოეფ.':<5} | {'შეწონილი':<8}"
    )
    print("  " + "-" * 80)

    for b in result["subjects_breakdown"]:
        subj_short = b["canonical_subject"][:28]
        raw_str = f"{b['raw_score']:.0f}/{b['max_score']}"
        status_mark = "PASS" if b["passed_threshold"] else "FAIL"
        min_str = f">={b['min_raw_required']} ({status_mark})"
        esd_str = f"{b['mean_e']:.1f}/{b['sd']:.1f}"
        z_str = f"{b['z_score']:+.2f}"
        scl_str = f"{b['scaled_score']:.1f} ({b['scaled_score_exact']:.2f})"
        coeff_str = f"x{b['coefficient']:g}"
        w_str = f"{b['weighted_score']:.1f}"
        print(
            f"  {subj_short:<28} | {raw_str:<11} | {min_str:<14} | {esd_str:<13} | {z_str:<7} | {scl_str:<13} | {coeff_str:<5} | {w_str:<8}"
        )

    print("-" * 84)
    print(
        f"  ჯამური საკონკურსო (შეწონილი) ქულა / TOTAL WEIGHTED SCORE : {result['total_weighted_score']:.1f}"
    )
    print("-" * 84)
    print("  ისტორიული რანჟირებული სიის შედარება (HISTORICAL CUTOFF & RANKING COMPARISON):")
    if comp.get("admitted_count", 0) > 0:
        print(
            f"  - ჩარიცხულთა რაოდენობა (Admitted / Quota) : {comp['admitted_count']} ჩარიცხული / {comp['seats']} ადგილი (ვაკანტური: {comp['vacancy_count']})"
        )
        print(
            f"  - მინიმალური გამსვლელი ქულა (Cutoff Score): {comp['cutoff_score']:.1f} (თქვენი სხვაობა: {comp['diff_from_cutoff']:+.1f})"
        )
        print(
            f"  - საშუალო ქულა (Mean Admitted Score)      : {comp['mean_score']:.1f} ± {comp['sd_score']:.1f} (თქვენი სხვაობა: {comp['diff_from_mean']:+.1f})"
        )
        print(
            f"  - მედიანა / მაქსიმალური (Median / Max)    : {comp['median_score']:.1f} / {comp['max_score']:.1f}"
        )
        if comp.get("simulated_rank") is not None:
            print(
                f"  - პოზიცია ჩარიცხულთა შორის (Simulated Rank): #{comp['simulated_rank']} / {comp['admitted_count']} (უსწრებთ ჩარიცხულთა {comp['beaten_percentile']:.1f}%-ს)"
            )
    else:
        print("  - რანჟირებულ სიაში ამ პროგრამაზე ჩარიცხულები არ ფიქსირდება (თავისუფალი ადგილები).")

    print(f"  - შეფასება (Note): {comp['status_note']}")
    print("=" * 84)
    print(
        f"  ჩარიცხვის ალბათობა / ADMISSION PROBABILITY : {result['admission_probability_pct']:.1f}%"
    )
    print("=" * 84)


def list_matching_programs(uni_query: str | None, prog_query: str | None, db_path: str = DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    uni_matches = resolve_university(cur, uni_query) if uni_query else []
    uni_codes = [u[0] for u in uni_matches]

    sql = "SELECT program_code, program_name, uni_code, uni_name, total_seats FROM programs WHERE 1=1"
    params = []
    if uni_codes:
        sql += f" AND uni_code IN ({','.join('?' for _ in uni_codes)})"
        params.extend(uni_codes)
    if prog_query:
        pq = PROGRAM_SEARCH_ALIASES.get(prog_query.strip().lower(), prog_query.strip())
        sql += " AND (program_code LIKE ? OR program_name LIKE ?)"
        params.extend([f"%{pq}%", f"%{pq}%"])
    sql += " ORDER BY program_code LIMIT 50"

    rows = cur.execute(sql, params).fetchall()
    print(f"ნაპოვნია {len(rows)} პროგრამა (Showing up to 50):")
    for r in rows:
        ps = cur.execute(
            "SELECT canonical_subject, elective_code, coefficient, min_threshold_str, seats FROM program_subjects WHERE program_code = ?",
            (r[0],),
        ).fetchall()
        subj_str = ", ".join(
            f"{s[0]}[x{s[2]:g}, {s[3]}, seats={s[4]}]" for s in ps
        )
        print(f"  {r[0]} | {r[1]} | [{r[2]}] {r[3]} (სულ ადგილები: {r[4]})")
        print(f"          საგნები: {subj_str}")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Georgian National Unified Examinations (NAEC 2026) Admission Probability Calculator"
    )
    parser.add_argument(
        "-u",
        "--university",
        "--uni",
        type=str,
        default=None,
        help="University code (e.g. '001'), name, or alias (e.g. 'თსუ', 'TSU', 'ილიაუნი')",
    )
    parser.add_argument(
        "-p",
        "--program",
        "--prog",
        type=str,
        default=None,
        help="7-digit program code (e.g. '0010112') or program name (e.g. 'ინგლისური ფილოლოგია', 'ეკონომიკა')",
    )
    parser.add_argument(
        "-g",
        "--georgian",
        type=float,
        default=None,
        help="Raw score in Georgian Language & Literature (max 60)",
    )
    parser.add_argument(
        "-f",
        "--foreign",
        type=float,
        default=None,
        help="Raw score in Foreign Language (max 70)",
    )
    parser.add_argument(
        "--foreign-lang",
        type=str,
        default="უცხოური ენა",
        help="Foreign language name (default: 'უცხოური ენა')",
    )
    parser.add_argument(
        "-s",
        "--elective-subject",
        "--elective",
        type=str,
        default=None,
        help="3rd elective subject name, menu index (1..N), or NAEC code (4=Math, 5=History, 6=Geo, 7=Lit, 8=Physics, 9=Chem, 10=Bio, 12=Art, 14=Civics)",
    )
    parser.add_argument(
        "-e",
        "--elective-score",
        type=float,
        default=None,
        help="Raw score in 3rd elective subject",
    )
    parser.add_argument(
        "--elective2-subject",
        type=str,
        default=None,
        help="Optional 4th elective subject (for 4-subject programs)",
    )
    parser.add_argument(
        "--elective2-score",
        type=float,
        default=None,
        help="Optional raw score in 4th elective subject",
    )
    parser.add_argument(
        "--list-programs",
        action="store_true",
        help="List programs matching --university and/or --program",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    parser.add_argument(
        "positional",
        nargs="*",
        help="Optional positional args: [university] <program> <georgian_raw> <foreign_raw> [elective_subject] <elective_raw>",
    )

    args = parser.parse_args()

    if args.list_programs:
        list_matching_programs(args.university, args.program)
        return

    uni_q = args.university
    prog_q = args.program
    g_raw = args.georgian
    f_raw = args.foreign
    elec_subj = args.elective_subject
    elec_raw = args.elective_score

    # Allow combined "--elective-subject Math:42" syntax
    if elec_subj and ":" in elec_subj and elec_raw is None:
        parts = elec_subj.split(":", 1)
        elec_subj = parts[0].strip()
        try:
            elec_raw = float(parts[1].strip())
        except ValueError:
            pass

    # Parse positional arguments safely (never confuse a 7-digit program code with georgian_raw)
    pos = args.positional
    if pos:
        if len(pos) == 4:
            prog_q = prog_q or pos[0]
            g_raw = g_raw if g_raw is not None else float(pos[1])
            f_raw = f_raw if f_raw is not None else float(pos[2])
            if ":" in pos[3]:
                p_s, p_r = pos[3].split(":", 1)
                elec_subj = elec_subj or p_s
                elec_raw = elec_raw if elec_raw is not None else float(p_r)
            else:
                elec_raw = elec_raw if elec_raw is not None else float(pos[3])
        elif len(pos) == 5:
            is_pos1_prog_code = len(pos[1].strip()) >= 7 and pos[1].strip().isdigit()
            is_pos1_score = False
            if not is_pos1_prog_code:
                try:
                    val1 = float(pos[1])
                    if 0 <= val1 <= 100:
                        is_pos1_score = True
                except ValueError:
                    pass

            if is_pos1_score:
                # <prog> <g_raw> <f_raw> <e_subj> <e_raw>
                prog_q = prog_q or pos[0]
                g_raw = g_raw if g_raw is not None else float(pos[1])
                f_raw = f_raw if f_raw is not None else float(pos[2])
                elec_subj = elec_subj or pos[3]
                elec_raw = elec_raw if elec_raw is not None else float(pos[4])
            else:
                # <uni> <prog> <g_raw> <f_raw> <e_raw>
                uni_q = uni_q or pos[0]
                prog_q = prog_q or pos[1]
                g_raw = g_raw if g_raw is not None else float(pos[2])
                f_raw = f_raw if f_raw is not None else float(pos[3])
                if ":" in pos[4]:
                    p_s, p_r = pos[4].split(":", 1)
                    elec_subj = elec_subj or p_s
                    elec_raw = elec_raw if elec_raw is not None else float(p_r)
                else:
                    elec_raw = elec_raw if elec_raw is not None else float(pos[4])
        elif len(pos) >= 6:
            uni_q = uni_q or pos[0]
            prog_q = prog_q or pos[1]
            g_raw = g_raw if g_raw is not None else float(pos[2])
            f_raw = f_raw if f_raw is not None else float(pos[3])
            elec_subj = elec_subj or pos[4]
            elec_raw = elec_raw if elec_raw is not None else float(pos[5])

    # Interactive fallback if required arguments are still missing
    if not prog_q:
        from interactive import run_interactive_session
        run_interactive_session()
        return

    if g_raw is None or f_raw is None or elec_raw is None:
        parser.error(
            "Please provide raw scores for Georgian (-g), Foreign Language (-f), and 3rd Elective Subject (-e)."
        )

    try:
        res = evaluate_candidate(
            uni_query=uni_q,
            prog_query=prog_q,
            georgian_raw=g_raw,
            foreign_raw=f_raw,
            elective_subject_query=elec_subj,
            elective_raw=elec_raw,
            foreign_lang_query=args.foreign_lang,
            elective2_subject_query=args.elective2_subject,
            elective2_raw=args.elective2_score,
        )
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print_report(res)
    except Exception as exc:
        print(f"შეცდომა / Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
