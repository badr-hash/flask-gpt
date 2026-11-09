"""Compare frozen/current prompts and Groq models on synthetic reference cases.

Usage: python evals/run_quality.py [--limit 12] [--repeats 1] [--resume]
This makes paid/quota-consuming API requests. It never reads user conversations.
"""

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from openai import AuthenticationError, OpenAI, RateLimitError

from answer_quality import PROMPT_VERSION, application_date
from chat_service import build_context
from evals.baseline import baseline_context
from evals.scoring import check_answer
from web_answers import web_answer


def summarize(results):
    summary = []
    for variant in dict.fromkeys(row["variant"] for row in results):
        rows = [row for row in results if row["variant"] == variant]
        dimensions = {}
        for dimension in ("accuracy", "relevance", "clarity", "completeness"):
            checks = [c for row in rows for c in row["checks"] if c["dimension"] == dimension]
            dimensions[dimension] = round(100 * sum(c["passed"] for c in checks) / len(checks), 1) if checks else None
        summary.append({
            "variant": variant, "model": rows[0]["model"], "cases": len(rows),
            "criteria_percent": round(100 * statistics.mean(row["score"] for row in rows), 1),
            "all_checks_passed": sum(row["score"] == 1 for row in rows),
            "errors": sum(bool(row["error"]) for row in rows),
            "median_seconds": round(statistics.median(row["seconds"] for row in rows), 2),
            "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
            "completion_tokens": sum(row["completion_tokens"] for row in rows),
            "dimensions": dimensions,
        })
    return summary


