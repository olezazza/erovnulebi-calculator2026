#!/usr/bin/env python3
"""
build_database.py

Streams and parses the 4 official NAEC 2026 admission data files:
1. 'ცნობარი_2026_15.pdf' (1,093 programs, universities, seats, required subjects, coefficients, minimum thresholds)
2. 'რანჟირებული-სია-2026 - Sheet1.pdf' (34,150 admitted candidate rows, matched via 7-digit base program code + 8th/9th digit elective code)
3. 'შეფასებისა და გამოცდების ეროვნული ცენტრი.html' (subject mean E, standard deviation SD, max score, and minimum competency thresholds)
4. '- სკალირებული ქულის გამოანგარიშება (4).pdf' (official scaling formula Z = (X - E) / SD, Scaled = 15*Z + 150)

Stores all extracted and verified data into 'admission_data.db'.
"""

import os
import re
import sys
import math
import time
import sqlite3
import numpy as np
from bs4 import BeautifulSoup
import pymupdf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

pymupdf.TOOLS.mupdf_display_errors(False)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CNOBARI_PDF = os.path.join(BASE_DIR, "ცნობარი_2026_15.pdf")
RANKED_PDF = os.path.join(BASE_DIR, "რანჟირებული-სია-2026 - Sheet1.pdf")
HTML_STATS_FILE = os.path.join(BASE_DIR, "შეფასებისა და გამოცდების ეროვნული ცენტრი.html")
SCALING_PDF_CANDIDATES = [
    os.path.join(BASE_DIR, "- სკალირებული ქულის გამოანგარიშება (4).pdf"),
    os.path.join(BASE_DIR, "სკალირებული ქულის გამოანგარიშება (4).pdf"),
]
DB_PATH = os.path.join(BASE_DIR, "admission_data.db")

# Mapping of 8th/9th digits (elective suffixes) to canonical elective subject names
ELECTIVE_CODE_TO_SUBJECT = {
    "4": "მათემატიკა",
    "5": "ისტორია",
    "6": "გეოგრაფია",
    "7": "ლიტერატურა",
    "8": "ფიზიკა",
    "9": "ქიმია",
    "10": "ბიოლოგია",
    "11": "შემოქმედებითი ტური",
    "12": "ხელოვნება",
    "14": "სამოქალაქო განათლება",
    # 4-subject suffixes where 3rd subject is mandatory (10=Bio or 11=Creative Tour) and last digit(s) are the 4th elective
    "104": "მათემატიკა",
    "108": "ფიზიკა",
    "109": "ქიმია",
    "111": "ხელოვნება",
    "114": "მათემატიკა",
    "115": "ისტორია",
    "117": "ლიტერატურა",
}

SUBJECT_TO_ELECTIVE_CODE = {
    "მათემატიკა": "4",
    "ისტორია": "5",
    "გეოგრაფია": "6",
    "ლიტერატურა": "7",
    "ფიზიკა": "8",
    "ქიმია": "9",
    "ბიოლოგია": "10",
    "შემოქმედებითი ტური": "11",
    "ხელოვნება": "12",
    "სახვითი და გამოყენებითი ხელოვნება": "12",
    "სამოქალაქო განათლება": "14",
}

KNOWN_SUBJECTS = {
    "აფხაზური ენა",
    "ბიოლოგია",
    "გეოგრაფია",
    "ზოგადი უნარები (აზერ)",
    "ზოგადი უნარები (სომხ)",
    "ისტორია",
    "ლიტერატურა",
    "მათემატიკა",
    "ოსური ენა",
    "სამოქალაქო განათლება",
    "უცხოური ენა (გერ.)",
    "უცხოური ენა (გერ.; ინგ.; რუს.)",
    "უცხოური ენა (გერ.; ინგ.; რუს.; ფრან.)",
    "უცხოური ენა (გერ.; ინგ.; ფრან.)",
    "უცხოური ენა (ინგ.)",
    "უცხოური ენა (ინგ.; გერ.; ფრან.)",
    "უცხოური ენა (ინგ.; რუს.)",
    "უცხოური ენა (ინგ.; რუს.; გერ.; ფრან.)",
    "უცხოური ენა (რუს.)",
    "ფიზიკა",
    "ქართული ენა და ლიტერატურა",
    "ქიმია",
    "შემოქმედებითი ტური",
    "ხელოვნება",
    "სასპორტო პროფესიული კონკურსი",
}


def normalize_subject_name(raw_name: str) -> str:
    """Maps subject names from Cnobari, HTML, and Ranked List to a canonical key."""
    s = raw_name.strip()
    if s.startswith("უცხოური ენა"):
        return "უცხოური ენა"
    if s in ("ხელოვნება", "სახვითი და გამოყენებითი ხელოვნება"):
        return "ხელოვნება"
    if s in ("ზოგადი უნარები (სომხ)", "ზოგადი უნარები (სომხურ ენაზე)"):
        return "ზოგადი უნარები (სომხურ ენაზე)"
    if s in ("ზოგადი უნარები (აზერ)", "ზოგადი უნარები (აზერბაიჯანულ ენაზე)"):
        return "ზოგადი უნარები (აზერბაიჯანულ ენაზე)"
    if s == "ქართული":
        return "ქართული ენა და ლიტერატურა"
    return s


