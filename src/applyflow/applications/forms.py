"""Analyse de formulaire HTML et construction d'un plan de préremplissage sûr."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from applyflow.applications.answers import find_answer, normalize_question
from applyflow.text import normalize_text

if TYPE_CHECKING:
    from applyflow.db.models import ApplicationAnswer, Profile, Resume

SKIP_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}

FIELD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("first_name", re.compile(r"\b(?:first[\s_-]?name|given[\s_-]?name|prenom)\b")),
    ("last_name", re.compile(r"\b(?:last[\s_-]?name|family[\s_-]?name|surname|nom de famille)\b")),
    ("full_name", re.compile(r"\b(?:full[\s_-]?name|nom complet|your name|^name$|^nom$)")),
    ("email", re.compile(r"\b(?:e[\s_-]?mail|email address|courriel)\b")),
    ("phone", re.compile(r"\b(?:phone|telephone|mobile|tel)\b")),
    ("linkedin", re.compile(r"linkedin")),
    ("github", re.compile(r"github")),
    (
        "other_link",
        re.compile(
            r"\b(?:other (?:website|link|url|site)|additional (?:link|website|url)|"
            r"autre (?:site|lien)|lien supplementaire)\b"
        ),
    ),
    ("website", re.compile(r"\b(?:website|portfolio|site web|personal site)\b")),
    ("resume", re.compile(r"\b(?:resume|cv|curriculum|attachment|piece jointe)\b")),
    ("cover_letter", re.compile(r"\b(?:cover letter|lettre de motivation|motivation letter)\b")),
    ("salary", re.compile(r"\b(?:salary|salaire|remuneration|compensation|pretention)\b")),
    (
        "work_authorization",
        re.compile(
            r"\b(?:work authori[sz]ation|authori[sz]ed to work|right to work|"
            r"autorisation de travail|visa status)\b"
        ),
    ),
    ("start_date", re.compile(r"\b(?:start date|availability|disponibilite|date de debut)\b")),
    ("location", re.compile(r"\b(?:location|city|ville|adresse|address)\b")),
    ("remote", re.compile(r"\b(?:remote|teletravail)\b")),
]


class FormField(BaseModel):
    label: str
    name: str
    input_type: str = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)
    option_labels: list[str] = Field(default_factory=list)
    selector: str = ""
    key: str = "custom"
    placeholder: str | None = None


class FormAnalysis(BaseModel):
    source_url: str = ""
    page_title: str = ""
    fields: list[FormField] = Field(default_factory=list)
    submit_label: str | None = None


class PlannedFill(BaseModel):
    selector: str
    label: str
    key: str
    value: str
    source: Literal["profile", "resume", "answer_library"]
    input_type: str = "text"
    # Nom lisible à présenter (le CV est stocké sous son identifiant : le recruteur doit
    # voir « cv-nom-prenom.pdf », jamais l'empreinte du stockage).
    display: str | None = None


class UnknownQuestion(BaseModel):
    label: str
    selector: str
    name: str = ""
    required: bool = False
    key: str = "custom"


class KitItem(BaseModel):
    """Une information du profil à copier quand on postule à la main."""

    key: str
    label: str
    value: str


class ApplicationPlan(BaseModel):
    source_url: str = ""
    page_title: str = ""
    mode: str = "dry_run"
    fills: list[PlannedFill] = Field(default_factory=list)
    unknown_questions: list[UnknownQuestion] = Field(default_factory=list)
    missing_values: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    can_prepare: bool = False
    blocked_reason: str | None = None
    manual_kit: list[KitItem] = Field(default_factory=list)


class FormAnalysisError(ValueError):
    pass


class NoFormFields(FormAnalysisError):
    """La page est lisible mais n'a aucun formulaire de candidature exploitable.

    C'est le cas des sites qui demandent une connexion (HelloWork…) ou qui fabriquent leur
    formulaire en JavaScript : on ne se connecte jamais à votre place, on prépare un dossier.
    """


def _clean_selector_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _selector(element: Tag) -> str:
    element_id = element.get("id")
    if element_id:
        return f"#{element_id}"
    name = element.get("name")
    if name:
        return f'[name="{_clean_selector_value(str(name))}"]'
    return ""


def _label_for(element: Tag, soup: BeautifulSoup) -> str:
    element_id = element.get("id")
    if element_id:
        label = soup.find("label", attrs={"for": element_id})
        if label:
            return label.get_text(" ", strip=True)
    parent = element.find_parent("label")
    if parent:
        text = parent.get_text(" ", strip=True)
        if text:
            return text
    for attribute in ("aria-label", "placeholder"):
        value = element.get(attribute)
        if value:
            return str(value).strip()
    name = element.get("name") or element.get("id")
    if name:
        return str(name).replace("_", " ").replace("-", " ").strip()
    return "champ sans libellé"


def _clean_label(label: str) -> str:
    """Retire l'astérisque de « champ obligatoire » pour stabiliser les clés de réponse."""
    cleaned = re.sub(r"\s*\*+\s*", " ", label).strip(" :")
    return re.sub(r"\s{2,}", " ", cleaned)



