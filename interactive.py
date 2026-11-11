#!/usr/bin/env python3
"""
interactive.py

Interactive step-by-step terminal menu for the NAEC 2026 Admission Predictor using admission_data.db.
1. Prompts for University name or code (supports 'list', smart substring/alias search, numbered selection).
2. Prompts for Program name or code within the chosen university (supports 'list', smart search, numbered selection).
3. Automatically detects required subjects, coefficients, thresholds, and valid general elective options from admission_data.db.
4. Prompts step-by-step for raw scores (Georgian, Foreign Language, numbered Elective selection, Elective score).
5. Runs evaluation, prints the formatted report (eligibility, scaled scores, total weighted score, historical comparison, and admission probability %), and asks to calculate another.
"""

import os
import sys
import sqlite3

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

from calculate_probability import (
    DEFAULT_DB_PATH,
    PROGRAM_SEARCH_ALIASES,
    UNI_ALIASES,
    VALID_ELECTIVE_SUBJECTS,
    evaluate_candidate,
    print_report,
    resolve_elective_subject,
)


def smart_search_universities(cur: sqlite3.Cursor, query: str) -> list[tuple[str, str, int]]:
    """
    Searches universities by code, alias, or smart substring/token match.
    Returns list of (uni_code, uni_name, program_count).
    """
    all_rows = cur.execute(
        """
        SELECT u.uni_code, u.uni_name, COUNT(p.program_code) as prog_count
        FROM universities u
        LEFT JOIN programs p ON u.uni_code = p.uni_code
        GROUP BY u.uni_code, u.uni_name
        ORDER BY u.uni_code
        """
    ).fetchall()

    q = query.strip()
    if not q or q.lower() == "list":
        return all_rows

    q_low = q.lower()

    # 1. Exact alias match
    if q_low in UNI_ALIASES:
        target_code = UNI_ALIASES[q_low]
        matches = [r for r in all_rows if r[0] == target_code]
        if matches:
            return matches

    # 2. Numeric code match (e.g. '1' or '001')
    if q.isdigit():
        padded = q.zfill(3)
        exact_code = [r for r in all_rows if r[0] == padded]
        if exact_code:
            return exact_code
        sub_code = [r for r in all_rows if q in r[0]]
        if sub_code:
            return sub_code

    # 3. Substring match on university name or code
    sub_matches = [
        r for r in all_rows if q_low in r[1].lower() or q_low in r[0].lower()
    ]
    if sub_matches:
        return sub_matches

    # 4. Token / stemmed-token match
    tokens = [t for t in q_low.split() if t]
    if tokens:
        tok_matches = [
            r for r in all_rows if all(tok in r[1].lower() for tok in tokens)
        ]
        if tok_matches:
            return tok_matches
        stems = [t[:5] for t in tokens if len(t) >= 3]
        if stems:
            stem_matches = [
                r for r in all_rows if all(st in r[1].lower() for st in stems)
            ]
            if stem_matches:
                return stem_matches

    # 5. Alias substring fallback
    alias_codes = {
        code for alias, code in UNI_ALIASES.items() if q_low in alias or alias in q_low
    }
    if alias_codes:
        return [r for r in all_rows if r[0] in alias_codes]

    return []


def select_university(cur: sqlite3.Cursor) -> tuple[str, str]:
    """Step 1: Interactive prompt to search and select a University."""
    while True:
        query = input(
            "\nEnter University name or code (or 'list' to see options): "
        ).strip()
        if not query:
            continue

        if query.lower() in ("q", "quit", "exit"):
            print("Exiting calculator. Goodbye!")
            sys.exit(0)

        matches = smart_search_universities(cur, query)
        if not matches:
            print(
                f"  [!] No universities found matching '{query}'. Try again or type 'list'."
            )
            continue

        if len(matches) == 1 and query.lower() != "list":
            u_code, u_name, p_cnt = matches[0]
            print(f"  -> Selected University: [{u_code}] {u_name} ({p_cnt} programs)")
            return u_code, u_name

        print(f"\n  Matching Universities ({len(matches)}):")
        for idx, (u_code, u_name, p_cnt) in enumerate(matches, start=1):
            print(f"    {idx:3d}. [{u_code}] {u_name} ({p_cnt} programs)")

        while True:
            choice = input(
                f"  Select university number (1-{len(matches)}) or type a new search: "
            ).strip()
            if not choice:
                continue
            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(matches):
                    u_code, u_name, p_cnt = matches[num - 1]
                    print(
                        f"  -> Selected University: [{u_code}] {u_name} ({p_cnt} programs)"
                    )
                    return u_code, u_name
                # Also check if they typed the 3-digit university code directly
                by_code = [m for m in matches if m[0] == choice.zfill(3)]
                if len(by_code) == 1:
                    u_code, u_name, p_cnt = by_code[0]
                    print(
                        f"  -> Selected University: [{u_code}] {u_name} ({p_cnt} programs)"
                    )
                    return u_code, u_name
                print(f"  [!] Please enter a valid number between 1 and {len(matches)}.")
            else:
                # Treat as a new search query
                sub_matches = smart_search_universities(cur, choice)
                if len(sub_matches) == 1:
                    u_code, u_name, p_cnt = sub_matches[0]
                    print(
                        f"  -> Selected University: [{u_code}] {u_name} ({p_cnt} programs)"
                    )
                    return u_code, u_name
                elif sub_matches:
                    matches = sub_matches
                    print(f"\n  Matching Universities ({len(matches)}):")
                    for idx, (u_code, u_name, p_cnt) in enumerate(matches, start=1):
                        print(f"    {idx:3d}. [{u_code}] {u_name} ({p_cnt} programs)")
                else:
                    print(f"  [!] No universities found matching '{choice}'.")