def decode_gid(gid: int) -> str:
    """Decodes custom BPGArial glyph IDs used in ცნობარი_2026_15.pdf."""
    if 0x031D <= gid <= 0x033D:
        return chr(gid + 0x0DB3)
    elif 0x0004 <= gid < 0x007F:
        return chr(gid + 0x1C)
    return chr(gid)


def decode_cnobari_text(raw_text: str) -> str:
    """Decodes mixed Type3 + BPGArial text extracted from ცნობარი_2026_15.pdf."""
    out = []
    prev_type = None
    for ch in raw_text:
        c = ord(ch)
        if 0x031D <= c <= 0x033D:
            curr_type = "bpg_geo"
            dec_ch = chr(c + 0x0DB3)
        elif c < 0x20 and c not in (0x0A, 0x0D):
            if 0x14 <= c <= 0x1D:
                curr_type = "bpg_digit"
            else:
                curr_type = "bpg_sym"
            dec_ch = chr(c + 0x1C)
        elif 0x10D0 <= c <= 0x10FA:
            curr_type = "std_geo"
            dec_ch = ch
        else:
            curr_type = "other"
            dec_ch = ch
        if prev_type in ("std_geo", "bpg_digit") and curr_type == "bpg_geo":
            out.append("\n")
        out.append(dec_ch)
        prev_type = curr_type
    return "".join(out)


def extract_mcid_cells(page) -> list[str]:
    """Extracts all table cell text blocks in exact stream order from a Cnobari PDF page."""
    s = page.read_contents().decode("latin1", errors="ignore")
    cells = []
    for m in re.finditer(r"NonStruct\s*<<\s*/MCID\s*\d+\s*>>\s*BDC(.*?)EMC", s, re.DOTALL):
        hs = re.findall(r"<([0-9A-Fa-f]{4,})>\s*Tj", m.group(1))
        if hs:
            txt = "".join(
                decode_gid(int(h[i : i + 4], 16))
                for h in hs
                for i in range(0, len(h), 4)
            ).strip()
            txt = txt.replace("\x01", "").strip()
            if txt:
                cells.append(txt)
    return cells


def parse_scaling_pdf() -> dict:
    """Verifies the official scaling formula from '- სკალირებული ქულის გამოანგარიშება (4).pdf'."""
    pdf_path = None
    for cand in SCALING_PDF_CANDIDATES:
        if os.path.exists(cand):
            pdf_path = cand
            break
    info = {
        "formula_z": "Z = (X - E) / SD",
        "formula_scaled": "Scaled = 15 * Z + 150",
        "scale_mean": 150.0,
        "scale_sd": 15.0,
        "verified_from_pdf": False,
    }
    if pdf_path:
        doc = pymupdf.open(pdf_path)
        full_text = "\n".join(page.get_text("text") for page in doc)
        if "150" in full_text and "15" in full_text:
            info["verified_from_pdf"] = True
        doc.close()
    return info


