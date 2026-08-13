"""Реестр провайдеров: эндпоинты, модели-кандидаты, ориентировочные цены.

Каталоги моделей у всех провайдеров меняются без предупреждения, поэтому
перед прогоном стоит выполнить `python3 bench.py --list-models` — он спросит
у каждого API реальный список и покажет, какие из указанных ниже ещё живы.

Цены — ориентир на август 2026, доллары за миллион токенов (вход/выход).
Нужны только для оценки порядка расходов, не для бухгалтерии.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class Provider:
    key: str                       # короткий идентификатор
    title: str                     # человекочитаемое имя
    kind: str                      # gemini | openai | anthropic
    env: str                       # переменная окружения с ключом
    base_url: str = ""
    models: list[str] = field(default_factory=list)
    region: str = ""               # юрисдикция размещения
    free: str = ""                 # что даёт бесплатно
    price: dict[str, tuple[float, float]] = field(default_factory=dict)
    min_interval: float = 1.0      # секунд между запросами (защита от RPM-лимитов)
    notes: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
#  США / Европа
# --------------------------------------------------------------------------

GOOGLE = Provider(
    key="google",
    title="Google Gemini",
    kind="gemini",
    env="GEMINI_API_KEY",
    base_url="https://generativelanguage.googleapis.com/v1beta",
    models=["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    region="США",
    free="есть бесплатный тариф, лимиты режут",
    price={
        "gemini-3.6-flash": (1.50, 7.50),
        "gemini-3.5-flash-lite": (0.30, 2.50),
    },
    min_interval=6.0,
    notes="единственный с бесплатным поиском в интернете (grounding)",
)

GROQ = Provider(
    key="groq",
    title="Groq",
    kind="openai",
    env="GROQ_API_KEY",
    base_url="https://api.groq.com/openai/v1",
    models=["llama-3.3-70b-versatile", "qwen3-32b", "openai/gpt-oss-120b"],
    region="США",
    free="да, ~30 запросов/мин",
    min_interval=2.0,
    notes="самая быстрая генерация, открытые веса",
)

CEREBRAS = Provider(
    key="cerebras",
    title="Cerebras",
    kind="openai",
    env="CEREBRAS_API_KEY",
    base_url="https://api.cerebras.ai/v1",
    models=["gpt-oss-120b", "zai-glm-4.7", "qwen-3-235b-a22b-instruct"],
    region="США",
    free="да, ~1 млн токенов/сутки",
    min_interval=2.0,
)

MISTRAL = Provider(
    key="mistral",
    title="Mistral AI",
    kind="openai",
    env="MISTRAL_API_KEY",
    base_url="https://api.mistral.ai/v1",
    models=["mistral-small-latest", "mistral-large-latest", "open-mistral-nemo"],
    region="Франция (ЕС)",
    free="да, ~1 млрд токенов/мес, но 2 запроса/мин",
    min_interval=31.0,
    notes="европейская юрисдикция, GDPR",
)

OPENROUTER = Provider(
    key="openrouter",
    title="OpenRouter",
    kind="openai",
    env="OPENROUTER_API_KEY",
    base_url="https://openrouter.ai/api/v1",
    models=[
        "deepseek/deepseek-chat-v3.1:free",
        "z-ai/glm-4.5-air:free",
        "qwen/qwen3-235b-a22b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
    ],
    region="агрегатор",
    free="да, ~30 моделей с суффиксом :free",
    min_interval=4.0,
    notes="один ключ на множество моделей, удобен как резерв",
    extra_headers={"HTTP-Referer": "https://github.com/Chistovik92/radar", "X-Title": "Radar"},
)

OPENAI = Provider(
    key="openai",
    title="OpenAI",
    kind="openai",
    env="OPENAI_API_KEY",
    base_url="https://api.openai.com/v1",
    models=["gpt-5.5", "gpt-4.1-mini"],
    region="США",
    free="нет, только оплата",
    min_interval=1.0,
)

ANTHROPIC = Provider(
    key="anthropic",
    title="Anthropic Claude",
    kind="anthropic",
    env="ANTHROPIC_API_KEY",
    base_url="https://api.anthropic.com/v1",
    models=["claude-haiku-4-5-20251001", "claude-sonnet-5"],
    region="США",
    free="нет, только оплата",
    min_interval=1.0,
)

COHERE = Provider(
    key="cohere",
    title="Cohere",
    kind="openai",
    env="COHERE_API_KEY",
    base_url="https://api.cohere.ai/compatibility/v1",
    models=["command-a-03-2025", "command-r7b-12-2024"],
    region="Канада",
    free="пробный тариф, запрещено личное использование",
    min_interval=6.0,
    notes="условия лицензии не подходят для домашнего проекта — проверяйте ToS",
)

GITHUB = Provider(
    key="github",
    title="GitHub Models",
    kind="openai",
    env="GITHUB_TOKEN",
    base_url="https://models.github.ai/inference",
    models=["openai/gpt-4.1-mini", "mistral-ai/mistral-small-2503"],
    region="США",
    free="да, по токену GitHub",
    min_interval=4.0,
)

NVIDIA = Provider(
    key="nvidia",
    title="NVIDIA NIM",
    kind="openai",
    env="NVIDIA_API_KEY",
    base_url="https://integrate.api.nvidia.com/v1",
    models=["deepseek-ai/deepseek-v3.1", "qwen/qwen3-next-80b-a3b-instruct"],
    region="США",
    free="ознакомительный доступ, ~40 запросов/мин",
    min_interval=2.0,
)

TOGETHER = Provider(
    key="together",
    title="Together AI",
    kind="openai",
    env="TOGETHER_API_KEY",
    base_url="https://api.together.xyz/v1",
    models=[
        "deepseek-ai/DeepSeek-V3",
        "Qwen/Qwen2.5-72B-Instruct-Turbo",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ],
    region="США",
    free="стартовый кредит",
    min_interval=1.5,
)

SAMBANOVA = Provider(
    key="sambanova",
    title="SambaNova",
    kind="openai",
    env="SAMBANOVA_API_KEY",
    base_url="https://api.sambanova.ai/v1",
    models=["Meta-Llama-3.3-70B-Instruct", "DeepSeek-V3-0324"],
    region="США",
    free="$5 кредита на 30 дней",
    min_interval=2.0,
)

# --------------------------------------------------------------------------
#  Азия
# --------------------------------------------------------------------------

DEEPSEEK = Provider(
    key="deepseek",
    title="DeepSeek",
    kind="openai",
    env="DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com/v1",
    models=["deepseek-chat", "deepseek-v4-flash", "deepseek-reasoner"],
    region="КНР",
    free="5 млн токенов на 30 дней, дальше платно и очень дёшево",
    price={"deepseek-v4-flash": (0.14, 0.28), "deepseek-chat": (0.14, 0.28)},
    min_interval=1.0,
    notes="самая низкая цена на рынке; проверьте фильтрацию военных тем",
)

ZAI = Provider(
    key="zai",
    title="Z.ai / Zhipu GLM",
    kind="openai",
    env="ZAI_API_KEY",
    base_url="https://api.z.ai/api/paas/v4",
    models=["glm-4.7-flash", "glm-4.5-air", "glm-4.6"],
    region="КНР",
    free="Flash-модели бесплатны с оговорками по лицензии",
    min_interval=1.5,
)

MOONSHOT = Provider(
    key="moonshot",
    title="Moonshot Kimi",
    kind="openai",
    env="MOONSHOT_API_KEY",
    base_url="https://api.moonshot.ai/v1",
    models=["kimi-k2-0905-preview", "moonshot-v1-32k"],
    region="КНР",
    free="до 1000 запросов/сутки на базовой модели",
    min_interval=2.0,
)

DASHSCOPE = Provider(
    key="qwen",
    title="Alibaba Qwen (DashScope)",
    kind="openai",
    env="DASHSCOPE_API_KEY",
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    models=["qwen-plus", "qwen-turbo", "qwen3-max"],
    region="КНР / Сингапур",
    free="стартовая квота токенов",
    min_interval=1.5,
    notes="международный эндпоинт, регистрация без китайского номера",
)

MINIMAX = Provider(
    key="minimax",
    title="MiniMax",
    kind="openai",
    env="MINIMAX_API_KEY",
    base_url="https://api.minimax.io/v1",
    models=["MiniMax-M2", "abab6.5s-chat"],
    region="КНР",
    free="стартовый кредит",
    min_interval=2.0,
)

ALL: list[Provider] = [
    GOOGLE, GROQ, CEREBRAS, MISTRAL, OPENROUTER,
    DEEPSEEK, ZAI, MOONSHOT, DASHSCOPE, MINIMAX,
    OPENAI, ANTHROPIC, COHERE, GITHUB, NVIDIA, TOGETHER, SAMBANOVA,
]

BY_KEY = {provider.key: provider for provider in ALL}


def resolve(names: list[str]) -> list[Provider]:
    """Отбирает провайдеров по списку ключей; пустой список — все."""
    if not names:
        return list(ALL)
    chosen = []
    for name in names:
        provider = BY_KEY.get(name.strip().lower())
        if provider is None:
            raise SystemExit(
                f"Неизвестный провайдер «{name}». Доступные: {', '.join(BY_KEY)}"
            )
        chosen.append(provider)
    return chosen