def smart_search_programs(
    all_progs: list[tuple[str, str, int]], query: str
) -> list[tuple[str, str, int]]:
    """
    Searches programs of the selected university by code, English/Latin alias, substring, or stemmed tokens.
    """
    q = query.strip()
    if not q or q.lower() == "list":
        return all_progs

    q_low = q.lower()

    # Translate English/Latin program search terms into Georgian equivalents if applicable
    if q_low in PROGRAM_SEARCH_ALIASES:
        q_low = PROGRAM_SEARCH_ALIASES[q_low].lower()
    else:
        translated_tokens = []
        changed = False
        for tok in q_low.split():
            if tok in PROGRAM_SEARCH_ALIASES:
                translated_tokens.append(PROGRAM_SEARCH_ALIASES[tok].lower())
                changed = True
            else:
                translated_tokens.append(tok)
        if changed:
            q_low = " ".join(translated_tokens)

    # Exact code match
    exact_code = [p for p in all_progs if p[0] == q or p[0] == q[:7]]
    if exact_code:
        return exact_code

    # Substring match on code or name (put exact name match first)
    sub = [p for p in all_progs if q_low in p[0].lower() or q_low in p[1].lower()]
    if sub:
        sub.sort(key=lambda p: (0 if p[1].lower() == q_low else 1, p[0]))
        return sub

    # Token match
    tokens = [t for t in q_low.split() if t]
    if tokens:
        tok_m = [p for p in all_progs if all(tok in p[1].lower() for tok in tokens)]
        if tok_m:
            return tok_m
        stems = [t[:5] for t in tokens if len(t) >= 2]
        if stems:
            stem_m = [p for p in all_progs if all(st in p[1].lower() for st in stems)]
            if stem_m:
                return stem_m

    return []