def parse_html_stats(html_path: str) -> tuple[dict, list]:
    """
    Parses 'შეფასებისა და გამოცდების ეროვნული ცენტრი.html' to extract:
    - subject_stats dict keyed by canonical subject name
    - variant_rows list of per-variant statistics
    """
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    subject_stats = {}
    variant_rows = []

    for sec in soup.find_all("div", class_="section level3"):
        h3 = sec.find("h3")
        if not h3:
            continue
        raw_subj_name = h3.get_text(strip=True)
        subj_key = normalize_subject_name(raw_subj_name)

        h4 = sec.find("h4")
        max_score_m = re.search(r"(\d+)", h4.get_text()) if h4 else None
        max_score = int(max_score_m.group(1)) if max_score_m else 60

        sec_text = sec.get_text(" ", strip=True)
        thresh_m = re.search(r"მეტია\s+([\d.]+)\s*-ზე", sec_text)
        min_comp = float(thresh_m.group(1)) if thresh_m else 0.0

        tables = sec.find_all("table")
        if not tables:
            continue
        var_table = tables[0]
        hist_tables = tables[1:]

        variants = []
        for row in var_table.find_all("tr")[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cols) >= 7:
                v_name = cols[0]
                count = int(re.search(r"\d+", cols[1]).group(0))
                m_pass = re.search(r"\d+", cols[2])
                passed = int(m_pass.group(0)) if m_pass else 0
                mean = float(re.search(r"[\d.]+", cols[3]).group(0))
                m_diff = re.search(r"[\d.]+", cols[4])
                diff = float(m_diff.group(0)) if m_diff else 0.0
                m_max = re.search(r"[\d.]+", cols[5])
                max_obs = float(m_max.group(0)) if m_max else 0.0
                m_ps = re.search(r"[\d.]+", cols[6])
                pass_score = float(m_ps.group(0)) if m_ps else 0.0
                variants.append(
                    {
                        "variant": v_name,
                        "count": count,
                        "passed": passed,
                        "mean": mean,
                        "difficulty": diff,
                        "max_observed": max_obs,
                        "pass_score": pass_score,
                    }
                )

        all_mid = []
        all_freq = []
        for v_idx, ht in enumerate(hist_tables):
            bins = []
            for row in ht.find_all("tr")[1:]:
                cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cols) >= 2:
                    m_int = re.match(r"\((\d+);(\d+)\]", cols[0])
                    if m_int:
                        lo, hi = float(m_int.group(1)), float(m_int.group(2))
                        freq = int(cols[1])
                        bins.append((lo, hi, freq))
                        all_mid.append((lo + hi) / 2.0)
                        all_freq.append(freq)
            if bins and v_idx < len(variants):
                mids = np.array([(b[0] + b[1]) / 2.0 for b in bins])
                freqs = np.array([b[2] for b in bins])
                tot_f = np.sum(freqs)
                if tot_f > 0:
                    vm = float(np.sum(mids * freqs) / tot_f)
                    vsd = float(np.sqrt(np.sum(freqs * (mids - vm) ** 2) / tot_f))
                else:
                    vsd = 10.0
                variants[v_idx]["sd"] = vsd

        for v in variants:
            variant_rows.append(
                (
                    subj_key,
                    raw_subj_name,
                    v["variant"],
                    v["count"],
                    v["passed"],
                    v["mean"],
                    v.get("sd", 0.0),
                    v["pass_score"],
                )
            )

        total_n = sum(v["count"] for v in variants)
        weighted_mean = (
            sum(v["count"] * v["mean"] for v in variants) / total_n if total_n else 0.0
        )

        all_mid_arr = np.array(all_mid)
        all_freq_arr = np.array(all_freq)
        if np.sum(all_freq_arr) > 0:
            hist_mean = float(np.sum(all_mid_arr * all_freq_arr) / np.sum(all_freq_arr))
            hist_sd = float(
                np.sqrt(
                    np.sum(all_freq_arr * (all_mid_arr - hist_mean) ** 2)
                    / np.sum(all_freq_arr)
                )
            )
        else:
            hist_mean = weighted_mean
            hist_sd = 10.0

        elective_code = SUBJECT_TO_ELECTIVE_CODE.get(subj_key)
        subject_stats[subj_key] = {
            "subject_key": subj_key,
            "subject_name": raw_subj_name,
            "elective_code": elective_code,
            "max_score": max_score,
            "min_competency_score": min_comp,
            "mean": weighted_mean,
            "sd": hist_sd,
            "hist_mean": hist_mean,
            "empirical_mean": weighted_mean,
            "empirical_sd": hist_sd,
            "total_candidates": total_n,
        }

    # Create combined 'უცხოური ენა' entry across English, Russian, German, French
    foreign_langs = ["ინგლისური ენა", "რუსული ენა", "გერმანული ენა", "ფრანგული ენა"]
    present_fl = [subject_stats[k] for k in foreign_langs if k in subject_stats]
    if present_fl:
        tot_fl_n = sum(d["total_candidates"] for d in present_fl)
        comb_mean = sum(d["mean"] * d["total_candidates"] for d in present_fl) / tot_fl_n
        # Pooled variance: E[Var(X|L)] + Var(E[X|L])
        within_var = (
            sum((d["sd"] ** 2) * d["total_candidates"] for d in present_fl) / tot_fl_n
        )
        between_var = (
            sum(((d["mean"] - comb_mean) ** 2) * d["total_candidates"] for d in present_fl)
            / tot_fl_n
        )
        comb_sd = math.sqrt(within_var + between_var)
        subject_stats["უცხოური ენა"] = {
            "subject_key": "უცხოური ენა",
            "subject_name": "უცხოური ენა (ინგ.; რუს.; გერ.; ფრან.)",
            "elective_code": None,
            "max_score": present_fl[0]["max_score"],
            "min_competency_score": present_fl[0]["min_competency_score"],
            "mean": comb_mean,
            "sd": comb_sd,
            "hist_mean": comb_mean,
            "empirical_mean": comb_mean,
            "empirical_sd": comb_sd,
            "total_candidates": tot_fl_n,
        }

    # Also ensure 'შემოქმედებითი ტური' and 'აფხაზური ენა' have fallback metadata if needed
    if "შემოქმედებითი ტური" not in subject_stats:
        subject_stats["შემოქმედებითი ტური"] = {
            "subject_key": "შემოქმედებითი ტური",
            "subject_name": "შემოქმედებითი ტური",
            "elective_code": "11",
            "max_score": 100,
            "min_competency_score": 25.0,
            "mean": 65.0,
            "sd": 15.0,
            "hist_mean": 65.0,
            "empirical_mean": 65.0,
            "empirical_sd": 15.0,
            "total_candidates": 0,
        }

    return subject_stats, variant_rows


