"""Append-only source identity using the existing exact-URL rule."""
from copy import deepcopy
from research_assistant.schemas import Source


def merge_sources(existing: list[dict], results: list[dict], round_number: int) -> tuple[list[dict], list[str]]:
    if not isinstance(results, list):
        raise ValueError('Поиск должен вернуть список источников.')
    registry = [Source.model_validate(s).model_dump(mode='json') for s in deepcopy(existing)]
    indexes = {s['url']: i for i, s in enumerate(registry)}
    used = []
    for raw in results:
        item = Source.model_validate({**raw, 'section_indexes': [round_number - 1]}).model_dump(mode='json')
        if item['url'] in indexes:
            index = indexes[item['url']]
            registry[index]['section_indexes'] = sorted(set(registry[index]['section_indexes'] + item['section_indexes']))
        else:
            index = len(registry)
            indexes[item['url']] = index
            registry.append(item)
        sid = f'S{index + 1}'
        if sid not in used:
            used.append(sid)
    return registry, used


def validate_source_ids(ids: list[str], allowed_ids: list[str]) -> list[str]:
    if not isinstance(ids, list) or any(not isinstance(s, str) or s not in allowed_ids for s in ids):
        raise ValueError('Ответ содержит неизвестный source_id.')
    return list(dict.fromkeys(ids))


def source_context(sources: list[dict], ids: list[str]) -> list[dict]:
    return [{'id': f'S{i}', 'title': s['title'], 'snippet': s['snippet']}
            for i, s in enumerate(sources, 1) if f'S{i}' in ids]