def write_report(path, run, cases):
    run["summary"] = summarize(run["results"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    lines = ["# Évaluation de la qualité des réponses", "", f"Date UTC : {run['started_at']}",
             f"Instructions candidates : `{run['prompt_version']}`", "",
             "Ce rapport mesure des critères explicites sur un petit jeu de cas synthétiques.",
             "Les pourcentages ne constituent pas un taux général d'exactitude ni une note humaine de qualité.",
             "Les contrôles de longueur et de format ne suffisent pas à juger la clarté ; relire les réponses ci-dessous.", "",
             "Le prompt initial est comparé au nouveau prompt sur les mêmes cas et paramètres :",
             "température 0,2 et plafond de 4 096 tokens, sans juge IA.",
             "Les variantes `baseline` et `quality` n'ont pas de recherche Web. Les variantes `web` utilisent browser_search obligatoire, raisonnement low, et uniquement la question actuelle.",
             "Le plafond est identique pour isoler les instructions. Une réponse vide, tronquée ou en erreur échoue.", "",
             "| Variante | Critères satisfaits | Cas entièrement réussis | Erreurs | Latence médiane | Tokens entrée / sortie |",
             "|---|---:|---:|---:|---:|---:|"]
    for item in run["summary"]:
        lines.append(f"| {item['variant']} | {item['criteria_percent']} % | {item['all_checks_passed']}/{item['cases']} | {item['errors']} | {item['median_seconds']} s | {item['prompt_tokens']} / {item['completion_tokens']} |")
    lines.extend(["", "Les tokens indiquent l'usage mesuré. Aucun coût en dollars n'est déduit : les tarifs, quotas et le palier du compte sont distincts.",
                  "Un seul passage peut être sensible à la variabilité ; utiliser `--repeats 3` pour une comparaison plus stable.", "",
                  "## Indicateurs par dimension", "", "| Variante | Exactitude | Pertinence | Clarté (indicateurs) | Complétude |",
                  "|---|---:|---:|---:|---:|"])
    for item in run["summary"]:
        d = item["dimensions"]
        lines.append("| " + item["variant"] + " | " + " | ".join(f"{d[k]} %" for k in ("accuracy", "relevance", "clarity", "completeness")) + " |")
    lines.extend(["", "## Réponses et revue manuelle", "",
                  "Pour chaque réponse, vérifier : faits corrects, réponse à la demande, langage adapté au niveau, points nécessaires présents et références soutenant réellement les affirmations.",
                  "Les contrôles automatiques vérifient des repères et des faits attendus ; ils ne prouvent pas que chaque affirmation est exacte ou chaque citation bien placée.", ""])
    case_map = {case["id"]: case for case in cases}
    for row in run["results"]:
        case = case_map[row["case_id"]]
        lines.extend([f"### {row['variant']} / {row['case_id']} / passage {row['repeat']}", "",
                      "**Demande :** " + case["question"], "", "**Référence :** " + case["reference"], "",
                      f"**Critères :** {round(row['score'] * 100, 1)} % ; {row['seconds']:.2f} s ; fin : {row['finish_reason']}", ""])
        if case.get("reference_url"):
            lines.extend(["[Source de la référence](" + case["reference_url"] + ")", ""])
        if row["error"]:
            lines.append("Erreur : " + row["error"])
        lines.extend([row["answer"] or "[Aucun texte]", "", "Contrôles :"])
        lines.extend(f"- {'OK' if check['passed'] else 'ÉCHEC'} : {check['label']}" for check in row["checks"])
        lines.append("")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=14)
    parser.add_argument("--case", nargs="+", help="Run only these case IDs (for focused regression checks).")
    parser.add_argument("--web-case", nargs="+", default=[], help="Also evaluate these public cases with browser search on the last model.")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--models", nargs="+", default=["openai/gpt-oss-20b", "openai/gpt-oss-120b"])
    parser.add_argument("--output", type=Path, default=ROOT / "evals/results/latest.json")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reuse", type=Path, help="Reuse successful responses only when model, exact input, and generation settings match.")
    args = parser.parse_args()
    if args.limit < 1 or not 1 <= args.repeats <= 10:
        parser.error("Use a positive limit and 1 to 10 repeats.")
    load_dotenv(ROOT / ".env")
    if not os.getenv("GROQ_API_KEY"):
        parser.error("GROQ_API_KEY must be configured in .env.")
    case_text = (ROOT / "evals/cases.json").read_text(encoding="utf-8")
    case_text = case_text.replace("{CURRENT_YEAR}", application_date()[:4])
    cases = json.loads(case_text)[:args.limit]
    if args.case:
        selected = set(args.case)
        if selected - {case["id"] for case in cases}:
            parser.error("Unknown case ID or case outside --limit.")
        cases = [case for case in cases if case["id"] in selected]
    variants = [("baseline-20b", args.models[0], True)] + [
        ("quality-" + model.rsplit("/", 1)[-1], model, False) for model in dict.fromkeys(args.models)
    ]
    if args.web_case:
        if set(args.web_case) - {case["id"] for case in cases}:
            parser.error("Unknown --web-case ID.")
        variants.append(("web-" + args.models[-1].rsplit("/", 1)[-1], args.models[-1], False))
    fingerprint = hashlib.sha256((json.dumps(cases, sort_keys=True) + json.dumps(variants)
                                  + (ROOT / "answer_quality.py").read_text(encoding="utf-8")
                                  + (ROOT / "evals/baseline.py").read_text(encoding="utf-8")
                                  + (ROOT / "evals/scoring.py").read_text(encoding="utf-8")).encode()).hexdigest()
    run = {"started_at": datetime.now(timezone.utc).isoformat(), "fingerprint": fingerprint,
           "repeats": args.repeats, "prompt_version": PROMPT_VERSION, "results": []}
    if args.resume and args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if previous["fingerprint"] != fingerprint or previous["repeats"] != args.repeats:
            parser.error("The checkpoint belongs to different cases or instructions. Use a different output file.")
        run = previous
    finished = {(row["variant"], row["case_id"], row["repeat"]): row.get("input_fingerprint")
                for row in run["results"] if not row["error"] and row["finish_reason"] == "stop" and row["answer"].strip()}
    cache = {}
    if args.reuse:
        previous = json.loads(args.reuse.read_text(encoding="utf-8"))
        cache = {(row.get("input_fingerprint"), row["repeat"]): row for row in previous["results"]
                 if row.get("input_fingerprint") and not row["error"] and row["finish_reason"] == "stop" and row["answer"].strip()}
    with OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1", timeout=60, max_retries=0) as client:
        for repeat in range(1, args.repeats + 1):
            for case in cases:
                for variant, model, baseline in variants:
                    use_web = variant.startswith("web-")
                    if use_web and case["id"] not in args.web_case:
                        continue
                    messages = baseline_context(case) if baseline else build_context(
                        case.get("history", []), case.get("specialty", "general"), case["question"],
                        case.get("filename"), case.get("source"), case.get("answer_level", "intermediate"), web_access=use_web)
                    row = {"variant": variant, "model": model, "case_id": case["id"], "repeat": repeat,
                           "answer": "", "error": None, "finish_reason": None, "prompt_tokens": 0, "completion_tokens": 0}
                    request_data = {"model": model, "messages": messages, "temperature": 0.2, "max_completion_tokens": 4096}
                    if use_web:
                        request_data.update(tools=[{"type": "browser_search"}], tool_choice="required", reasoning_effort="low")
                    input_hash = hashlib.sha256(json.dumps(request_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    if finished.get((variant, case["id"], repeat)) == input_hash:
                        continue
                    row["input_fingerprint"] = input_hash
                    cached = cache.get((input_hash, repeat))
                    if cached:
                        row.update({key: cached[key] for key in ("answer", "finish_reason", "prompt_tokens", "completion_tokens", "seconds")})
                        row["reused_from"] = str(args.reuse)
                    started = time.monotonic()
                    for attempt in range(0 if cached else 3):
                        try:
                            response = client.chat.completions.create(**request_data)
                            row["answer"] = (web_answer(response) if use_web else response.choices[0].message.content) or ""
                            if use_web and not row["answer"]:
                                row["error"] = "MissingWebSources"
                            row["finish_reason"] = response.choices[0].finish_reason
                            if response.usage:
                                row["prompt_tokens"] = response.usage.prompt_tokens
                                row["completion_tokens"] = response.usage.completion_tokens
                            break
                        except AuthenticationError:
                            print("Authentication failed. Check .env; no key has been printed.", flush=True)
                            return 1
                        except RateLimitError:
                            if attempt < 2:
                                print(f"Rate limit for {model}; retrying in 20 seconds.", flush=True)
                                time.sleep(20)
                            else:
                                row["error"] = "RateLimitError"
                        except Exception as error:
                            row["error"] = type(error).__name__
                            break
                    if not cached:
                        row["seconds"] = time.monotonic() - started
                    row["checks"] = check_answer(row["answer"], case["checks"], complete=not row["error"] and row["finish_reason"] == "stop")
                    row["score"] = sum(check["passed"] for check in row["checks"]) / len(row["checks"])
                    run["results"] = [old for old in run["results"] if (old["variant"], old["case_id"], old["repeat"]) != (variant, case["id"], repeat)]
                    run["results"].append(row)
                    write_report(args.output, run, cases)
                    print(f"{variant} / {case['id']}: {row['score']:.0%}, {row['seconds']:.2f}s" + (f" ({row['error']})" if row["error"] else ""), flush=True)
    print("Reports saved:", args.output, "and", args.output.with_suffix(".md"), flush=True)
    return int(any(row["error"] for row in run["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