def parse_cnobari(pdf_path: str, subject_stats: dict) -> tuple[dict, list, list]:
    """
    Streams and parses 'ცნობარი_2026_15.pdf':
    Returns:
      - universities: dict[uni_code -> full_uni_name]
      - programs: list of dicts
      - program_subjects: list of dicts
    """
    doc = pymupdf.open(pdf_path)
    prog_header_re = re.compile(r"^(\d{7})[ \t]+([^\r\n]+)", re.MULTILINE)

    universities = {}
    programs = []
    program_subjects = []

    # First pass / single pass over all pages: capture university cover pages AND program pages
    for p_idx in range(len(doc)):
        page = doc[p_idx]
        raw_txt = page.get_text("text")
        dec_txt = decode_cnobari_text(raw_txt)
        cells = extract_mcid_cells(page)

        # Check if this is a university header/cover page
        if "მისამართი:" in cells or "ვებგვერდი:" in cells:
            for c in cells[:4]:
                m_uni = re.match(r"^(\d{3})\s+(.+)$", c)
                if m_uni:
                    u_code = m_uni.group(1)
                    u_name = m_uni.group(2).rstrip("ΰ").strip()
                    universities[u_code] = u_name
                    break

        m = prog_header_re.search(dec_txt)
        if not m or not (
            "აკრედიტაცია" in dec_txt
            or "სწავლების ენა" in dec_txt
            or "გამოცდა" in dec_txt
        ):
            continue

        prog_code = m.group(1)
        prog_name = m.group(2).strip()
        uni_code = prog_code[:3]

        # Find university cell in cells (from bottom up)
        uni_name_cell = None
        uni_idx = len(cells)
        for idx in range(len(cells) - 1, -1, -1):
            if cells[idx].startswith(uni_code):
                uni_name_cell = (
                    cells[idx][len(uni_code) :].lstrip(" -").rstrip("ΰ").strip()
                )
                uni_idx = idx
                break

        if uni_code not in universities and uni_name_cell:
            universities[uni_code] = uni_name_cell

        # Find index of first exam subject
        first_subj_idx = None
        for idx, c in enumerate(cells[:uni_idx]):
            if (
                c in KNOWN_SUBJECTS
                or c.startswith("უცხოური ენა")
                or c.startswith("ზოგადი უნარები")
            ):
                first_subj_idx = idx
                break

        total_seats = 0
        accreditation = ""
        language = ""
        tuition = ""

        if first_subj_idx is not None and first_subj_idx > 0:
            prev_cell = cells[first_subj_idx - 1]
            if prev_cell.isdigit():
                total_seats = int(prev_cell)
            # Extract metadata from cells[0 : first_subj_idx - 1]
            meta_cells = cells[: first_subj_idx - 1]
            if len(meta_cells) >= 2:
                tuition = meta_cells[-1]
                language = meta_cells[-2]
            for mc in meta_cells:
                if "აკრედიტ" in mc:
                    accreditation = mc
                    break

        # Parse exam subjects
        raw_exams = []
        if first_subj_idx is not None:
            idx = first_subj_idx
            while idx < uni_idx:
                subj = cells[idx]
                idx += 1
                attrs = []
                while idx < uni_idx and not (
                    cells[idx] in KNOWN_SUBJECTS
                    or cells[idx].startswith("უცხოური ენა")
                    or cells[idx].startswith("ზოგადი უნარები")
                ):
                    attrs.append(cells[idx])
                    idx += 1

                coeff = None
                min_thresh_str = None
                priority = None
                sub_seats = None

                nums = []
                for a in attrs:
                    if "%" in a:
                        min_thresh_str = a
                    elif a.replace(".", "").isdigit():
                        nums.append(float(a) if "." in a else int(a))

                if len(nums) == 1:
                    priority = int(nums[0])
                elif len(nums) == 2:
                    coeff, priority = float(nums[0]), int(nums[1])
                elif len(nums) >= 3:
                    coeff, priority, sub_seats = (
                        float(nums[0]),
                        int(nums[1]),
                        int(nums[2]),
                    )

                raw_exams.append((subj, coeff, min_thresh_str, priority, sub_seats))

        programs.append(
            {
                "program_code": prog_code,
                "program_name": prog_name,
                "uni_code": uni_code,
                "uni_name": universities.get(uni_code, uni_name_cell or ""),
                "total_seats": total_seats,
                "accreditation": accreditation,
                "language": language,
                "tuition": tuition,
                "page_number": p_idx + 1,
            }
        )

        # Determine mandatory vs elective subjects for this program
        for subj, coeff, min_thresh_str, priority, sub_seats in raw_exams:
            canon_subj = normalize_subject_name(subj)
            elec_code = SUBJECT_TO_ELECTIVE_CODE.get(canon_subj)
            is_mandatory = 1 if (sub_seats is None) else 0
            effective_seats = sub_seats if sub_seats is not None else total_seats

            # Parse minimum threshold percentage and compute minimum raw score required
            # Note: In NAEC rules, "25%+1" or "X%-ზე მეტი" means raw score must be strictly > (pct/100)*max_score,
            # i.e. floor(max_score * pct / 100.0) + 1.
            pct_val = 0.0
            plus_one = 1
            if min_thresh_str:
                m_pct = re.search(r"([\d.]+)\s*%", min_thresh_str)
                if m_pct:
                    pct_val = float(m_pct.group(1))
                if "+1" in min_thresh_str:
                    plus_one = 1

            stat_entry = subject_stats.get(canon_subj)
            max_sc = stat_entry["max_score"] if stat_entry else 60
            state_min_comp = stat_entry["min_competency_score"] if stat_entry else 0.0

            if pct_val > 0:
                prog_min_raw = math.floor((pct_val / 100.0) * max_sc + 1e-9) + 1
            else:
                prog_min_raw = math.floor(state_min_comp + 1e-9) + 1

            state_min_raw_int = math.floor(state_min_comp + 1e-9) + 1
            min_raw_required = max(prog_min_raw, state_min_raw_int)

            program_subjects.append(
                {
                    "program_code": prog_code,
                    "subject_name": subj,
                    "canonical_subject": canon_subj,
                    "is_mandatory": is_mandatory,
                    "elective_code": elec_code,
                    "coefficient": coeff if coeff is not None else 0.0,
                    "min_threshold_str": min_thresh_str or "",
                    "min_threshold_pct": pct_val,
                    "min_raw_required": min_raw_required,
                    "priority": priority if priority is not None else 1,
                    "seats": effective_seats,
                }
            )

    # Backfill full university names in programs
    for p in programs:
        if p["uni_code"] in universities:
            p["uni_name"] = universities[p["uni_code"]]

    doc.close()
    return universities, programs, program_subjects


