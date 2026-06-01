"""
hh.ru vacancy scraper.

Usage:
    python3 hh_parser.py
    python3 hh_parser.py --query "React TypeScript" --area 1 --days 3
    python3 hh_parser.py --ai --limit 30
"""

import csv
import json
import time
import argparse
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL       = "https://hh.ru/search/vacancy"
GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL     = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
YANDEX_URL     = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
DEEPSEEK_URL   = "https://api.deepseek.com/v1/chat/completions"
CONFIG_PATH    = "config.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_exclude_keywords() -> list:
    return load_config().get("exclude_title_keywords", [])


def analyze_with_llm(description: str, config: dict) -> dict:
    """Send vacancy description to configured LLM API, return structured analysis."""
    empty = {
        "stack_summary": None, "frontend_framework": None,
        "backend_framework": None, "styling": None,
        "other_languages": [], "employment": None,
        "company_description": None, "important": None,
    }
    if not description:
        return empty

    provider = config.get("llm_provider", "yandex")

    # ── Yandex GPT (нативный формат) ──────────────────────────
    if provider == "yandex":
        api_key   = config.get("yandex_api_key", "")
        folder_id = config.get("yandex_folder_id", "")
        model     = config.get("yandex_model", "yandexgpt-lite")
        placeholders = ("YOUR_YANDEX_API_KEY",)
        if not api_key or api_key in placeholders or not folder_id:
            print("    ! yandex_api_key / yandex_folder_id не заданы в config.json")
            return empty

        prompt = config.get("analysis_prompt", "")
        full_prompt = (
            f"{prompt}\n\n"
            "Верни ТОЛЬКО валидный JSON без пояснений и markdown.\n\n"
            f"Текст вакансии:\n{description[:4000]}"
        )
        payload = {
            "modelUri": f"gpt://{folder_id}/{model}/latest",
            "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": "600"},
            "messages": [{"role": "user", "text": full_prompt}],
        }
        parsed = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    YANDEX_URL,
                    headers={"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 429:
                    wait = 15 * (attempt + 1)
                    print(f"    ! Rate limit, жду {wait}с...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                text = resp.json()["result"]["alternatives"][0]["message"]["text"]
                m = re.search(r"\{.*\}", text, re.DOTALL)
                if m:
                    parsed = json.loads(m.group())
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    ! Yandex GPT error: {e}")
                    return empty
                time.sleep(5)
        if not parsed:
            return empty

    # ── OpenAI-совместимые провайдеры ─────────────────────────
    else:
        if provider == "gemini":
            api_key = config.get("gemini_api_key", "")
            api_url = GEMINI_URL
            model   = config.get("gemini_model", "gemini-2.0-flash")
            extra_headers = {}
        elif provider == "openrouter":
            api_key = config.get("openrouter_api_key", "")
            api_url = OPENROUTER_URL
            model   = config.get("openrouter_model", "meta-llama/llama-3.3-70b-instruct:free")
            extra_headers = {"HTTP-Referer": "https://hh-parser.local", "X-Title": "HH Parser"}
        elif provider == "deepseek":
            api_key = config.get("deepseek_api_key", "")
            api_url = DEEPSEEK_URL
            model   = config.get("deepseek_model", "deepseek-chat")
            extra_headers = {}
        else:  # groq
            api_key = config.get("groq_api_key", "")
            api_url = GROQ_URL
            model   = config.get("groq_model", "llama-3.3-70b-versatile")
            extra_headers = {}

        placeholders = ("YOUR_GROQ_API_KEY", "YOUR_OPENROUTER_API_KEY", "YOUR_GEMINI_API_KEY")
        if not api_key or api_key in placeholders:
            print(f"    ! API key не задан в config.json (provider: {provider})")
            return empty

        prompt = config.get("analysis_prompt", "")
        full_prompt = f"{prompt}\n\nТекст вакансии:\n{description[:4000]}"
        req_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        req_headers.update(extra_headers)
        oai_payload = {
            "model": model,
            "messages": [{"role": "user", "content": full_prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 512,
        }
        parsed = None
        for attempt in range(4):
            try:
                resp = requests.post(api_url, headers=req_headers, json=oai_payload, timeout=60)
                if resp.status_code == 429:
                    wait = 20 * (attempt + 1)
                    print(f"    ! Rate limit, жду {wait}с...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
                break
            except Exception as e:
                if attempt == 3:
                    print(f"    ! LLM error: {e}")
                    return empty
                time.sleep(10)
        if not parsed:
            return empty

    _JS = {"javascript", "typescript", "js", "ts"}
    other_langs = [l for l in (parsed.get("other_languages") or []) if l.lower() not in _JS]
    company = parsed.get("company_description")
    if isinstance(company, list):
        company = " ".join(str(s) for s in company) or None

    return {
        "stack_summary":       parsed.get("stack_summary") or None,
        "frontend_framework":  parsed.get("frontend_framework") or None,
        "backend_framework":   parsed.get("backend_framework") or None,
        "styling":             parsed.get("styling") or None,
        "other_languages":     other_langs,
        "employment":          parsed.get("employment") or None,
        "company_description": company or None,
        "important":           parsed.get("important") or None,
    }


def generate_cover_letter(description: str, config: dict):
    """Generate a cover letter for the vacancy using configured LLM."""
    prompt_file = config.get("cover_letter_prompt_file", "")
    if prompt_file:
        try:
            with open(prompt_file, encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            print(f"    ! cover_letter_prompt_file не найден: {prompt_file}")
            return None
    else:
        prompt_template = config.get("cover_letter_prompt", "")

    if not prompt_template or not description:
        return None

    full_prompt = f"{prompt_template}\n\n{description[:4000]}"
    provider = config.get("llm_provider", "yandex")

    if provider == "yandex":
        api_key   = config.get("yandex_api_key", "")
        folder_id = config.get("yandex_folder_id", "")
        model     = config.get("yandex_model", "yandexgpt-lite")
        if not api_key or api_key in ("YOUR_YANDEX_API_KEY",) or not folder_id:
            return None
        payload = {
            "modelUri": f"gpt://{folder_id}/{model}/latest",
            "completionOptions": {"stream": False, "temperature": 0.3, "maxTokens": "800"},
            "messages": [{"role": "user", "text": full_prompt}],
        }
        for attempt in range(3):
            try:
                resp = requests.post(
                    YANDEX_URL,
                    headers={"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 429:
                    time.sleep(15 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()["result"]["alternatives"][0]["message"]["text"].strip()
            except Exception as e:
                if attempt == 2:
                    print(f"    ! Yandex GPT cover letter error: {e}")
                    return None
                time.sleep(5)
        return None

    if provider == "gemini":
        api_key, api_url = config.get("gemini_api_key", ""), GEMINI_URL
        model, extra_headers = config.get("gemini_model", "gemini-2.0-flash"), {}
    elif provider == "openrouter":
        api_key, api_url = config.get("openrouter_api_key", ""), OPENROUTER_URL
        model = config.get("openrouter_model", "meta-llama/llama-3.3-70b-instruct:free")
        extra_headers = {"HTTP-Referer": "https://hh-parser.local", "X-Title": "HH Parser"}
    elif provider == "deepseek":
        api_key, api_url = config.get("deepseek_api_key", ""), DEEPSEEK_URL
        model, extra_headers = config.get("deepseek_model", "deepseek-chat"), {}
    else:  # groq
        api_key, api_url = config.get("groq_api_key", ""), GROQ_URL
        model, extra_headers = config.get("groq_model", "llama-3.3-70b-versatile"), {}

    if not api_key or api_key in ("YOUR_GROQ_API_KEY", "YOUR_OPENROUTER_API_KEY", "YOUR_GEMINI_API_KEY"):
        return None

    req_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    req_headers.update(extra_headers)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.3,
        "max_tokens": 800,
    }
    for attempt in range(4):
        try:
            resp = requests.post(api_url, headers=req_headers, json=payload, timeout=60)
            if resp.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == 3:
                print(f"    ! LLM cover letter error: {e}")
                return None
            time.sleep(10)
    return None


def is_excluded(title: str, keywords: list) -> bool:
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def fetch_vacancy_details(session: requests.Session, url: str) -> tuple:
    """Fetch full vacancy page once, return (details_dict, description_text)."""
    empty_details = {
        "employment_type": [],
        "work_format": None,
        "schedule": None,
        "full_employment": None,
        "it_accredited": False,
        "salary_net": None,
        "full_skills": [],
    }
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        def qa_text(data_qa, strip_prefix=None):
            el = soup.find(attrs={"data-qa": data_qa})
            if not el:
                return None
            text = el.get_text(separator=" ", strip=True)
            if strip_prefix:
                text = re.sub(strip_prefix, "", text).strip()
            return text or None

        hiring_el = soup.find(attrs={"data-qa": "vacancy-hiring-formats"})
        if hiring_el:
            raw = hiring_el.get_text(separator=" ", strip=True)
            raw = re.sub(r"^Оформление\s*[:\s]+", "", raw).strip()
            empty_details["employment_type"] = [p.strip() for p in re.split(r"[·•]", raw) if p.strip()]

        empty_details["work_format"]     = qa_text("work-formats-text",          r"^Формат работы\s*[:\s]+")
        empty_details["schedule"]        = qa_text("work-schedule-by-days-text", r"^График\s*[:\s]+")
        empty_details["full_employment"] = qa_text("common-employment-text")
        empty_details["salary_net"]      = qa_text("vacancy-salary-compensation-type-net")
        empty_details["it_accredited"]   = soup.find(attrs={"data-qa": "employer-card-employer-it-accreditation"}) is not None
        empty_details["full_skills"]     = [s.get_text(strip=True) for s in soup.find_all(attrs={"data-qa": "skills-element"})]

        desc_el = soup.find(attrs={"data-qa": "vacancy-description"})
        description = desc_el.get_text(separator=" ", strip=True)[:4000] if desc_el else ""

        return empty_details, description
    except Exception:
        return empty_details, ""


def fetch_page(session: requests.Session, query: str, area: int, days: int, page: int) -> tuple:
    params = {
        "text": query,
        "area": area,
        "order_by": "publication_time",
        "search_period": days,
        "per_page": 20,
        "page": page,
    }
    resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser"), resp.text


def extract_pub_dates(html: str) -> dict:
    dates = {}
    for m in re.finditer(r'"vacancyId":(\d+)', html):
        vid = m.group(1)
        window = html[m.start():m.start() + 3000]
        dt_m = re.search(r'publicationTime[^}]+?"([0-9]{4}-[0-9]{2}-[0-9]{2}T[^"]+)"', window)
        if dt_m:
            dates[vid] = dt_m.group(1)
    return dates


def get_page_count(soup: BeautifulSoup) -> int:
    pager = soup.find(attrs={"data-qa": "pager-block"})
    if not pager:
        return 1
    pages = pager.find_all("a", attrs={"data-qa": lambda x: x and "pager-page" in x})
    if not pages:
        return 1
    nums = []
    for p in pages:
        try:
            nums.append(int(p.get_text(strip=True)))
        except ValueError:
            pass
    return max(nums) if nums else 1


def get_total(soup: BeautifulSoup) -> str:
    header = soup.find(attrs={"data-qa": "vacancies-search-header"})
    if header:
        m = re.search(r"\d[\d\s]*", header.get_text())
        return m.group().replace(" ", "") if m else "?"
    return "?"


def parse_salary(card: BeautifulSoup) -> str:
    comp_el = card.find(attrs={"data-qa": lambda x: x and "compensation-frequency" in x})
    if not comp_el:
        return "не указана"
    try:
        container_text = comp_el.parent.parent.parent.parent.get_text(strip=True)
    except AttributeError:
        return "не указана"
    m = re.search(r"([\d\s]+(?:–|-)[\d\s]+[₽$€]|от\s*[\d\s]+[₽$€]|до\s*[\d\s]+[₽$€])", container_text)
    return m.group().strip() if m else "не указана"


def parse_card(card: BeautifulSoup, pub_dates: dict) -> dict:
    link_el    = card.find("a", attrs={"data-qa": "serp-item__title"})
    title_el   = card.find(attrs={"data-qa": "serp-item__title-text"})
    company_el = card.find(attrs={"data-qa": "vacancy-serp__vacancy-employer-text"})
    city_el    = card.find(attrs={"data-qa": "vacancy-serp__vacancy-address"})
    exp_el     = card.find(attrs={"data-qa": lambda x: x and "work-experience" in x})
    remote_el  = card.find(attrs={"data-qa": "vacancy-label-work-schedule-remote"})
    skill_els  = card.find_all(attrs={"data-qa": "skills-element"})

    url = ""
    vacancy_id = card.get("id", "")
    if link_el and link_el.get("href"):
        url = link_el["href"].split("?")[0]
        if not vacancy_id:
            m = re.search(r"/vacancy/(\d+)", url)
            vacancy_id = m.group(1) if m else ""

    return {
        "title":        title_el.get_text(strip=True)   if title_el   else "",
        "company":      company_el.get_text(strip=True) if company_el else "",
        "salary":       parse_salary(card),
        "city":         city_el.get_text(strip=True)    if city_el    else "",
        "experience":   exp_el.get_text(strip=True)     if exp_el     else "",
        "remote":       "да" if remote_el else "нет",
        "published_at": pub_dates.get(vacancy_id, ""),
        "skills":       [s.get_text(strip=True) for s in skill_els],
        "url":          url,
    }


def scrape(query: str, area: int, days: int, max_pages: int, limit: int, use_ai: bool = False) -> list:
    session = requests.Session()
    vacancies = []
    config = load_config()
    exclude_keywords = config.get("exclude_title_keywords", [])

    print(f"Ищем: «{query}» | регион={area} | за {days} дн. | цель: {limit} вакансий")
    if exclude_keywords:
        print(f"Исключаем из заголовка: {', '.join(exclude_keywords)}")
    if use_ai:
        provider = config.get("llm_provider", "openrouter")
        model = config.get(f"{provider}_model", "")
        cover = "+ письма" if (config.get("cover_letter_prompt_file") or config.get("cover_letter_prompt")) else ""
        print(f"AI-анализ: {provider} ({model}) {cover}")

    first_soup, first_html = fetch_page(session, query, area, days, 0)
    total = get_total(first_soup)
    page_count = min(get_page_count(first_soup), max_pages)
    print(f"Найдено на hh.ru: {total} вакансий, страниц: {page_count}")

    for page in range(page_count):
        if page == 0:
            soup, html = first_soup, first_html
        else:
            time.sleep(1.5)
            soup, html = fetch_page(session, query, area, days, page)

        pub_dates = extract_pub_dates(html)
        cards = soup.find_all("div", attrs={"data-qa": "vacancy-serp__vacancy"})

        for card in cards:
            v = parse_card(card, pub_dates)
            if not v["title"]:
                continue
            if is_excluded(v["title"], exclude_keywords):
                continue

            idx = len(vacancies) + 1
            print(f"  [{idx}/{limit}] {v['title'][:55]}")
            details, description = fetch_vacancy_details(session, v["url"])
            v["details"] = details
            if use_ai:
                v["analysis"] = analyze_with_llm(description, config)
                if config.get("cover_letter_prompt_file") or config.get("cover_letter_prompt"):
                    v["cover_letter"] = generate_cover_letter(description, config)
                else:
                    v["cover_letter"] = None
                time.sleep(1.5)
            else:
                v["analysis"] = None
                v["cover_letter"] = None
            time.sleep(0.3)

            vacancies.append(v)
            if len(vacancies) >= limit:
                print(f"  Страница {page + 1} — набрано {len(vacancies)}, стоп")
                return vacancies

        print(f"  Страница {page + 1}/{page_count} — подходящих: {len(vacancies)}/{limit}")

    return vacancies


def save_json(vacancies: list, query: str, path: str) -> None:
    if not vacancies:
        print("Вакансий не найдено.")
        return

    payload = {
        "parsed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "query": query,
        "count": len(vacancies),
        "vacancies": vacancies,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\nСохранено {len(vacancies)} вакансий → {path}")


def save_csv(vacancies: list, path: str) -> None:
    if not vacancies:
        return

    fields = [
        "title", "company", "salary", "salary_net", "city", "experience",
        "work_format", "schedule", "employment_type", "full_employment",
        "it_accredited", "published_at", "skills", "url", "cover_letter",
    ]

    def flatten(v: dict) -> dict:
        d = v.get("details") or {}
        return {
            "title":           v.get("title", ""),
            "company":         v.get("company", ""),
            "salary":          v.get("salary", ""),
            "salary_net":      d.get("salary_net") or "",
            "city":            v.get("city", ""),
            "experience":      v.get("experience", ""),
            "work_format":     d.get("work_format") or "",
            "schedule":        d.get("schedule") or "",
            "employment_type": " · ".join(d.get("employment_type") or []),
            "full_employment": d.get("full_employment") or "",
            "it_accredited":   "да" if d.get("it_accredited") else "нет",
            "published_at":    v.get("published_at", ""),
            "skills":          ", ".join(d.get("full_skills") or v.get("skills") or []),
            "url":             v.get("url", ""),
            "cover_letter":    v.get("cover_letter") or "",
        }

    rows = [flatten(v) for v in vacancies]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="hh.ru vacancy scraper")
    parser.add_argument("--query",     default="Frontend разработчик React TypeScript")
    parser.add_argument("--area",      type=int, default=113, help="113=Россия, 1=Москва, 2=СПб")
    parser.add_argument("--days",      type=int, default=3,   help="Вакансии за последние N дней")
    parser.add_argument("--json-out",  default="frontend/public/vacancies.json")
    parser.add_argument("--csv-out",   default="vacancies.csv")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--limit",     type=int, default=50,  help="Сколько вакансий собрать")
    parser.add_argument("--no-ai",      action="store_true",   help="Отключить AI-анализ и генерацию писем")
    args = parser.parse_args()

    vacancies = scrape(args.query, args.area, args.days, args.max_pages, args.limit, not args.no_ai)
    save_json(vacancies, args.query, args.json_out)
    save_csv(vacancies, args.csv_out)

    if vacancies:
        print("\nТоп-5 вакансий:")
        for v in vacancies[:5]:
            d = v.get("details") or {}
            emp  = " · ".join(d.get("employment_type") or []) or ""
            fmt  = d.get("work_format") or ("удалённо" if v["remote"] == "да" else "")
            acc  = " [IT ✓]" if d.get("it_accredited") else ""
            sal  = d.get("salary_net") or v["salary"]
            print(f"  {v['title']} @ {v['company']}{acc}")
            print(f"  {sal} | {v['experience']} | {fmt}{' | ' + emp if emp else ''}")
            print(f"  {v['url']}")
            if v.get("cover_letter"):
                print(f"\n  --- Сопроводительное письмо ---")
                print(f"  {v['cover_letter']}")
            print()


if __name__ == "__main__":
    main()
