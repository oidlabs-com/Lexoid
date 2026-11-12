from types import SimpleNamespace

from lexoid.core.parse_type.llm_parser import _create_client_response


def test_anthropic_request_includes_system_prompt():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="response")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    result = _create_client_response(
        client=client,
        api="anthropic",
        model="claude-sonnet-5-5",
        system_prompt="Return valid JSON.",
        user_prompt="Evaluate this run.",
        image_url=None,
        temperature=0.0,
        max_tokens=1024,
    )

    assert captured["system"] == "Return valid JSON."
    assert result["response"] == "response"