def _classify(label: str, name: str, input_type: str) -> str:
    if input_type == "file":
        return "resume"
    if input_type == "email":
        return "email"
    if input_type == "tel":
        return "phone"
    haystack = normalize_text(f"{label} {name}")
    if haystack in {"name", "nom"}:
        return "full_name"
    for key, pattern in FIELD_PATTERNS:
        if pattern.search(haystack):
            return key
    return "custom"


# Formulaires de la page qui ne sont pas une candidature : recherche, alerte e-mail, connexion…
_NOT_APPLICATION_ACTION = re.compile(
    r"alert|newsletter|subscribe|search|recherche|login|signin|sign-in|connexion|bookmark|"
    r"favori|onetap|cookie|consent",
    re.I,
)


def _is_application_form(form: Tag | BeautifulSoup, soup: BeautifulSoup) -> bool:
    """Un champ CV, ou un nom ET un e-mail : un champ e-mail seul est une alerte ou une lettre."""
    elements = form.find_all(["input", "select", "textarea"])
    if any(str(el.get("type") or "").lower() == "password" for el in elements):
        return False  # page de connexion
    if _NOT_APPLICATION_ACTION.search(str(form.get("action") or "")):
        return False
    keys: set[str | None] = set()
    for el in elements:
        if el.name == "select":
            input_type = "select"
        elif el.name == "textarea":
            input_type = "textarea"
        else:
            input_type = str(el.get("type") or "text").lower()
            if input_type in SKIP_INPUT_TYPES:
                continue
        label = _clean_label(_label_for(el, soup))
        keys.add(_classify(label, str(el.get("name") or el.get("id") or ""), input_type))
    return "resume" in keys or ("email" in keys and bool(keys & {"full_name", "first_name", "last_name"}))


def _pick_form(soup: BeautifulSoup) -> Tag | BeautifulSoup | None:
    """Le formulaire de candidature de la page, ou None s'il n'y en a pas de lisible.

    Une page contient souvent d'autres formulaires (recherche, alerte e-mail, connexion) : on ne
    remplit jamais l'un d'eux à la place de la candidature. Parmi les candidats, celui qui a le
    plus de champs utiles (un CV compte le plus) ; à égalité, le premier.
    """
    candidates = soup.find_all("form") or [soup]
    accepted = [form for form in candidates if _is_application_form(form, soup)]
    if not accepted:
        return None

    def score(form: Tag | BeautifulSoup) -> int:
        fields = form.find_all(["input", "select", "textarea"])
        visible = [f for f in fields if str(f.get("type") or "text").lower() not in SKIP_INPUT_TYPES]
        has_file = any(str(f.get("type") or "").lower() == "file" for f in fields)
        return (3 if has_file else 0) + len(visible)

    return max(accepted, key=score)


