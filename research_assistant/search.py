"""Sequential search adapter using the official Tavily SDK."""

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from pydantic import ValidationError
from tavily import TavilyClient
from tavily.errors import (
    BadRequestError, ForbiddenError, InvalidAPIKeyError,
    TimeoutError as TavilyTimeoutError, UsageLimitExceededError,
)

from research_assistant.schemas import Source


class SearchError(Exception):
    """Expected configuration, request or response error during search."""


def validate_search_query(query: str) -> None:
    if not query.strip():
        raise SearchError("Поисковый запрос не должен быть пустым.")
    if len(query) > 400:
        raise SearchError(
            f"Поисковый запрос содержит {len(query)} символов; Tavily допускает максимум 400. "
            "Сократите тему, название или вопросы раздела перед утверждением плана. "
            "Запрос не обрезан и не отправлен."
        )


def _require_results(payload: Any) -> list:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SearchError("Tavily вернул некорректную структуру ответа: ожидается список results.")
    return payload["results"]


def _validate_response(response: requests.Response, **kwargs) -> requests.Response:
    # SDK 0.8.5 adds results=[] when the field is missing. Check the actual
    # response first so malformed success bodies cannot become empty searches.
    if response.status_code == 200:
        _require_results(response.json())
    elif response.status_code < 400:
        raise SearchError(f"Tavily вернул неожиданный HTTP {response.status_code}; ожидался HTTP 200.")
    return response


def search_web(query: str) -> list[dict[str, Any]]:
    """Return validated title/url/snippet records; never fetch full pages."""
    validate_search_query(query)
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False, encoding="utf-8-sig")
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise SearchError("Укажите TAVILY_API_KEY в окружении или .env для поиска.")
    try:
        with requests.Session() as session:
            session.hooks["response"].append(_validate_response)
            client = TavilyClient(api_key=api_key, session=session)
            payload = client.search(
                query=query, search_depth="basic", max_results=3,
                include_answer=False, include_raw_content=False,
                auto_parameters=False, timeout=30,
            )
    except InvalidAPIKeyError as error:
        raise SearchError("Tavily отклонил ключ. Проверьте TAVILY_API_KEY.") from error
    except UsageLimitExceededError as error:
        raise SearchError("Достигнут лимит Tavily. Проверьте квоту и баланс.") from error
    except ForbiddenError as error:
        raise SearchError("Доступ к Tavily запрещён. Проверьте разрешения аккаунта.") from error
    except BadRequestError as error:
        raise SearchError("Tavily отклонил поисковый запрос. Проверьте его параметры.") from error
    except TavilyTimeoutError as error:
        raise SearchError("Истекло время ожидания Tavily (30 с).") from error
    except requests.exceptions.JSONDecodeError as error:
        raise SearchError("Tavily вернул ответ, который не является корректным JSON.") from error
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else "неизвестен"
        raise SearchError(f"Ошибка Tavily (HTTP {status}). Поиск не завершён.") from error
    except requests.RequestException as error:
        raise SearchError("Не удалось подключиться к Tavily. Проверьте сеть.") from error

    sources = []
    for item in _require_results(payload):
        if not isinstance(item, dict):
            raise SearchError("Tavily вернул некорректный источник: ожидается объект.")
        try:
            source = Source.model_validate({
                "title": item.get("title"), "url": item.get("url"),
                "snippet": item.get("content", ""), "section_indexes": [],
            })
        except ValidationError as error:
            raise SearchError("Источник Tavily не прошёл проверку title, HTTP(S) URL или snippet.") from error
        sources.append(source.model_dump(mode="json", exclude={"section_indexes"}))
    return sources