def select_program(cur: sqlite3.Cursor, uni_code: str, uni_name: str) -> tuple[str, str, int]:
    """Step 2: Interactive prompt to search and select a Program within the selected university."""
    all_progs = cur.execute(
        """
        SELECT program_code, program_name, total_seats
        FROM programs
        WHERE uni_code = ?
        ORDER BY program_code
        """,
        (uni_code,),
    ).fetchall()

    if len(all_progs) <= 15:
        print(f"\n  Available Programs at [{uni_code}] {uni_name}:")
        for idx, (p_code, p_name, seats) in enumerate(all_progs, start=1):
            print(f"    {idx:2d}. [{p_code}] {p_name} (Seats: {seats})")

    while True:
        query = input(
            "\nEnter Program name or code (or 'list' to see programs): "
        ).strip()
        if not query:
            continue

        if query.lower() in ("q", "quit", "exit"):
            print("Exiting calculator. Goodbye!")
            sys.exit(0)

        # Allow direct selection by list index if programs were already displayed
        if query.isdigit() and len(all_progs) <= 15:
            num = int(query)
            if 1 <= num <= len(all_progs):
                p_code, p_name, seats = all_progs[num - 1]
                print(f"  -> Selected Program: [{p_code}] {p_name} (Total Seats: {seats})")
                return p_code, p_name, seats

        matches = smart_search_programs(all_progs, query)
        if not matches:
            print(
                f"  [!] No programs found matching '{query}'. Try again or type 'list'."
            )
            continue

        if len(matches) == 1 and query.lower() != "list":
            p_code, p_name, seats = matches[0]
            print(f"  -> Selected Program: [{p_code}] {p_name} (Total Seats: {seats})")
            return p_code, p_name, seats

        print(f"\n  Matching Programs ({len(matches)}):")
        for idx, (p_code, p_name, seats) in enumerate(matches, start=1):
            print(f"    {idx:3d}. [{p_code}] {p_name} (Seats: {seats})")

        while True:
            choice = input(
                f"  Select program number (1-{len(matches)}) or type a new search: "
            ).strip()
            if not choice:
                continue
            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(matches):
                    p_code, p_name, seats = matches[num - 1]
                    print(
                        f"  -> Selected Program: [{p_code}] {p_name} (Total Seats: {seats})"
                    )
                    return p_code, p_name, seats
                # Check if user entered the 7-digit program code directly
                by_code = [m for m in matches if m[0] == choice[:7]]
                if len(by_code) == 1:
                    p_code, p_name, seats = by_code[0]
                    print(
                        f"  -> Selected Program: [{p_code}] {p_name} (Total Seats: {seats})"
                    )
                    return p_code, p_name, seats
                print(f"  [!] Please enter a valid number between 1 and {len(matches)}.")
            else:
                sub_matches = smart_search_programs(all_progs, choice)
                if len(sub_matches) == 1:
                    p_code, p_name, seats = sub_matches[0]
                    print(
                        f"  -> Selected Program: [{p_code}] {p_name} (Total Seats: {seats})"
                    )
                    return p_code, p_name, seats
                elif sub_matches:
                    matches = sub_matches
                    print(f"\n  Matching Programs ({len(matches)}):")
                    for idx, (p_code, p_name, seats) in enumerate(matches, start=1):
                        print(f"    {idx:3d}. [{p_code}] {p_name} (Seats: {seats})")
                else:
                    print(f"  [!] No programs found matching '{choice}'.")


def prompt_float_score(prompt_text: str, max_score: int = 100) -> float:
    """Prompts for and validates a numeric exam raw score."""
    while True:
        val_str = input(prompt_text).strip()
        if val_str.lower() in ("q", "quit", "exit"):
            print("Exiting calculator. Goodbye!")
            sys.exit(0)
        try:
            val = float(val_str)
            if 0 <= val <= max_score:
                return val
            print(f"  [!] Score must be between 0 and {max_score}. Please try again.")
        except ValueError:
            print("  [!] Invalid number. Please enter a numeric raw score.")


def get_program_requirements(cur: sqlite3.Cursor, program_code: str) -> dict:
    """
    Step 3: Queries program_subjects and subject_stats for the chosen program
    to automatically detect mandatory subjects and valid general 3rd/4th elective options
    officially defined in the handbook for that program.
    """
    rows = cur.execute(
        """
        SELECT ps.subject_name, ps.canonical_subject, ps.is_mandatory, ps.elective_code,
               ps.coefficient, ps.min_threshold_str, ps.min_raw_required, ps.seats,
               COALESCE(ss.max_score, 60) as max_score,
               COALESCE(ss.mean, 30.0) as mean_score,
               COALESCE(ss.sd, 10.0) as sd_score
        FROM program_subjects ps
        LEFT JOIN subject_stats ss ON ps.canonical_subject = ss.subject_key
        WHERE ps.program_code = ?
        ORDER BY ps.id
        """,
        (program_code,),
    ).fetchall()

    reqs = [
        {
            "subject_name": r[0],
            "canonical_subject": r[1],
            "is_mandatory": bool(r[2]),
            "elective_code": r[3],
            "coefficient": r[4],
            "min_threshold_str": r[5],
            "min_raw_required": r[6],
            "seats": r[7],
            "max_score": r[8],
            "mean_score": r[9],
            "sd_score": r[10],
        }
        for r in rows
    ]

    georgian_req = next(
        (r for r in reqs if r["canonical_subject"] == "ქართული ენა და ლიტერატურა"),
        None,
    )
    foreign_req = next(
        (r for r in reqs if r["canonical_subject"] == "უცხოური ენა"),
        None,
    )

    # Filter strictly to valid general NAEC elective subjects defined in the handbook for this program
    other_reqs = []
    seen_canonical = set()
    for r in reqs:
        canon = r["canonical_subject"]
        if canon in VALID_ELECTIVE_SUBJECTS and canon not in seen_canonical:
            seen_canonical.add(canon)
            other_reqs.append(r)

    return {
        "all": reqs,
        "georgian": georgian_req,
        "foreign": foreign_req,
        "others": other_reqs,
    }