def analyze_html(html: str, source_url: str = "") -> FormAnalysis:
    soup = BeautifulSoup(html, "html.parser")
    form = _pick_form(soup)
    if form is None:
        raise NoFormFields("aucun champ de formulaire détecté")
    title = soup.title.get_text(strip=True) if soup.title else ""
    fields: list[FormField] = []
    for element in form.find_all(["input", "select", "textarea"]):
        if element.name == "select":
            input_type = "select"
        elif element.name == "textarea":
            input_type = "textarea"
        else:
            input_type = str(element.get("type") or "text").lower()
        if element.name == "input" and input_type in SKIP_INPUT_TYPES:
            continue
        if element.has_attr("disabled"):
            continue
        name = str(element.get("name") or element.get("id") or "")
        raw_label = _label_for(element, soup)
        label = _clean_label(raw_label)
        required = element.has_attr("required") or str(element.get("aria-required", "")).lower() == "true"
        if not required and "*" in raw_label:
            required = True
        options: list[str] = []
        option_labels: list[str] = []
        if element.name == "select":
            for option in element.find_all("option"):
                value = str(option.get("value") or option.get_text(strip=True))
                text = option.get_text(" ", strip=True)
                if not value and not text:
                    continue
                options.append(value)
                option_labels.append(text or value)
        key = _classify(label, name, input_type)
        fields.append(
            FormField(
                label=label,
                name=name,
                input_type=input_type,
                required=required,
                options=options,
                option_labels=option_labels,
                selector=_selector(element),
                key=key,
                placeholder=element.get("placeholder"),
            )
        )
    if not fields:
        raise NoFormFields("aucun champ de formulaire détecté")
    submit = form.find("button", attrs={"type": "submit"}) or form.find(
        "input", attrs={"type": "submit"}
    )
    submit_label = None
    if submit is not None:
        submit_label = submit.get_text(" ", strip=True) or submit.get("value")
    return FormAnalysis(
        source_url=source_url, page_title=title, fields=fields, submit_label=submit_label
    )


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _match_option(value: str, field: FormField) -> str | None:
    candidates = [value, *[part.strip() for part in value.split(",") if part.strip()]]
    for candidate in candidates:
        target = normalize_text(candidate)
        if not target:
            continue
        for option in field.options:
            if normalize_text(option) == target:
                return option
        for option, label in zip(field.options, field.option_labels, strict=False):
            if normalize_text(label) == target:
                return option
    for candidate in candidates:
        target = normalize_text(candidate)
        if not target:
            continue
        for option, label in zip(field.options, field.option_labels, strict=False):
            normalized_label = normalize_text(label)
            if normalized_label and (target in normalized_label or normalized_label in target):
                return option
    return None


def _profile_values(
    profile: Profile, resume: Resume | None, resume_path: str | None
) -> dict[str, str | None]:
    first, last = _split_name(profile.full_name or "")
    return {
        "first_name": first or None,
        "last_name": last or None,
        "full_name": profile.full_name or None,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.city,
        "linkedin": profile.linkedin_url,
        "github": profile.github_url,
        "website": profile.website,
        "other_link": next(
            (link.get("url") for link in (profile.other_links or []) if link.get("url")), None
        ),
        "resume": resume_path if resume else None,
        "salary": str(profile.salary_min) if profile.salary_min else None,
        "work_authorization": profile.work_authorization,
        "remote": ", ".join(profile.remote_preferences) if profile.remote_preferences else None,
    }


def manual_kit(profile: Profile) -> list[KitItem]:
    """Ce qu'il faut pour postuler à la main : uniquement des valeurs réellement renseignées."""
    values = _profile_values(profile, None, None)
    salary = (
        f"{profile.salary_min} {profile.salary_currency or 'EUR'} brut par an (minimum)"
        if profile.salary_min
        else None
    )
    wanted = [
        ("full_name", "Nom complet", values["full_name"]),
        ("email", "E-mail", values["email"]),
        ("phone", "Téléphone", values["phone"]),
        ("location", "Ville", values["location"]),
        ("linkedin", "LinkedIn", values["linkedin"]),
        ("github", "GitHub", values["github"]),
        ("website", "Portfolio", values["website"]),
        ("other_link", "Autre lien", values["other_link"]),
        ("work_authorization", "Autorisation de travail", values["work_authorization"]),
        ("salary", "Prétentions salariales", salary),
    ]
    return [KitItem(key=key, label=label, value=str(value)) for key, label, value in wanted if value]


