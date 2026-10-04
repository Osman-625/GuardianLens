from __future__ import annotations
from .config import settings, provider_client_options

def openai_models() -> list[str]:
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key, **provider_client_options())
    return sorted(m.id for m in client.models.list())

def anthropic_models() -> list[str]:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, **provider_client_options())
    return sorted(m.id for m in client.models.list())

def omniroute_models() -> list[str]:
    from openai import OpenAI
    client = OpenAI(
        api_key=settings.omniroute_api_key,
        base_url=settings.omniroute_base_url,
        **provider_client_options(),
    )
    return sorted(m.id for m in client.models.list())

def gemini_models() -> list[str]:
    from openai import OpenAI
    client = OpenAI(
        api_key=settings.gemini_api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        **provider_client_options(),
    )
    return sorted(m.id for m in client.models.list())

MODEL_LISTERS = {"openai": openai_models, "anthropic": anthropic_models, "omniroute": omniroute_models, "gemini": gemini_models}