def select_from_elective_menu(options: list[dict], prompt_label: str = "Select elective subject number: ") -> dict:
    """
    Prompts the user to select an elective subject from the numbered list of valid program electives.
    Strictly pairs the 1-based menu number (or exact subject name) with that exact elective entry.
    """
    while True:
        sel = input(prompt_label).strip()
        if sel.lower() in ("q", "quit", "exit"):
            print("Exiting calculator. Goodbye!")
            sys.exit(0)
        if not sel and len(options) == 1:
            return options[0]
        if sel.isdigit():
            idx = int(sel)
            if 1 <= idx <= len(options):
                return options[idx - 1]
            print(
                f"  [!] Please enter a valid option number between 1 and {len(options)}."
            )
            continue
        resolved = resolve_elective_subject(sel)
        if resolved:
            matched = next(
                (r for r in options if r["canonical_subject"] == resolved),
                None,
            )
            if matched:
                return matched
            valid_names = ", ".join(r["canonical_subject"] for r in options)
            print(
                f"  [!] '{resolved}' is not an eligible elective for this program. Valid options: {valid_names}."
            )
            continue
        print(
            f"  [!] Please enter a valid number between 1 and {len(options)} (or subject name)."
        )


def run_interactive_session(db_path: str = DEFAULT_DB_PATH) -> None:
    if not os.path.exists(db_path):
        print(
            f"Error: Database '{db_path}' not found. Please run 'python build_database.py' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    print("=" * 84)
    print("  WELCOME TO THE NAEC 2026 ADMISSION PROBABILITY CALCULATOR")
    print("  ერთიანი ეროვნული გამოცდების ჩარიცხვის ალბათობის ინტერაქტიული კალკულატორი")
    print("=" * 84)

    try:
        while True:
            # 1. Select University
            uni_code, uni_name = select_university(cur)

            # 2. Select Program
            prog_code, prog_name, total_seats = select_program(cur, uni_code, uni_name)

            # 3. Automatically detect required subjects and valid general elective options
            reqs = get_program_requirements(cur, prog_code)
            georgian_req = reqs["georgian"]
            foreign_req = reqs["foreign"]
            other_reqs = reqs["others"]

            print("\n  ----------------------------------------------------------------------------")
            print(f"  Program Requirements for [{prog_code}] {prog_name}:")
            if georgian_req:
                print(
                    f"    - {georgian_req['subject_name']} (Mandatory) | Coeff: x{georgian_req['coefficient']:g} | "
                    f"Min Threshold: >={georgian_req['min_raw_required']}/{georgian_req['max_score']} ({georgian_req['min_threshold_str']}) | "
                    f"E={georgian_req['mean_score']:.2f}, SD={georgian_req['sd_score']:.2f} | Seats: {georgian_req['seats']}"
                )
            if foreign_req:
                print(
                    f"    - {foreign_req['subject_name']} (Mandatory) | Coeff: x{foreign_req['coefficient']:g} | "
                    f"Min Threshold: >={foreign_req['min_raw_required']}/{foreign_req['max_score']} ({foreign_req['min_threshold_str']}) | "
                    f"E={foreign_req['mean_score']:.2f}, SD={foreign_req['sd_score']:.2f} | Seats: {foreign_req['seats']}"
                )
            for r in other_reqs:
                kind = "Mandatory 3rd Subject" if r["is_mandatory"] else "Elective"
                print(
                    f"    - {r['canonical_subject']} ({kind}) | Coeff: x{r['coefficient']:g} | "
                    f"Min Threshold: >={r['min_raw_required']}/{r['max_score']} ({r['min_threshold_str']}) | "
                    f"E={r['mean_score']:.2f}, SD={r['sd_score']:.2f} | Seats: {r['seats']}"
                )
            print("  ----------------------------------------------------------------------------\n")

            # 4. Prompt step-by-step for raw scores
            g_max = georgian_req["max_score"] if georgian_req else 60
            g_min = georgian_req["min_raw_required"] if georgian_req else 16
            print(f"  [Georgian Language: min threshold >={g_min}, max score {g_max}]")
            g_raw = prompt_float_score(
                "Enter Georgian Language raw score: ",
                max_score=g_max,
            )

            f_max = foreign_req["max_score"] if foreign_req else 70
            f_min = foreign_req["min_raw_required"] if foreign_req else 15
            print(f"  [Foreign Language: min threshold >={f_min}, max score {f_max}]")
            f_raw = prompt_float_score(
                "Enter Foreign Language raw score: ",
                max_score=f_max,
            )

            # Check if 4-subject program (mandatory 3rd + elective 4th) or standard 3-subject program
            mandatory_others = [r for r in other_reqs if r["is_mandatory"]]
            elective_others = [r for r in other_reqs if not r["is_mandatory"]]

            elec_subj_name = None
            elec_raw = 0.0
            elec2_subj_name = None
            elec2_raw = None

            if len(other_reqs) > 1 and mandatory_others and elective_others:
                # 4-subject program (e.g. Medicine where Biology is mandatory 3rd subject and Chemistry/Physics/Math is 4th elective)
                mand_3 = mandatory_others[0]
                print(
                    f"\n  Mandatory 3rd Subject: {mand_3['canonical_subject']} "
                    f"(Coeff: x{mand_3['coefficient']:g}, Min >={mand_3['min_raw_required']}/{mand_3['max_score']}, "
                    f"E={mand_3['mean_score']:.2f}, SD={mand_3['sd_score']:.2f})"
                )
                elec_raw = prompt_float_score(
                    f"Enter {mand_3['canonical_subject']} raw score (min >={mand_3['min_raw_required']}, max {mand_3['max_score']}): ",
                    max_score=mand_3["max_score"],
                )
                elec_subj_name = mand_3["canonical_subject"]

                print("\n  Available 4th Elective Subjects:")
                for idx, r in enumerate(elective_others, start=1):
                    print(
                        f"    {idx}. {r['canonical_subject']} (Coeff: x{r['coefficient']:g}, "
                        f"Min >={r['min_raw_required']}/{r['max_score']}, "
                        f"E={r['mean_score']:.2f}, SD={r['sd_score']:.2f}, Seats: {r['seats']})"
                    )
                chosen_e2 = select_from_elective_menu(
                    elective_others, "Select elective subject number: "
                )
                elec2_subj_name = chosen_e2["canonical_subject"]
                print(
                    f"  -> Selected Elective Subject: {elec2_subj_name} "
                    f"(Coeff: x{chosen_e2['coefficient']:g}, min threshold >={chosen_e2['min_raw_required']}, "
                    f"max score {chosen_e2['max_score']}, E={chosen_e2['mean_score']:.2f}, SD={chosen_e2['sd_score']:.2f})"
                )
                elec2_raw = prompt_float_score(
                    "Enter elective subject raw score: ",
                    max_score=chosen_e2["max_score"],
                )

            elif other_reqs:
                # Standard 3rd subject list (1 or more options)
                print("\n  Available 3rd Elective Subjects for this program:")
                for idx, r in enumerate(other_reqs, start=1):
                    print(
                        f"    {idx}. {r['canonical_subject']} (Coeff: x{r['coefficient']:g}, "
                        f"Min >={r['min_raw_required']}/{r['max_score']}, "
                        f"E={r['mean_score']:.2f}, SD={r['sd_score']:.2f}, Seats: {r['seats']})"
                    )

                chosen_elec = select_from_elective_menu(
                    other_reqs, "Select elective subject number: "
                )
                elec_subj_name = chosen_elec["canonical_subject"]
                print(
                    f"  -> Selected Elective Subject: {elec_subj_name} "
                    f"(Coeff: x{chosen_elec['coefficient']:g}, min threshold >={chosen_elec['min_raw_required']}, "
                    f"max score {chosen_elec['max_score']}, E={chosen_elec['mean_score']:.2f}, SD={chosen_elec['sd_score']:.2f})"
                )
                elec_raw = prompt_float_score(
                    "Enter elective subject raw score: ",
                    max_score=chosen_elec["max_score"],
                )

            # 5. Run evaluation logic and print formatted report
            print()
            result = evaluate_candidate(
                uni_query=uni_code,
                prog_query=prog_code,
                georgian_raw=g_raw,
                foreign_raw=f_raw,
                elective_subject_query=elec_subj_name,
                elective_raw=elec_raw,
                elective2_subject_query=elec2_subj_name,
                elective2_raw=elec2_raw,
                db_path=db_path,
            )
            print_report(result)

            # Ask to calculate another
            again = input("\nWould you like to calculate another? (y/n): ").strip().lower()
            if not again.startswith("y"):
                print("\nThank you for using the NAEC 2026 Admission Predictor! Goodbye!")
                break
    except (KeyboardInterrupt, EOFError):
        print("\nExiting calculator. Goodbye!")
    finally:
        conn.close()


if __name__ == "__main__":
    run_interactive_session()
