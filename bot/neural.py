"""Запрос к нейросети: системный промпт с памятью и разбор JSON-ответа."""

import asyncio
import json
import logging
import os
import re

import aiohttp

logger = logging.getLogger(__name__)


class NeuralApiError(RuntimeError):
    """Ошибка HTTP от API нейросети. status — код ответа, без тела с фрагментом ключа."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)

# Параметры вызова совместимого с OpenAI chat completions.
DEFAULT_BASE_URL = 'https://api.openai.com/v1'
DEFAULT_MODEL = 'gpt-4o-mini'
LLM_TEMPERATURE = 0.4
REQUEST_TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1.0
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

_JSON_FENCE_PATTERN = re.compile(r'```(?:json)?\s*(\{.*\})\s*```', re.DOTALL)

_INSTRUCTION = (
    'Ты — собеседник в Telegram с долгосрочной памятью.\n'
    'Отвечай на языке пользователя.\n'
    'Верни строго один JSON-объект и никакого текста вокруг него.\n'
    'Первый ключ — "theses": список коротких строк.\n'
    'В этот список помести только тезисы текущего хода: '
    'суть вопроса пользователя и суть твоего ответа.\n'
    'Не копируй в theses старые пункты из блока ниже.\n'
    'Второй ключ — "message": обычный текст ответа человеку в чат.\n'
    'В message не упоминай JSON, ключи и то, что тезисы куда-то сохраняются.\n'
    'Пример формы, не содержания:\n'
    '{"theses": ["Пользователь спросил про память бота.", '
    '"Бот объяснил, что помнит прошлые темы."], '
    '"message": "Да, я помню, о чём мы уже говорили."}'
)


def build_system_prompt(db_theses: list[str]) -> str:
    """Собирает системный промпт и явно помечает тезисы как данные из базы."""
    cleaned = [item.strip() for item in db_theses if item and item.strip()]
    if cleaned:
        lines = '\n'.join(f'- {item}' for item in cleaned)
        memory = (
            'Тезисы из базы данных. Это тезисы из базы данных — '
            'долгосрочная память прошлых диалогов с этим пользователем. '
            'Опирайся на них, чтобы не терять контекст после перезапуска:\n'
            f'{lines}'
        )
    else:
        memory = (
            'Тезисы из базы данных: записей пока нет. '
            'Это начало диалога с пользователем.'
        )
    return f'{_INSTRUCTION}\n\n{memory}'


def parse_model_payload(raw: str) -> tuple[list[str], str]:
    """Достаёт список тезисов и текст message из ответа модели."""
    payload = _load_json_object(raw)
    if 'theses' in payload:
        raw_theses = payload['theses']
    elif 'тезисы' in payload:
        raw_theses = payload['тезисы']
    else:
        raise ValueError('В JSON нет ключа theses')

    raw_message = payload.get('message')
    if not isinstance(raw_message, str) or not raw_message.strip():
        raise ValueError('Ключ message пустой или отсутствует')

    return _normalize_theses(raw_theses), raw_message.strip()


async def generate_reply(
    db_theses: list[str],
    user_text: str,
) -> tuple[list[str], str]:
    """Просит модель вернуть тезисы текущего хода и текст для чата."""
    system_prompt = build_system_prompt(db_theses)
    raw = await complete_chat(system_prompt, user_text)
    try:
        return parse_model_payload(raw)
    except ValueError:
        logger.warning('Модель вернула не JSON, повторяю запрос: %s', raw[:500])
        repair_prompt = (
            system_prompt
            + '\nПредыдущий ответ был невалидным. '
            + 'Верни только JSON с ключами theses и message.'
        )
        raw_retry = await complete_chat(repair_prompt, user_text)
        return parse_model_payload(raw_retry)


async def complete_chat(system_prompt: str, user_text: str) -> str:
    """Вызывает chat completions и возвращает сырой текст ответа модели."""
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('Не задан OPENAI_API_KEY')

    base_url = os.getenv('OPENAI_BASE_URL', DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    raw_model = os.getenv('OPENAI_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL
    model = normalize_model_name(raw_model, base_url)
    url = base_url.rstrip('/') + '/chat/completions'
    payload = build_chat_payload(model, system_prompt, user_text)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    last_error: Exception | None = None

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(RETRY_ATTEMPTS):
            try:
                async with session.post(url, headers=headers, json=payload) as response:
                    raw_body = await response.text()
                    if response.status in TRANSIENT_STATUS_CODES:
                        last_error = RuntimeError(
                            f'Временная ошибка API: {response.status} {raw_body}'
                        )
                        await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
                        continue
                    if response.status >= 400:
                        raise _api_error(response.status, raw_body)
                    return _extract_content(_decode_body(raw_body))
            except aiohttp.ClientError as error:
                last_error = error
                await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** attempt))

    raise RuntimeError('Не удалось связаться с API нейросети') from last_error


def normalize_model_name(model: str, base_url: str) -> str:
    """На api.openai.com модель называется gpt-6-luna, а не openai/gpt-6-luna."""
    if 'api.openai.com' in base_url.lower() and model.startswith('openai/'):
        return model.split('/', 1)[1]
    return model


def build_chat_payload(model: str, system_prompt: str, user_text: str) -> dict:
    """Собирает тело запроса. У gpt-5/gpt-6 параметр temperature API не принимает."""
    payload: dict = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ],
    }
    if _is_reasoning_model(model):
        # none — обычный текст в content, без скрытых токенов рассуждения.
        payload['reasoning_effort'] = 'none'
    else:
        payload['temperature'] = LLM_TEMPERATURE
    return payload


def _is_reasoning_model(model: str) -> bool:
    """Модели с рассуждением не принимают произвольный temperature."""
    name = model.lower()
    prefixes = ('gpt-5', 'gpt-6', 'o1', 'o3', 'o4')
    return name.startswith(prefixes)


def _api_error(status: int, raw_body: str) -> NeuralApiError:
    """401 не пишем в лог целиком: в теле OpenAI повторяет кусок ключа."""
    if status == 401:
        return NeuralApiError(
            status,
            'Ключ OPENAI_API_KEY отклонён. Нужен действующий ключ с platform.openai.com.',
        )
    details = raw_body[:500]
    return NeuralApiError(status, f'Ошибка API нейросети: {status} {details}')


def _decode_body(raw_body: str) -> dict:
    """Превращает тело HTTP-ответа в словарь и проверяет, что это объект."""
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise RuntimeError('API вернуло не JSON') from error
    if not isinstance(body, dict):
        raise RuntimeError('API вернуло не объект JSON')
    return body


def _extract_content(body: dict) -> str:
    """Берёт текст сообщения из choices[0], в том числе если content пришёл частями."""
    try:
        content = body['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError('Неожиданный ответ API нейросети') from error

    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get('text'), str):
                parts.append(part['text'])
        text = ''.join(parts).strip()
        if text:
            return text
    raise RuntimeError('Пустой ответ нейросети')


def _load_json_object(raw: str) -> dict:
    """Находит JSON-объект в ответе модели, даже если он обёрнут в ```json."""
    text = raw.strip()
    fenced = _JSON_FENCE_PATTERN.search(text)
    if fenced is not None:
        text = fenced.group(1)
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start == -1 or end <= start:
            raise ValueError('В ответе модели нет JSON-объекта')
        text = text[start:end + 1]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError('Ответ модели не является валидным JSON') from error
    if not isinstance(payload, dict):
        raise ValueError('Ответ модели не является JSON-объектом')
    return payload


def _normalize_theses(raw_theses: object) -> list[str]:
    """Приводит theses к списку непустых строк, не меняя исходный объект."""
    if isinstance(raw_theses, str):
        text = raw_theses.strip()
        return [text] if text else []
    if not isinstance(raw_theses, list):
        raise ValueError('Ключ theses должен быть списком строк')

    result: list[str] = []
    for item in raw_theses:
        text = str(item).strip()
        if text:
            result.append(text)
    return result