def parse_ranked_list(pdf_path: str) -> tuple[list[tuple], dict]:
    """
    Streams and parses all 2,847 pages (949 vertical strips x 3 horizontal strips)
    of 'რანჟირებული-სია-2026 - Sheet1.pdf'.
    Returns:
      - candidate_rows: list of tuples for SQLite insertion
      - empirical_fits: dict[subject_key -> (e_fit, sd_fit)] from actual (raw, scaled) pairs
    """
    doc = pymupdf.open(pdf_path)
    n_pages = len(doc)
    stride = n_pages // 3  # 949

    candidate_rows = []
    raw_scaled_pairs = {}

    for i in range(stride):
        w_left = doc[i].get_text("words")
        w_mid = doc[i + stride].get_text("words")
        w_right = doc[i + 2 * stride].get_text("words")

        y_min = 115.0 if i == 0 else 45.0
        y_base = 127.5 if i == 0 else 58.5

        rows_l = {}
        for w in w_left:
            if w[1] < y_min:
                continue
            rk = round((w[1] - y_base) / 18.75)
            rows_l.setdefault(rk, []).append(w)

        rows_m = {}
        for w in w_mid:
            if w[1] < y_min:
                continue
            rk = round((w[1] - y_base) / 18.75)
            rows_m.setdefault(rk, []).append(w)

        rows_r = {}
        for w in w_right:
            if w[1] < y_min:
                continue
            rk = round((w[1] - y_base) / 18.75)
            rows_r.setdefault(rk, []).append(w)

        for rk in sorted(rows_l.keys()):
            wl = sorted(rows_l[rk], key=lambda x: x[0])
            wm = sorted(rows_m.get(rk, []), key=lambda x: x[0])
            wr = sorted(rows_r.get(rk, []), key=lambda x: x[0])

            # 1. Strip 1 (Left): uni_code, full_program_code, exam_id, georgian_raw, georgian_scaled, foreign_lang
            pcode = None
            for w in wl:
                if w[0] < 190:
                    m = re.search(r"(\d{7,11})", w[4])
                    if m:
                        pcode = m.group(1)
                        break
            if not pcode:
                continue

            base_pcode = pcode[:7]
            uni_code = pcode[:3]
            suffix = pcode[7:]

            exam_id = ""
            for w in wl:
                if 255 <= w[0] < 335:
                    m_id = re.search(r"(\d{9})$", w[4])
                    if m_id:
                        exam_id = m_id.group(1)
                        break

            g_raw = None
            g_scl = None
            f_lang = ""
            for w in wl:
                if 335 <= w[0] < 415:
                    try:
                        g_raw = float(w[4])
                    except ValueError:
                        pass
                elif 415 <= w[0] < 470:
                    try:
                        g_scl = float(w[4])
                    except ValueError:
                        pass
                elif w[0] >= 470:
                    f_lang = (f_lang + " " + w[4]).strip()

            # 2. Strip 2 (Middle): foreign_raw, foreign_scaled, elective1_name, elective1_raw, elective1_scaled, elective2_name, elective2_raw
            f_raw = None
            f_scl = None
            e1_name = ""
            e1_raw = None
            e1_scl = None
            e2_name = ""
            e2_raw = None

            for w in wm:
                if 50 <= w[0] < 110:
                    try:
                        f_raw = float(w[4])
                    except ValueError:
                        pass
                elif 110 <= w[0] < 160:
                    try:
                        f_scl = float(w[4])
                    except ValueError:
                        pass
                elif 160 <= w[0] < 245:
                    e1_name = (e1_name + " " + w[4]).strip()
                elif 245 <= w[0] < 315:
                    try:
                        e1_raw = float(w[4])
                    except ValueError:
                        pass
                elif 315 <= w[0] < 370:
                    try:
                        e1_scl = float(w[4])
                    except ValueError:
                        pass
                elif 370 <= w[0] < 445:
                    e2_name = (e2_name + " " + w[4]).strip()
                elif w[0] >= 445:
                    try:
                        e2_raw = float(w[4])
                    except ValueError:
                        pass

            # 3. Strip 3 (Right): elective2_scaled, competitive_score, choice_rank, program_type
            e2_scl = None
            comp_score = None
            choice_rank = None
            prog_type = ""

            for w in wr:
                if w[0] < 120:
                    try:
                        e2_scl = float(w[4])
                    except ValueError:
                        pass
                elif 120 <= w[0] < 200:
                    try:
                        comp_score = float(w[4])
                    except ValueError:
                        pass
                elif 200 <= w[0] < 305:
                    try:
                        choice_rank = int(w[4])
                    except ValueError:
                        pass
                elif w[0] >= 305:
                    prog_type = (prog_type + " " + w[4]).strip()

            # Map elective suffix to canonical elective subject & code
            elec_subj = ELECTIVE_CODE_TO_SUBJECT.get(suffix, "")
            if not elec_subj and e1_name:
                elec_subj = normalize_subject_name(e1_name)
            elec_code = SUBJECT_TO_ELECTIVE_CODE.get(elec_subj, suffix)

            # Record empirical (raw, scaled) pairs for single-variant subjects
            if g_raw is not None and g_scl is not None:
                raw_scaled_pairs.setdefault("ქართული ენა და ლიტერატურა", []).append(
                    (g_raw, g_scl)
                )
            if f_raw is not None and f_scl is not None:
                raw_scaled_pairs.setdefault("უცხოური ენა", []).append((f_raw, f_scl))
            if e1_name and e1_raw is not None and e1_scl is not None:
                canon_e1 = normalize_subject_name(e1_name)
                raw_scaled_pairs.setdefault(canon_e1, []).append((e1_raw, e1_scl))
            if e2_name and e2_raw is not None and e2_scl is not None:
                canon_e2 = normalize_subject_name(e2_name)
                raw_scaled_pairs.setdefault(canon_e2, []).append((e2_raw, e2_scl))

            candidate_rows.append(
                (
                    uni_code,
                    pcode,
                    base_pcode,
                    suffix,
                    elec_code,
                    elec_subj,
                    exam_id,
                    g_raw,
                    g_scl,
                    f_lang,
                    f_raw,
                    f_scl,
                    e1_name,
                    e1_raw,
                    e1_scl,
                    e2_name,
                    e2_raw,
                    e2_scl,
                    comp_score,
                    choice_rank,
                    prog_type,
                )
            )

    doc.close()

    # Fit linear regression Scaled = 15*(X - E)/SD + 150 on empirical pairs
    empirical_fits = {}
    for subj_key, plist in raw_scaled_pairs.items():
        if len(plist) >= 5:
            arr = np.array(plist, dtype=float)
            x = arr[:, 0]
            y = arr[:, 1]
            if np.std(x) > 1e-6:
                m, b = np.polyfit(x, y, 1)
                if m > 1e-6:
                    sd_fit = float(15.0 / m)
                    e_fit = float((150.0 - b) / m)
                    empirical_fits[subj_key] = (e_fit, sd_fit)

    return candidate_rows, empirical_fits


