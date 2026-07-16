from ai_research_agent.llm.client import LLMConfig, create_llm_client
from ai_research_agent.llm.providers.deepseek import DeepSeekClient


def test_create_deepseek_client() -> None:
    client = create_llm_client(
        LLMConfig(
            provider="deepseek",
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model_name="deepseek-chat",
        )
    )

    assert isinstance(client, DeepSeekClient)
    assert client.model_name == "deepseek-chat"


def test_deepseek_chat_completions_url() -> None:
    client = DeepSeekClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model_name="deepseek-chat",
    )

    assert client._chat_completions_url() == "https://api.deepseek.com/chat/completions"
