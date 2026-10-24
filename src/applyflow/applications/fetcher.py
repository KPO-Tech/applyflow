"""Récupération du HTML d'un formulaire de candidature."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx

from applyflow.config import PROJECT_ROOT, Settings


class FormFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchedForm:
    url: str
    html: str


DEMO_FORMS: dict[str, str] = {
    "demo://greenhouse": "playground/greenhouse_form.html",
    "demo://lever": "playground/lever_form.html",
    "demo://custom": "playground/custom_form.html",
    "demo://custom-unknown": "playground/custom_form.html",
    "demo://simple": "playground/simple_form.html",
    "demo://js": "playground/js_form.html",
}


def demo_form_path(url: str) -> Path | None:
    relative = DEMO_FORMS.get(url.rstrip("/"))
    if relative is None:
        return None
    return PROJECT_ROOT / relative


def browser_url(url: str) -> str:
    """Convertit une URL de démonstration en file:// pour Playwright."""
    path = demo_form_path(url)
    return path.as_uri() if path else url


class FormFetcher(Protocol):
    def fetch(self, url: str) -> FetchedForm: ...


class DemoFormFetcher:
    def fetch(self, url: str) -> FetchedForm:
        path = demo_form_path(url)
        if path is None:
            raise FormFetchError(f"formulaire de démonstration inconnu : {url}")
        if not path.is_file():
            raise FormFetchError(f"page de démonstration absente : {path}")
        return FetchedForm(url=url, html=path.read_text(encoding="utf-8"))


# Une offre Lever : /{entreprise}/{identifiant}. Le formulaire est à la même adresse + /apply.
_LEVER_POSTING = re.compile(r"^/[^/]+/[0-9a-fA-F-]{36}/?$")


def form_page_url(url: str) -> str:
    """Adresse de la page qui contient le formulaire, quand elle diffère de celle de l'offre.

    Sur Lever, la page de l'offre n'a pas de formulaire ; il se trouve sous `/apply`.
    """
    parts = urlsplit(url)
    if parts.hostname == "jobs.lever.co" and _LEVER_POSTING.match(parts.path):
        return urlunsplit(parts._replace(path=parts.path.rstrip("/") + "/apply"))
    return url


class HttpFormFetcher:
    def __init__(
        self,
        *,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    def fetch(self, url: str) -> FetchedForm:
        if not url.startswith(("http://", "https://")):
            raise FormFetchError(f"URL http(s) attendue : {url}")
        url = form_page_url(url)
        try:
            with httpx.Client(
                timeout=self.settings.discovery.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": self.settings.discovery.user_agent},
                transport=self._transport,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FormFetchError(
                f"formulaire inaccessible (HTTP {exc.response.status_code}). "
                "ApplyFlow ne contourne ni CAPTCHA ni protection antibot."
            ) from exc
        except httpx.HTTPError as exc:
            raise FormFetchError(f"formulaire inaccessible : {exc}") from exc

        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        if content_type and content_type not in {"text/html", "application/xhtml+xml"}:
            raise FormFetchError(f"contenu non HTML : {content_type}")
        if len(response.content) > self.settings.application.max_form_bytes:
            raise FormFetchError("formulaire trop volumineux")
        return FetchedForm(url=str(response.url), html=response.text)


class BrowserFormFetcher:
    """Lit la page telle qu'un navigateur la rend.

    Beaucoup d'ATS (Teamtailor, Workday, Jobvite…) construisent le formulaire en JavaScript :
    le HTML servi ne contient alors aucun champ. On récupère le DOM affiché, sans aucune
    interaction : rien n'est cliqué, rien n'est soumis.
    """

    def __init__(self, settings: Settings, *, headless: bool | None = None) -> None:
        self.settings = settings
        self.headless = settings.application.headless if headless is None else headless

    def fetch(self, url: str) -> FetchedForm:
        demo = demo_form_path(url) if url.startswith("demo://") else None
        if demo is not None:
            target = demo.as_uri()
        else:
            if not url.startswith(("http://", "https://")):
                raise FormFetchError(f"URL http(s) attendue : {url}")
            target = form_page_url(url)
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dépendance déclarée
            raise FormFetchError(
                "Playwright n'est pas installé : impossible de lire la page rendue"
            ) from exc

        timeout_ms = int(self.settings.discovery.timeout_seconds * 1000)
        try:
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch(headless=self.headless)
                try:
                    page = browser.new_page(
                        user_agent=self.settings.discovery.user_agent, locale="fr-FR"
                    )
                    page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
                    # Le formulaire se monte après le premier rendu : court délai plutôt que
                    # « networkidle », qui ne se calme jamais sur ces pages.
                    page.wait_for_timeout(1_500)
                    html = page.content()
                    final_url = page.url
                finally:
                    browser.close()
        except PlaywrightTimeout as exc:
            raise FormFetchError("page rendue trop lente à charger (délai dépassé)") from exc
        except PlaywrightError as exc:
            raise FormFetchError(f"page rendue inaccessible : {exc}") from exc

        if len(html) > self.settings.application.max_form_bytes:
            raise FormFetchError("formulaire trop volumineux")
        return FetchedForm(url=final_url, html=html)


class DemoAndHttpFetcher:
    """Choisit le lecteur local pour `demo://`, HTTP pour les sites réels, et le navigateur
    (`render`) quand la page statique ne contient aucun champ."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.demo = DemoFormFetcher()
        self.http = HttpFormFetcher(settings=settings, transport=transport)
        self._browser: BrowserFormFetcher | None = None

    def render(self, url: str) -> FetchedForm:
        """Relit la page dans un navigateur ; appelé seulement si le HTML statique est vide."""
        if not self.settings.application.render_forms:
            raise FormFetchError(
                "lecture de la page rendue désactivée (application.render_forms = false)"
            )
        if self._browser is None:
            self._browser = BrowserFormFetcher(self.settings)
        return self._browser.fetch(url)

    def fetch(self, url: str) -> FetchedForm:
        if url.startswith("demo://"):
            if not self.settings.app.demo_forms:
                raise FormFetchError("les formulaires de démonstration sont désactivés")
            return self.demo.fetch(url)
        return self.http.fetch(url)