PROFILE_SOURCE_KEYS = {
    "first_name",
    "last_name",
    "full_name",
    "email",
    "phone",
    "location",
    "linkedin",
    "github",
    "website",
    "other_link",
    "resume",
    "salary",
    "work_authorization",
    "remote",
}


def build_plan(
    analysis: FormAnalysis,
    *,
    profile: Profile,
    resume: Resume | None,
    answers: dict[str, ApplicationAnswer],
    resume_path: str | None = None,
    mode: str = "dry_run",
) -> ApplicationPlan:
    plan = ApplicationPlan(
        source_url=analysis.source_url,
        page_title=analysis.page_title,
        mode=mode,
    )
    profile_values = _profile_values(profile, resume, resume_path)
    blocked: list[str] = []

    for field in analysis.fields:
        if not field.selector:
            plan.warnings.append(f"Champ sans sélecteur ignoré : {field.label}")
            continue

        value: str | None = None
        source: Literal["profile", "resume", "answer_library"] = "profile"
        answer = find_answer(answers, field.label)

        if field.key in PROFILE_SOURCE_KEYS:
            value = profile_values.get(field.key)
            source = "resume" if field.key == "resume" else "profile"
            # Une question à choix (ex. autorisation de travail oui/non) ne peut pas
            # être déduite mécaniquement du profil : seule une réponse validée compte.
            if answer and (value is None or (field.options and _match_option(value, field) is None)):
                value = answer.answer
                source = "answer_library"
        elif answer:
            value = answer.answer
            source = "answer_library"

        if value is not None and value.strip():
            if field.options:
                matched = _match_option(value, field)
                if matched is None:
                    if field.required:
                        plan.unknown_questions.append(
                            UnknownQuestion(
                                label=field.label,
                                selector=field.selector,
                                name=field.name,
                                required=True,
                                key=field.key,
                            )
                        )
                    else:
                        plan.warnings.append(
                            f"Valeur hors options ignorée pour « {field.label} » : {value}"
                        )
                    continue
                value = matched
            plan.fills.append(
                PlannedFill(
                    selector=field.selector,
                    label=field.label,
                    key=field.key,
                    value=value,
                    source=source,
                    input_type=field.input_type,
                    display=resume.filename if (field.key == "resume" and resume) else None,
                )
            )
            continue

        # Valeur indisponible : jamais inventée.
        if field.required:
            if field.key in PROFILE_SOURCE_KEYS:
                plan.missing_values.append(field.label)
                if field.key == "resume":
                    blocked.append("aucun CV PDF actif associé au profil")
            plan.unknown_questions.append(
                UnknownQuestion(
                    label=field.label,
                    selector=field.selector,
                    name=field.name,
                    required=True,
                    key=field.key,
                )
            )
        else:
            plan.warnings.append(f"Champ facultatif non rempli faute de donnée : {field.label}")

    if resume is None:
        if any(field.key == "resume" for field in analysis.fields):
            if not blocked:
                blocked.append("aucun CV PDF actif associé au profil")
        else:
            plan.warnings.append("Aucun CV actif : vérifier que le formulaire n'en demande pas")
    if plan.missing_values:
        blocked.append("valeurs obligatoires absentes du profil : " + ", ".join(plan.missing_values))

    plan.blocked_reason = "; ".join(dict.fromkeys(blocked)) or None
    plan.can_prepare = plan.blocked_reason is None
    return plan


def plan_requires_review(plan: ApplicationPlan) -> bool:
    return plan.blocked_reason is None and any(
        question.required for question in plan.unknown_questions
    )


def answer_key_for(label: str) -> str:
    return normalize_question(label)


def summarize_plan(plan: ApplicationPlan) -> dict[str, Any]:
    return {
        "fills": len(plan.fills),
        "unknown_required": sum(1 for item in plan.unknown_questions if item.required),
        "unknown_optional": sum(1 for item in plan.unknown_questions if not item.required),
        "can_prepare": plan.can_prepare,
        "blocked_reason": plan.blocked_reason,
    }