def build_database():
    t_start = time.time()
    print("1. Verifying official scaling formula from PDF...")
    scaling_info = parse_scaling_pdf()
    print(
        f"   Official Scaling: {scaling_info['formula_z']} | {scaling_info['formula_scaled']} (Verified={scaling_info['verified_from_pdf']})"
    )

    print("2. Parsing subject statistics from HTML ('შეფასებისა და გამოცდების ეროვნული ცენტრი.html')...")
    subject_stats, variant_rows = parse_html_stats(HTML_STATS_FILE)
    print(f"   Extracted {len(subject_stats)} subject entries and {len(variant_rows)} exam variants.")

    print("3. Streaming and parsing 'ცნობარი_2026_15.pdf'...")
    t_cnob = time.time()
    universities, programs, program_subjects = parse_cnobari(CNOBARI_PDF, subject_stats)
    print(
        f"   Extracted {len(universities)} universities, {len(programs)} programs, and {len(program_subjects)} program-subject requirements in {time.time() - t_cnob:.2f}s."
    )

    print("4. Streaming and parsing 'რანჟირებული-სია-2026 - Sheet1.pdf'...")
    t_rank = time.time()
    candidate_rows, empirical_fits = parse_ranked_list(RANKED_PDF)
    print(
        f"   Extracted {len(candidate_rows)} candidate admission rows in {time.time() - t_rank:.2f}s."
    )

    # Update empirical_mean and empirical_sd in subject_stats where available
    for subj_key, (e_fit, sd_fit) in empirical_fits.items():
        if subj_key in subject_stats:
            subject_stats[subj_key]["empirical_mean"] = e_fit
            subject_stats[subj_key]["empirical_sd"] = sd_fit

    print(f"5. Writing SQLite database to '{DB_PATH}'...")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE subject_stats (
            subject_key TEXT PRIMARY KEY,
            subject_name TEXT,
            elective_code TEXT,
            max_score INTEGER,
            min_competency_score REAL,
            mean REAL,
            sd REAL,
            hist_mean REAL,
            empirical_mean REAL,
            empirical_sd REAL,
            total_candidates INTEGER
        );

        CREATE TABLE subject_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_key TEXT,
            subject_name TEXT,
            variant_name TEXT,
            candidate_count INTEGER,
            passed_count INTEGER,
            mean REAL,
            sd REAL,
            pass_score REAL
        );

        CREATE TABLE universities (
            uni_code TEXT PRIMARY KEY,
            uni_name TEXT
        );

        CREATE TABLE programs (
            program_code TEXT PRIMARY KEY,
            program_name TEXT,
            uni_code TEXT,
            uni_name TEXT,
            total_seats INTEGER,
            accreditation TEXT,
            language TEXT,
            tuition TEXT,
            page_number INTEGER
        );

        CREATE TABLE program_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_code TEXT,
            subject_name TEXT,
            canonical_subject TEXT,
            is_mandatory INTEGER,
            elective_code TEXT,
            coefficient REAL,
            min_threshold_str TEXT,
            min_threshold_pct REAL,
            min_raw_required INTEGER,
            priority INTEGER,
            seats INTEGER
        );

        CREATE TABLE ranked_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uni_code TEXT,
            full_program_code TEXT,
            base_program_code TEXT,
            elective_suffix TEXT,
            elective_code TEXT,
            elective_subject TEXT,
            exam_id TEXT,
            georgian_raw REAL,
            georgian_scaled REAL,
            foreign_lang TEXT,
            foreign_raw REAL,
            foreign_scaled REAL,
            elective1_name TEXT,
            elective1_raw REAL,
            elective1_scaled REAL,
            elective2_name TEXT,
            elective2_raw REAL,
            elective2_scaled REAL,
            competitive_score REAL,
            choice_rank INTEGER,
            program_type TEXT
        );

        CREATE TABLE program_cutoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_program_code TEXT,
            full_program_code TEXT,
            elective_code TEXT,
            elective_subject TEXT,
            seats INTEGER,
            admitted_count INTEGER,
            vacancy_count INTEGER,
            cutoff_score REAL,
            max_score REAL,
            mean_score REAL,
            sd_score REAL,
            median_score REAL,
            p10_score REAL,
            p25_score REAL,
            p75_score REAL,
            p90_score REAL
        );
        """
    )

    # Insert metadata
    for k, v in scaling_info.items():
        cur.execute("INSERT INTO metadata VALUES (?, ?)", (k, str(v)))

    # Insert subject_stats
    for s in subject_stats.values():
        cur.execute(
            """
            INSERT INTO subject_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s["subject_key"],
                s["subject_name"],
                s["elective_code"],
                s["max_score"],
                s["min_competency_score"],
                s["mean"],
                s["sd"],
                s["hist_mean"],
                s["empirical_mean"],
                s["empirical_sd"],
                s["total_candidates"],
            ),
        )

    # Insert subject_variants
    cur.executemany(
        """
        INSERT INTO subject_variants (
            subject_key, subject_name, variant_name, candidate_count, passed_count, mean, sd, pass_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        variant_rows,
    )

    # Insert universities
    cur.executemany(
        "INSERT INTO universities VALUES (?, ?)",
        sorted(universities.items()),
    )

    # Insert programs
    cur.executemany(
        """
        INSERT INTO programs VALUES (
            :program_code, :program_name, :uni_code, :uni_name, :total_seats,
            :accreditation, :language, :tuition, :page_number
        )
        """,
        programs,
    )

    # Insert program_subjects
    cur.executemany(
        """
        INSERT INTO program_subjects (
            program_code, subject_name, canonical_subject, is_mandatory,
            elective_code, coefficient, min_threshold_str, min_threshold_pct,
            min_raw_required, priority, seats
        ) VALUES (
            :program_code, :subject_name, :canonical_subject, :is_mandatory,
            :elective_code, :coefficient, :min_threshold_str, :min_threshold_pct,
            :min_raw_required, :priority, :seats
        )
        """,
        program_subjects,
    )

    # Insert ranked_candidates
    cur.executemany(
        """
        INSERT INTO ranked_candidates (
            uni_code, full_program_code, base_program_code, elective_suffix,
            elective_code, elective_subject, exam_id, georgian_raw, georgian_scaled,
            foreign_lang, foreign_raw, foreign_scaled, elective1_name, elective1_raw,
            elective1_scaled, elective2_name, elective2_raw, elective2_scaled,
            competitive_score, choice_rank, program_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        candidate_rows,
    )

    # Build lookup of seats per (program_code, elective_code) and per program_code
    prog_seats_map = {p["program_code"]: p["total_seats"] for p in programs}
    subj_seats_map = {}
    for ps in program_subjects:
        if ps["elective_code"]:
            subj_seats_map[(ps["program_code"], ps["elective_code"])] = ps["seats"]
            subj_seats_map[(ps["program_code"], ps["canonical_subject"])] = ps["seats"]

    # Compute program_cutoffs distributions per (base_program_code, elective_code, elective_subject) and overall ('ALL')
    by_track = {}
    by_prog_all = {}
    for row in candidate_rows:
        base_pcode = row[2]
        full_pcode = row[1]
        elec_code = row[4]
        elec_subj = row[5]
        comp_score = row[18]
        if comp_score is None:
            continue
        by_track.setdefault((base_pcode, full_pcode, elec_code, elec_subj), []).append(
            comp_score
        )
        by_prog_all.setdefault(base_pcode, []).append(comp_score)

    cutoff_rows = []
    for (base_pcode, full_pcode, elec_code, elec_subj), scores in sorted(
        by_track.items()
    ):
        arr = np.array(scores, dtype=float)
        seats = subj_seats_map.get(
            (base_pcode, elec_code),
            subj_seats_map.get(
                (base_pcode, elec_subj), prog_seats_map.get(base_pcode, 0)
            ),
        )
        admitted = len(arr)
        vacancy = max(0, seats - admitted) if seats else 0
        cutoff_rows.append(
            (
                base_pcode,
                full_pcode,
                elec_code,
                elec_subj,
                seats,
                admitted,
                vacancy,
                float(np.min(arr)),
                float(np.max(arr)),
                float(np.mean(arr)),
                float(np.std(arr)) if len(arr) > 1 else 0.0,
                float(np.median(arr)),
                float(np.percentile(arr, 10)),
                float(np.percentile(arr, 25)),
                float(np.percentile(arr, 75)),
                float(np.percentile(arr, 90)),
            )
        )

    for base_pcode, scores in sorted(by_prog_all.items()):
        arr = np.array(scores, dtype=float)
        seats = prog_seats_map.get(base_pcode, 0)
        admitted = len(arr)
        vacancy = max(0, seats - admitted) if seats else 0
        cutoff_rows.append(
            (
                base_pcode,
                base_pcode,
                "ALL",
                "ყველა საგანი",
                seats,
                admitted,
                vacancy,
                float(np.min(arr)),
                float(np.max(arr)),
                float(np.mean(arr)),
                float(np.std(arr)) if len(arr) > 1 else 0.0,
                float(np.median(arr)),
                float(np.percentile(arr, 10)),
                float(np.percentile(arr, 25)),
                float(np.percentile(arr, 75)),
                float(np.percentile(arr, 90)),
            )
        )

    cur.executemany(
        """
        INSERT INTO program_cutoffs (
            base_program_code, full_program_code, elective_code, elective_subject,
            seats, admitted_count, vacancy_count, cutoff_score, max_score,
            mean_score, sd_score, median_score, p10_score, p25_score, p75_score, p90_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        cutoff_rows,
    )

    # Create indexes for fast querying in calculate_probability.py
    cur.executescript(
        """
        CREATE INDEX idx_programs_uni ON programs(uni_code);
        CREATE INDEX idx_prog_subj_code ON program_subjects(program_code);
        CREATE INDEX idx_candidates_base ON ranked_candidates(base_program_code);
        CREATE INDEX idx_candidates_track ON ranked_candidates(base_program_code, elective_code);
        CREATE INDEX idx_cutoffs_base ON program_cutoffs(base_program_code);
        """
    )

    conn.commit()
    conn.close()
    print(f"Done! Database built and verified in {time.time() - t_start:.2f}s.")


if __name__ == "__main__":
    build_database()
