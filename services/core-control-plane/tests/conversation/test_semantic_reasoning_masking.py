"""Identifier placeholders, typed input holds, and content-free traces in the form adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fdai.core.conversation.adaptive_call_scope import bind_adaptive_model_budget
from fdai.core.conversation.adaptive_models import AdaptivePolicy
from fdai.core.conversation.adaptive_service import _Budget
from fdai.core.conversation.semantic_reasoning_proposal import (
    FormInputHeldError,
    resolve_question_form,
)
from fdai.core.conversation.semantic_reasoning_shadow import run_reasoning_shadow
from fdai.delivery.azure.llm.identity_masking import IdentityMask
from fdai.delivery.azure.llm.semantic_question_form import (
    AzureOpenAIQuestionFormConfig,
    AzureOpenAIQuestionFormModel,
)

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    plan_verifier,
    production_manifest,
)
from tests.conversation.test_semantic_reasoning_shadow import _adapter, _Identity

_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app"
    "/providers/Microsoft.Compute/virtualMachines/vm-app-01"
)
_UTTERANCE = f"What depends on {_ID}, and does 10.0.0.4 reach {_ID}?"


def _form(anchor: dict[str, Any]) -> dict[str, Any]:
    return {
        "mentions": [{"id": "m1", "form": "identifier", "domain": "instance", "span": anchor}],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": {"text": "depends on", "occurrence": 1},
                },
                "cue": {"text": "What depends", "occurrence": 1},
                "confidence": 0.9,
            }
        ],
    }


async def _propose(anchor: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(json.loads(request.content)["messages"][1]["content"]))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(_form(anchor))}}]}
        )

    proposal = await _adapter(handler).propose_form(
        utterance=_UTTERANCE,
        context=(f"Earlier: {_ID}",),
        locale="en",
        pass_index=0,
        prior_goals=(),
    )
    return (dict(proposal) if proposal is not None else None), sent


async def test_identifiers_travel_as_placeholders_and_quotes_map_back_exactly() -> None:
    proposal, sent = await _propose({"text": "\u27e6ID1\u27e7", "occurrence": 2})

    assert _ID not in json.dumps(sent) and "10.0.0.4" not in json.dumps(sent)
    assert (
        sent["utterance"]
        == "What depends on \u27e6ID1\u27e7, and does \u27e6ID2\u27e7 reach \u27e6ID1\u27e7?"
    )
    assert sent["context"] == ["Earlier: \u27e6ID1\u27e7"]
    assert proposal is not None
    assert proposal["mentions"][0]["span"] == {"text": _ID, "occurrence": 2}
    resolved = resolve_question_form(proposal, utterance=_UTTERANCE)
    assert resolved.form is not None
    assert resolved.form.mentions[0].span.start == _UTTERANCE.rindex(_ID)


async def test_a_quote_through_a_placeholder_can_never_resolve() -> None:
    proposal, _sent = await _propose({"text": "ID1", "occurrence": 1})

    assert proposal is not None
    resolved = resolve_question_form(proposal, utterance=_UTTERANCE)
    assert resolved.form is None
    assert "quote_not_verbatim:span" in resolved.reasons


def test_bracketed_input_is_never_masked_so_redaction_still_holds_it() -> None:
    mask = IdentityMask(f"Is \u27e6ID1\u27e7 {_ID}?", ())

    assert mask.usable is False
    assert mask.utterance == f"Is \u27e6ID1\u27e7 {_ID}?"


async def test_the_request_ceiling_holds_the_call_before_any_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    base = _adapter(handler)
    adapter = AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=base._config.candidates,
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
            max_request_tokens=64,
        ),
    )

    with pytest.raises(FormInputHeldError) as held:
        await adapter.propose_form(
            utterance="List VMs", context=(), locale="en", pass_index=0, prior_goals=()
        )

    assert held.value.reason == "request_budget_exceeded"
    assert requests == []
    with pytest.raises(ValueError, match="request token ceiling"):
        AzureOpenAIQuestionFormConfig(
            candidates=base._config.candidates,
            form_system_prompt="p",
            concept_system_prompt="c",
            max_request_tokens=0,
        )


async def test_recorded_traces_carry_no_utterance_or_reply_text() -> None:
    sentinel = "zebra-note-77"
    reply = {"mentions": [], "goals": [], "note": sentinel}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(reply)}}],
                "usage": {"total_tokens": 99},
            },
        )

    budget = _Budget(AdaptivePolicy())
    async with bind_adaptive_model_budget(budget, reserved_calls=1):
        await _adapter(handler).propose_form(
            utterance=f"Which VMs mention {sentinel}?",
            context=(),
            locale="en",
            pass_index=0,
            prior_goals=(),
        )

    (observation,) = budget.observations
    assert sentinel not in repr(observation)
    assert observation.trace_call["request"]["messages"] == []  # type: ignore[index]
    assert observation.trace_call["response"]["content"] == ""  # type: ignore[index]
    assert observation.usage == {"total_tokens": 99}


async def test_a_held_input_is_a_typed_shadow_disposition() -> None:
    class _Held:
        async def propose_form(self, **_kwargs: Any) -> None:
            raise FormInputHeldError("input_redacted")

        async def choose_concepts(self, **_kwargs: Any) -> None:
            return None

    observation = await run_reasoning_shadow(
        model=_Held(),
        utterance="List VMs",
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )

    assert [(item.disposition, item.reasons) for item in observation.passes] == [
        ("input_held", ("input_redacted",))
    ]


async def test_the_default_ceiling_admits_a_call_with_the_released_prompt() -> None:
    from pathlib import Path

    from fdai.core.prompts.profiles import compose_static_selection
    from fdai.core.prompts.registry import FileSystemPromptRegistry

    root = Path(__file__).resolve().parents[4] / "rule-catalog"
    registry = FileSystemPromptRegistry(root)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    base = _adapter(handler)
    adapter = AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=base._config.candidates,
            form_system_prompt=compose_static_selection(
                registry.resolve("semantic.question_form")
            ).system_text,
            concept_system_prompt=compose_static_selection(
                registry.resolve("semantic.concept_selection")
            ).system_text,
        ),
    )

    await adapter.propose_form(
        utterance="What changed on vm-app-01 in the last 3 days?",
        context=(),
        locale="en",
        pass_index=0,
        prior_goals=(),
    )

    assert len(requests) == 1


def test_a_particle_after_an_identifier_stays_outside_its_placeholder() -> None:
    utterance = f"{_ID}의 CPU 사용률은?"
    mask = IdentityMask(utterance, ())

    assert mask.utterance == "\u27e6ID1\u27e7의 CPU 사용률은?"
    unmasked = mask.unmask_form(
        {"mentions": [{"id": "m1", "span": {"text": "\u27e6ID1\u27e7", "occurrence": 1}}]}
    )
    assert unmasked["mentions"][0]["span"] == {"text": _ID, "occurrence": 1}


def test_a_rejected_form_is_shown_with_quotes_anchored_to_the_masked_utterance() -> None:
    utterance = "compare 10.0.0.10 and 10.0.0.1"
    mask = IdentityMask(utterance, ())
    previous = {
        "mentions": [
            {"id": "m1", "span": {"text": "10.0.0.10", "occurrence": 1}},
            {"id": "m2", "span": {"text": "10.0.0.1", "occurrence": 2}},
        ],
        "goals": [{"id": "g1", "cue": {"text": "compare", "occurrence": 1}}],
    }

    masked = mask.mask_form(previous)

    assert mask.utterance == "compare \u27e6ID1\u27e7 and \u27e6ID2\u27e7"
    assert [item["span"] for item in masked["mentions"]] == [
        {"text": "\u27e6ID1\u27e7", "occurrence": 1},
        {"text": "\u27e6ID2\u27e7", "occurrence": 1},
    ]
    assert mask.unmask_form(masked)["mentions"] == previous["mentions"]


@pytest.mark.parametrize("wrapped", (f"`{_ID}`", f"**{_ID}**", f"|{_ID}|", f"'{_ID}'"))
def test_markdown_wrapping_stays_outside_the_placeholder(wrapped: str) -> None:
    mask = IdentityMask(f"What depends on {wrapped}?", ())

    assert _ID not in mask.utterance
    unmasked = mask.unmask_form(
        {"mentions": [{"id": "m1", "span": {"text": "\u27e6ID1\u27e7", "occurrence": 1}}]}
    )
    assert unmasked["mentions"][0]["span"]["text"] == _ID


@pytest.mark.parametrize(
    ("text", "rule"),
    (
        ("token-" + "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxIn0" + ".c2lnbmF0dXJl", "jwt"),
        ("토큰" + "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxIn0" + ".c2lnbmF0dXJl을", "jwt"),
        ("alice@contoso.com-owned VMs", "email"),
        ("admin@contoso.com의 권한", "email"),
    ),
)
def test_secrets_and_addresses_are_redacted_next_to_hyphens_and_hangul(
    text: str, rule: str
) -> None:
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages

    prepared = prepare_model_messages(({"role": "user", "content": text},))

    assert prepared.receipt.redaction_rules == (rule,)


@pytest.mark.parametrize(
    ("utterance", "identifier", "masked"),
    (
        (
            "https://app.example.com/운영/callback?access_token=SECRETabc123 에러 원인",
            "https://app.example.com/운영/callback?access_token=SECRETabc123",
            "\u27e6ID1\u27e7 에러 원인",
        ),
        (
            _ID.replace("rg-app", "운영-rg") + "의 상태",
            _ID.replace("rg-app", "운영-rg"),
            "\u27e6ID1\u27e7의 상태",
        ),
        (
            "owner=alice@example.com 태그가 붙은 VM",
            "alice@example.com",
            "owner=\u27e6ID1\u27e7 태그가 붙은 VM",
        ),
    ),
)
def test_placeholders_hide_whole_values_and_release_only_trailing_particles(
    utterance: str, identifier: str, masked: str
) -> None:
    mask = IdentityMask(utterance, ())

    assert mask.utterance == masked
    assert "SECRET" not in mask.utterance
    unmasked = mask.unmask_form(
        {"mentions": [{"id": "m1", "span": {"text": "\u27e6ID1\u27e7", "occurrence": 1}}]}
    )
    assert unmasked["mentions"][0]["span"]["text"] == identifier


@pytest.mark.parametrize(
    "utterance",
    (
        '설정 {"password": "hunter2"} 이 왜 실패해?',
        '{"apiKey":"sk-live-Zq81"} 로 호출하면 401이 나와',
        "DB_PASSWORD=비밀번호 https://x.example.com/login 확인해줘",
    ),
)
async def test_a_secret_outside_every_placeholder_holds_the_form_call(utterance: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with pytest.raises(FormInputHeldError) as held:
        await _adapter(handler).propose_form(
            utterance=utterance, context=(), locale="ko", pass_index=0, prior_goals=()
        )

    assert held.value.reason == "input_redacted"
    assert requests == []


async def test_a_secret_inside_an_identifier_travels_only_inside_its_placeholder() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    for utterance in (
        "https://app.example.com/cb?access_token=SECRETabc123 에러 원인",
        "https://x.example.com/login?password=비밀번호 확인해줘",
    ):
        await _adapter(handler).propose_form(
            utterance=utterance, context=(), locale="ko", pass_index=0, prior_goals=()
        )

    assert len(sent) == 2
    assert "SECRETabc123" not in sent[0]
    assert "비밀번호" not in sent[1] and json.dumps("비")[1:-1] not in sent[1]


async def test_concept_selection_withholds_operator_text_with_a_secret() -> None:
    from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
    from fdai.core.conversation.semantic_reasoning_form import MentionDomain

    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    shard = ConceptShard(
        domain=MentionDomain.RESOURCE_TYPE,
        index=0,
        total=1,
        candidates=(),
        catalog_digest="sha256:" + "0" * 64,
    )
    await _adapter(handler).choose_concepts(
        utterance='설정 {"password": "hunter2"} VM 목록',
        mentions=({"mention": "m1", "text": "VM"},),
        shard=shard,
    )

    assert sent == []


@pytest.mark.parametrize("ending", ("은?", "는?", "과,"))
def test_a_particle_before_punctuation_is_released_from_the_placeholder(ending: str) -> None:
    mask = IdentityMask(f"그럼 {_ID}{ending} 알려줘", ())

    unmasked = mask.unmask_form(
        {"mentions": [{"id": "m1", "span": {"text": "\u27e6ID1\u27e7", "occurrence": 1}}]}
    )
    assert unmasked["mentions"][0]["span"]["text"] == _ID


@pytest.mark.parametrize(
    ("text", "secret"),
    (
        ("password: P@ss\\w0rd!", "w0rd"),
        ("DB password: \u201cHunter2x\u201d", "Hunter2x"),
        ("client_secret=abc123XYZ 가 맞아?", "abc123XYZ"),
        ("AZURE_CLIENT_SECRET=Q8x~abc123 설정 확인", "abc123"),
        ('"clientSecret": "abc~123"', "abc~123"),
        ("DB_PASSWORD=hunter2", "hunter2"),
        ("AccountKey=abc123== 로 연결 안돼", "abc123"),
        ('password: "[Zx9!q2]" 로그인 실패 원인은?', "Zx9"),
        ("token: {abc", "abc"),
        ("db_password={Tr0ub4dor&3", "Tr0ub4dor"),
        ('{\\"password\\": \\"hunter2\\"}', "hunter2"),
        ('password: "True-Love-2024"', "Love"),
        ("secret=False.Start.99", "Start"),
        ("config/password=hunter2", "hunter2"),
        ("api/v1/token=abc123", "abc123"),
        ('password: "true love forever"', "forever"),
        ("/etc/token=abc123", "abc123"),
        ("token=Bearer abc%2Fdef", "2Fdef"),
    ),
)
@pytest.mark.parametrize("ascii_only", (False, True))
def test_compound_and_escaped_secrets_are_redacted_in_encoded_payloads(
    text: str, secret: str, ascii_only: bool
) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages

    content = json.dumps({"utterance": text}, ensure_ascii=ascii_only)
    prepared = prepare_model_messages(({"role": "user", "content": content},))

    assert secret not in prepared.messages[0]["content"]
    assert secret not in redact_text(text)


@pytest.mark.parametrize(
    "text",
    (
        "max_tokens=2048 으로 설정",
        "tokens: 5",
        "pwd 명령",
        "암호화: AES 사용",
        "isSecret: true",
        '"hasPassword": false',
        "use_token: null",
        "/etc/passwd: permission denied",
        '"client_secret": {"ref": "kv"}',
        "token: [REDACTED]",
        "secret: true",
        "password: none",
    ),
)
def test_ordinary_words_near_secret_keys_are_not_redacted(text: str) -> None:
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages

    content = json.dumps({"utterance": text}, ensure_ascii=False)

    assert (
        prepare_model_messages(({"role": "user", "content": content},)).receipt.redaction_rules
        == ()
    )


@pytest.mark.parametrize(
    "utterance",
    (
        "https://x.example.com/profile?user=홍길동",
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/재무팀 비용은?",
        "first/last@example.com 확인",
    ),
)
def test_text_after_a_separator_stays_inside_the_placeholder(utterance: str) -> None:
    mask = IdentityMask(utterance, ())

    assert "홍길동" not in mask.utterance and "재무팀" not in mask.utterance
    assert "first/" not in mask.utterance


def test_a_secret_inside_a_masked_address_does_not_hold_the_call() -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert not _exposes_secret("https://a.blob.core.windows.net/c/f?sv=1&sig=abc. 만료됐어?")
    assert not _exposes_secret("https://x.example.com/?token=abc은 확인")
    assert _exposes_secret("DB_PASSWORD=hunter2 https://x.example.com")


@pytest.mark.parametrize(
    "text",
    (
        "a_" * 25000,
        "_" * 50000,
        "a-" * 25000,
        "a." * 25000,
        "password=" + "\\" * 50000,
        "password=" + "a\\" * 25000,
    ),
)
def test_redaction_stays_linear_on_long_identifier_like_runs(text: str) -> None:
    import time

    from fdai.delivery.azure.llm.input_detection import redact_text

    started = time.monotonic()
    redact_text(text)

    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize(
    ("utterance", "identifier"),
    (
        ("[포털](https://portal.example.com)에서 VM 상태 확인", "https://portal.example.com"),
        ("(https://example.com/health)을 호출하면 503", "https://example.com/health"),
        (f"`{_ID}`의 VM", _ID),
        ("**https://example.com/a**를", "https://example.com/a"),
    ),
)
def test_a_particle_after_a_closing_wrapper_is_released(utterance: str, identifier: str) -> None:
    mask = IdentityMask(utterance, ())

    unmasked = mask.unmask_form(
        {"mentions": [{"id": "m1", "span": {"text": "\u27e6ID1\u27e7", "occurrence": 1}}]}
    )
    assert unmasked["mentions"][0]["span"]["text"] == identifier


@pytest.mark.parametrize(
    ("utterance", "hidden"),
    (
        ("https://h.example.com/~홍길동 페이지", "홍길동"),
        ("https://h.example.com/a|김철수 확인", "김철수"),
        ("https://h.example.com/a*값 확인", "값"),
    ),
)
def test_a_path_character_that_opened_nothing_keeps_the_text_inside(
    utterance: str, hidden: str
) -> None:
    assert hidden not in IdentityMask(utterance, ()).utterance


@pytest.mark.parametrize(
    ("text", "secret"),
    (('"adminPassword": {"value": "S3cretX9"}', "S3cretX9"), ('"token": ["abc123zz"]', "abc123zz")),
)
def test_a_secret_inside_a_container_under_a_secret_key_is_held_and_redacted(
    text: str, secret: str
) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert _exposes_secret(text)
    assert secret not in redact_text(text)


def test_a_secret_tail_in_hangul_stays_inside_the_address_placeholder() -> None:
    mask = IdentityMask("https://h.example.com/?token=abc비밀 확인", ())

    assert mask.utterance == "\u27e6ID1\u27e7 확인"


def _long_values() -> tuple[tuple[str, str], ...]:
    signed = "eyJ" + "a" * 600 + "." + "b" * 700 + "." + "c" * 700
    return (
        (json.dumps({"access_token": signed + "TAILMARK"}), "TAILMARK"),
        ('token: "' + "x" * 700 + 'TAILMARK"', "TAILMARK"),
        ("client_secret='" + "y" * 900 + "TAILMARK'", "TAILMARK"),
        ('password: "it\'s-a-SECRETWORD"', "SECRETWORD"),
        *((f"password={shape}SHAPE9secret", "SHAPE9secret") for shape in ("[[", "{{", "[]", "[{")),
    )


@pytest.mark.parametrize(("text", "secret"), _long_values())
def test_long_quoted_and_bracketed_secret_values_are_redacted_whole(text: str, secret: str) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages

    content = json.dumps({"evidence": text}, ensure_ascii=False)
    prepared = prepare_model_messages(({"role": "user", "content": content},))

    assert secret not in prepared.messages[0]["content"]
    assert secret not in redact_text(text)


@pytest.mark.parametrize(
    ("text", "secret"),
    (
        (
            '"adminPassword": {'
            + ", ".join(f'"token{index}": []' for index in range(10))
            + ', "value": "NESTEDSECRET"}',
            "NESTEDSECRET",
        ),
        ('"token": ["a]b", "INNERSECRET"]', "INNERSECRET"),
        ('"token": {"v": "' + "z" * 5000 + 'LONGTAIL"}', "LONGTAIL"),
    ),
)
def test_container_secrets_are_bounded_by_structure_not_by_stray_brackets(
    text: str, secret: str
) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text

    assert secret not in redact_text(text)


@pytest.mark.parametrize("text", ('"secret": {"name": "kv-1"}', '"secret": []', '"token": {}'))
def test_a_reference_object_or_empty_container_is_not_a_secret(text: str) -> None:
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages

    content = json.dumps({"evidence": text}, ensure_ascii=False)

    assert (
        prepare_model_messages(({"role": "user", "content": content},)).receipt.redaction_rules
        == ()
    )


@pytest.mark.parametrize(
    ("text", "secret"),
    (
        ('"password": "[bracketed] rest of PASSPHRASE words"', "PASSPHRASE"),
        ('{"token": "Bearer abc\\\\u002bRESTOFTOKEN"}', "RESTOFTOKEN"),
        ("token=null\\\\u002bRESTNULL", "RESTNULL"),
        ('"password": "bearer SECONDWORD third"', "SECONDWORD"),
    ),
)
def test_escapes_after_literals_and_bracketed_passphrases_stay_redacted(
    text: str, secret: str
) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages

    content = json.dumps({"evidence": text}, ensure_ascii=False)

    assert (
        secret
        not in prepare_model_messages(({"role": "user", "content": content},)).messages[0][
            "content"
        ]
    )
    assert secret not in redact_text(text)


def test_raw_redaction_never_exposes_what_the_rules_remove() -> None:
    import random

    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.model_trace import _redact

    generator = random.Random(1573)  # noqa: S311 - deterministic test inputs, not secrets
    keys = ("password", "token", "client_secret", "adminPassword", "note", "value")
    pieces = ("[", "]", "{", "}", '"', "'", ": ", "=", " ", "abc", "SECRETX", "\\\\", "Bearer ")
    for _ in range(2000):
        text = generator.choice(keys) + "".join(generator.choice(pieces) for _ in range(8))
        ruled = _redact(text, max_chars=None)[0]
        if "SECRETX" not in ruled:
            assert "SECRETX" not in redact_text(text), text


@pytest.mark.parametrize("text", ("-" * 50000, "." * 50000, "=" * 50000))
def test_separator_runs_redact_quickly(text: str) -> None:
    import time

    from fdai.delivery.azure.llm.input_detection import redact_text

    started = time.monotonic()
    redact_text(text)

    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize(
    ("text", "secret"),
    (
        ("pwd=abc&token= SWALLOWED1", "SWALLOWED1"),
        ("passwd=x/token=\tSWALLOWED2", "SWALLOWED2"),
        ('password: "unclosed token=\nSWALLOWED3', "SWALLOWED3"),
        ('password: "abc token: "SWALLOWED4"', "SWALLOWED4"),
        ("db_pwd=a.token: SWALLOWED5", "SWALLOWED5"),
    ),
)
def test_a_value_that_swallowed_another_key_extends_over_that_keys_value(
    text: str, secret: str
) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.model_trace import _redact
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert secret not in _redact(text, max_chars=None)[0]
    assert secret not in redact_text(text)
    assert _exposes_secret(text)


@pytest.mark.parametrize(
    "text",
    (
        "token: [ 1, CONTAINERSECRET ]",
        "token: {a: CONTAINERSECRET}",
        "token: [[1], CONTAINERSECRET]",
    ),
)
def test_raw_redaction_replaces_containers_before_the_rules_see_them(text: str) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text

    assert "CONTAINERSECRET" not in redact_text(text)


@pytest.mark.parametrize("text", ('pwd="' * 12500, 'pwd=\\\\"' * 8000, 'pwd= "' * 8000))
def test_chained_swallowed_keys_redact_in_linear_time(text: str) -> None:
    import time

    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    started = time.monotonic()
    redact_text(text)
    _exposes_secret(text)

    assert time.monotonic() - started < 3.0


@pytest.mark.parametrize(
    ("text", "secret"),
    (
        ("AccountKey=abc\\\\nspring.datasource.password = SEPSECRET1", "SEPSECRET1"),
        ("client_secret=abc spring.datasource.password = SEPSECRET2", "SEPSECRET2"),
        ('"token": {"a": 1}\\\\npassword: "two words SECRET3"', "SECRET3"),
    ),
)
def test_a_key_after_a_swallowed_value_or_container_keeps_its_value_redacted(
    text: str, secret: str
) -> None:
    from fdai.delivery.azure.llm.input_detection import redact_text
    from fdai.delivery.azure.llm.model_trace import _redact

    assert secret not in _redact(text, max_chars=None)[0]
    assert secret not in redact_text(text)


@pytest.mark.parametrize(
    "text",
    (
        "header\\\\nBearer abcdefTOKEN",
        "x\\\\neyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxIn0" + ".c2lnbmF0dXJl",
        "Authorization: \\\\u0022Bearer abcTOKEN\\\\u0022",
        "토큰Bearer abcTOKEN",
        "{\\\\u0022password\\\\u0022: \\\\u0022two words\\\\u0022}",
    ),
)
def test_escaped_or_hangul_adjacent_secrets_hold_the_form_call(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert _exposes_secret(text)


@pytest.mark.parametrize("key", ("secret", "DB_PASSWORD", "apiKey", "AccountKey", "token"))
def test_an_empty_quoted_string_before_a_value_does_not_hide_it(key: str) -> None:
    from fdai.delivery.azure.llm.model_trace import _redact
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    text = key + "=''QZXMARKQZ'"

    assert "QZXMARKQZ" not in _redact(text, max_chars=None)[0]
    assert _exposes_secret(text)


def test_a_secret_revealed_only_by_decoding_escapes_always_holds() -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert _exposes_secret("https:\\u002f\\u002fh.example.com\\u002f?token\\u003dQZXMARKQZ")


def test_a_secret_value_made_of_trailing_punctuation_stays_inside_the_placeholder() -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    utterance = "https://h.example.com/?token=!!!.."

    assert not _exposes_secret(utterance)
    assert IdentityMask(utterance, ()).utterance == "\u27e6ID1\u27e7"


def test_many_addresses_with_secret_queries_are_checked_in_linear_time() -> None:
    import time

    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    utterance = " ".join(f"https://h{index}.example.com/?token=v{index}" for index in range(1500))
    started = time.monotonic()

    assert not _exposes_secret(utterance)
    assert time.monotonic() - started < 2.0


_BACKSLASH = chr(92)


@pytest.mark.parametrize(
    "text",
    (
        "pa" + _BACKSLASH * 2 + "u0073sword=QZXMARKQZ",
        "pa" + _BACKSLASH * 4 + "u0073sword=QZXMARKQZ",
        _BACKSLASH * 2 + "u0070assword=QZXMARKQZ",
        "pa" + _BACKSLASH + "ssword=QZXMARKQZ",
    ),
)
def test_nested_escape_layers_hold_the_form_call_and_withhold_concept_text(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize(
    "text",
    (
        "What changed on vm-app-01 in the last 3 days?",
        "rg-app에 있는 VM은 몇 개야?",
        "C:" + _BACKSLASH + "Users" + _BACKSLASH + "app 로그 확인",
    ),
)
def test_ordinary_questions_are_neither_held_nor_withheld(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert not _exposes_secret(text)
    assert _concept_text(text) == text


@pytest.mark.parametrize("depth", (6, 7, 8, 16, 64, 128))
def test_escapes_nested_beyond_the_layer_bound_still_hold(depth: int) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    text = "pa" + _BACKSLASH * depth + "u0073sword=QZXMARKQZ"

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize(
    "text",
    (
        "pa" + _BACKSLASH + "x73sword=QZXMARKQZ",
        "pa" + _BACKSLASH + "U00000073sword=QZXMARKQZ",
        "pa" + _BACKSLASH * 3 + "x73sword=QZXMARKQZ",
        "p" + _BACKSLASH + "u0061" + _BACKSLASH * 2 + "x73sword=QZXMARKQZ",
    ),
)
def test_hexadecimal_and_long_code_point_escapes_are_decoded_for_detection(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize(
    "text",
    (_BACKSLASH * 50000, (_BACKSLASH + "u0041") * 8000, (_BACKSLASH * 7 + "u0041") * 5000),
)
def test_escape_decoding_for_detection_stays_fast(text: str) -> None:
    import time

    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    started = time.monotonic()
    _exposes_secret(text)
    _concept_text(text)

    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize(
    "text",
    (
        "pass\u200bword=QZXMARKQZ",
        "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44\uff1dQZXMARKQZ",
        "password\uff1dQZXMARKQZ",
        "%70assword=QZXMARKQZ",
        "&#112;assword=QZXMARKQZ",
        "pa" + _BACKSLASH + "ud835" + _BACKSLASH + "udc2csword=QZXMARKQZ",
        "x" * 70 + "_password=QZXMARKQZ",
        "credentials=QZXMARKQZ",
        "private_key=QZXMARKQZ",
        "connectionString=QZXMARKQZ",
        "Authorization: Basic QZXMARKQZ",
    ),
)
def test_alternate_encodings_long_keys_and_credential_categories_hold(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize(
    "text",
    (
        "basic setup questions",
        "Check the token count: 5",
        "\uff36\uff2d 목록을 보여줘",
        "vm-app-01의 CPU 사용률이 90% 넘었어?",
    ),
)
def test_ordinary_text_with_similar_characters_is_not_held(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert not _exposes_secret(text)
    assert _concept_text(text) == text


@pytest.mark.parametrize(
    "text",
    (
        "pass&#x200b;word=QZXMARKQZ",
        "pass%E2%80%8Bword=QZXMARKQZ",
        "&#xff50;assword=QZXMARKQZ",
        "%26%23112%3Bassword=QZXMARKQZ",
        "&#37;70assword=QZXMARKQZ",
        "%2570assword=QZXMARKQZ",
        "pa" + _BACKSLASH + "u0026#115;sword=QZXMARKQZ",
        "&amp;" * 20 + "#112;assword=QZXMARKQZ",
    ),
)
def test_composed_and_nested_encodings_are_canonicalized_to_a_fixed_point(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize(
    "text",
    ("CPU 90% 넘은 VM", "A&B 팀의 리소스", "50%OFF 이벤트 로그", "①번 VM 상태", "Tom &amp; Jerry"),
)
def test_ordinary_percent_ampersand_and_compatibility_text_is_not_held(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert not _exposes_secret(text)


def test_a_derived_variant_runs_to_its_own_fixed_point() -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    references = "".join(f"&#{ord(character)};" for character in "password")
    encoded = "".join(f"%{ord(character):02X}" for character in references)
    text = _BACKSLASH.join(encoded) + "=QZXMARKQZ"

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize("where", ("prior_goals", "repair"))
async def test_an_encoded_secret_in_any_other_payload_string_holds_the_form_call(
    where: str,
) -> None:
    from fdai.core.conversation.semantic_reasoning_repair import FormRepair

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    hidden = "%70assword=QZXMARKQZ"
    prior = ({"level": "instance", "note": hidden},) if where == "prior_goals" else ()
    repair = (
        FormRepair(previous={"mentions": [], "goals": [], "note": hidden}, violations=("x",))
        if where == "repair"
        else None
    )
    with pytest.raises(FormInputHeldError):
        await _adapter(handler).propose_form(
            utterance="List VMs",
            context=(),
            locale="en",
            pass_index=0,
            prior_goals=prior,
            repair=repair,
        )

    assert requests == []


@pytest.mark.parametrize(
    "text",
    (
        "client secret: QZXMARKQZ",
        "api key = QZXMARKQZ",
        "access key: QZXMARKQZ",
        "private key: QZXMARKQZ",
        "connection string: QZXMARKQZ",
        "shared access key=QZXMARKQZ",
    ),
)
def test_whitespace_separated_compound_keys_are_detected(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize(
    "text",
    (
        "API key rotation: done",
        "private key file location",
        "connection string format help",
        "the client secret expired yesterday?",
        "https://x.example.com/a%20b 확인",
    ),
)
def test_ordinary_mentions_of_compound_keys_and_escaped_urls_are_not_held(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert not _exposes_secret(text)


def test_an_identifier_visible_only_after_decoding_holds_both_calls() -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    text = (
        "https:"
        + _BACKSLASH
        + "u002f"
        + _BACKSLASH
        + "u002fhost.example.com"
        + _BACKSLASH
        + "u002fpath"
    )

    assert _exposes_secret(text)
    assert _concept_text(text) == "[REDACTED]"


async def test_a_catalog_string_that_decodes_to_a_secret_holds_the_concept_call() -> None:
    from fdai.core.conversation.semantic_reasoning_concepts import ConceptCandidate, ConceptShard
    from fdai.core.conversation.semantic_reasoning_form import MentionDomain

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    shard = ConceptShard(
        domain=MentionDomain.RESOURCE_TYPE,
        index=0,
        total=1,
        candidates=(
            ConceptCandidate(id="value:x", values=("x",), labels=("%70assword=QZXMARKQZ",)),
        ),
        catalog_digest="sha256:" + "0" * 64,
    )

    result = await _adapter(handler).choose_concepts(
        utterance="VM 목록", mentions=({"mention": "m1", "text": "VM"},), shard=shard
    )

    assert result is None
    assert requests == []


def test_an_encoded_duplicate_of_a_masked_identifier_still_holds() -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    address = "https://host.example.com/path"
    encoded = address.replace("/", _BACKSLASH + "u002f")
    text = f"{address} and {encoded}"

    assert _exposes_secret(text)
    assert _concept_text(text) == "[REDACTED]"


@pytest.mark.parametrize("where", ("prior_goals", "repair"))
async def test_an_encoded_identifier_in_another_payload_string_holds_the_form_call(
    where: str,
) -> None:
    from fdai.core.conversation.semantic_reasoning_repair import FormRepair

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    hidden = "https://host.example.com/path".replace("/", _BACKSLASH + "u002f")
    prior = ({"level": "instance", "note": hidden},) if where == "prior_goals" else ()
    repair = (
        FormRepair(previous={"mentions": [], "goals": [], "note": hidden}, violations=("x",))
        if where == "repair"
        else None
    )
    with pytest.raises(FormInputHeldError):
        await _adapter(handler).propose_form(
            utterance="List VMs",
            context=(),
            locale="en",
            pass_index=0,
            prior_goals=prior,
            repair=repair,
        )

    assert requests == []


async def test_only_the_most_recent_context_items_are_sent() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(json.loads(request.content)["messages"][1]["content"]))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    context = tuple(f"turn {index}" for index in range(12))
    await _adapter(handler).propose_form(
        utterance="List VMs", context=context, locale="en", pass_index=0, prior_goals=()
    )

    assert sent[0]["context"] == list(context[-8:])


@pytest.mark.parametrize("mark", ("\u0301", "\u0308", "\u20dd", "\u0327"))
def test_a_combining_mark_inside_a_key_does_not_hide_it(mark: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    text = f"pa{mark}ssword=QZXMARKQZ"

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in _concept_text(text)


@pytest.mark.parametrize(
    "text",
    (
        "café password rotation?",
        "naïve résumé 확인",
        "비밀번호를 변경하는 방법",
        "Crème brûlée VM 상태",
    ),
)
def test_accented_and_korean_prose_is_not_held(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _concept_text, _exposes_secret

    assert not _exposes_secret(text)
    assert _concept_text(text) == text


@pytest.mark.parametrize(
    "text",
    (
        "pa\u0903ssword=QZXMARKQZ",
        "pa\u093essword=QZXMARKQZ",
        "pass\x07word=QZXMARKQZ",
        "pass\x1fword=QZXMARKQZ",
    ),
)
async def test_spacing_marks_and_controls_inside_a_key_reach_no_request(text: str) -> None:
    from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
    from fdai.core.conversation.semantic_reasoning_form import MentionDomain

    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with pytest.raises(FormInputHeldError):
        await _adapter(handler).propose_form(
            utterance=text, context=(), locale="en", pass_index=0, prior_goals=()
        )
    shard = ConceptShard(
        domain=MentionDomain.RESOURCE_TYPE,
        index=0,
        total=1,
        candidates=(),
        catalog_digest="sha256:" + "0" * 64,
    )
    await _adapter(handler).choose_concepts(
        utterance=text, mentions=({"mention": "m1", "text": "VM"},), shard=shard
    )

    assert not any("QZXMARKQZ" in body for body in sent)


@pytest.mark.parametrize(
    "utterance",
    (
        "What changed on vm-app-01\nin the last 3 days?",
        "rg-app에 있는\tVM은 몇 개야?",
        "여러 줄\r\n질문입니다",
    ),
)
async def test_multiline_ordinary_questions_are_sent(utterance: str) -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    await _adapter(handler).propose_form(
        utterance=utterance, context=(), locale="ko", pass_index=0, prior_goals=()
    )

    assert len(sent) == 1


def _empty_shard() -> Any:
    from fdai.core.conversation.semantic_reasoning_concepts import ConceptShard
    from fdai.core.conversation.semantic_reasoning_form import MentionDomain

    return ConceptShard(
        domain=MentionDomain.RESOURCE_TYPE,
        index=0,
        total=1,
        candidates=(),
        catalog_digest="sha256:" + "0" * 64,
    )


@pytest.mark.parametrize(
    "text",
    (
        '[{"name": "DB_PASSWORD", "value": "QZXMARKQZ", "slotSetting": false}] 이 설정 왜 안돼?',
        '{"value": "QZXMARKQZ", "name": "db-secret"}',
        "- name: API_KEY\n  value: QZXMARKQZ",
        '{"parameters": {"adminPassword": {"value": "QZXMARKQZ"}}}',
    ),
)
async def test_a_record_labelling_a_sensitive_setting_reaches_no_request(text: str) -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with pytest.raises(FormInputHeldError):
        await _adapter(handler).propose_form(
            utterance=text, context=(), locale="ko", pass_index=0, prior_goals=()
        )
    concept = await _adapter(handler).choose_concepts(
        utterance=text, mentions=({"mention": "m1", "text": "VM"},), shard=_empty_shard()
    )

    assert concept is None
    assert sent == []


async def test_a_benign_record_is_still_sent() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    text = '{"name": "vm-app-01", "type": "compute.vm"} 상태는?'
    await _adapter(handler).propose_form(
        utterance=text, context=(), locale="ko", pass_index=0, prior_goals=()
    )
    await _adapter(handler).choose_concepts(
        utterance=text, mentions=({"mention": "m1", "text": "VM"},), shard=_empty_shard()
    )

    assert len(sent) == 2


@pytest.mark.parametrize(
    "text",
    (
        "{name: DB_PASSWORD, value: QZXMARKQZ}",
        "{name: dbPassword, value: QZXMARKQZ}",
        "name = CLIENT_SECRET value = QZXMARKQZ",
        "{'name': 'accessKey', 'value': 'QZXMARKQZ'}",
    ),
)
def test_flow_style_and_mixed_quoting_records_hold(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert _exposes_secret(text)


@pytest.mark.parametrize(
    "text",
    (
        '{"name": "tokenizer-settings", "value": "bpe"}',
        '{"name": "secretariat-report", "value": "x"}',
        '{"name": "passwordless-auth", "enabled": true}',
        '{"name": "pwdreset-policy", "value": "30d"}',
        '{"name": "db-secret"}',
        "- name: token-rotation-job\n  schedule: daily",
    ),
)
def test_benign_records_with_similar_labels_are_not_held(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert not _exposes_secret(text)


async def test_a_system_prompt_that_decodes_to_a_secret_holds_both_calls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    base = _adapter(handler)
    adapter = AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=base._config.candidates,
            form_system_prompt="Return the form. %70assword=QZXMARKQZ",
            concept_system_prompt="Choose concepts. %70assword=QZXMARKQZ",
        ),
    )

    with pytest.raises(FormInputHeldError):
        await adapter.propose_form(
            utterance="List VMs", context=(), locale="en", pass_index=0, prior_goals=()
        )
    concept = await adapter.choose_concepts(
        utterance="List VMs", mentions=({"mention": "m1", "text": "VM"},), shard=_empty_shard()
    )

    assert concept is None
    assert requests == []


@pytest.mark.parametrize(
    "text",
    (
        '{"dbPasswordValue": "QZXMARKQZ"}',
        '{"settingName": "DB_PASSWORD", "value": "QZXMARKQZ"}',
        '{"name": "dbPasswordPrimary", "value": "QZXMARKQZ"}',
    ),
)
def test_compound_field_and_label_names_hold(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert _exposes_secret(text)


@pytest.mark.parametrize(
    "text",
    (
        '[{"name": "DB_PASSWORD"}, {"name": "x", "value": "y"}]',
        "enableToken: yes",
        "requirePassword: on",
        '{"tokenCount": 5}',
        '{"secretName": "kv-1"}',
    ),
)
def test_benign_flags_counters_and_separate_records_are_neither_held_nor_redacted(
    text: str,
) -> None:
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    content = json.dumps({"evidence": text}, ensure_ascii=False)

    assert not _exposes_secret(text)
    assert (
        prepare_model_messages(({"role": "user", "content": content},)).receipt.redaction_rules
        == ()
    )


async def test_operator_text_with_a_multiword_secret_is_withheld_from_concepts_whole() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    result = await _adapter(handler).choose_concepts(
        utterance="password: correct horse QZXMARKQZ staple",
        mentions=({"mention": "m1", "text": "VM"},),
        shard=_empty_shard(),
    )

    assert result is None
    assert sent == []


@pytest.mark.parametrize(
    "text", ("db.password.value = QZXMARKQZ", "spring.datasource.password.plain: QZXMARKQZ")
)
def test_dotted_value_components_are_redacted_and_hold(text: str) -> None:
    from fdai.delivery.azure.llm.model_trace import prepare_model_messages
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    content = json.dumps({"evidence": text}, ensure_ascii=False)
    prepared = prepare_model_messages(({"role": "user", "content": content},))

    assert _exposes_secret(text)
    assert "QZXMARKQZ" not in prepared.messages[0]["content"]


@pytest.mark.parametrize(
    "text",
    (
        '{"name": "tokenRefreshEnabled", "value": true}',
        '{"name": "passwordMinLength", "value": 12}',
        '{"name": "secretName", "value": "kv-1"}',
        '{"name": "passwordPolicy", "value": "strong"}',
        "- name: TOKEN_TTL\n  value: 3600",
        '{"name": "DB_PASSWORD", "value": ""}',
    ),
)
def test_flag_counter_reference_and_empty_records_are_not_held(text: str) -> None:
    from fdai.delivery.azure.llm.semantic_question_form import _exposes_secret

    assert not _exposes_secret(text)


async def test_a_reviewed_catalog_shard_is_scanned_once_per_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fdai.delivery.azure.llm.semantic_question_form as adapter_module
    from fdai.core.conversation.semantic_reasoning_concepts import ConceptCandidate, ConceptShard
    from fdai.core.conversation.semantic_reasoning_form import MentionDomain

    scanned: list[str] = []
    original = adapter_module._hides_identity

    def counting(text: str) -> bool:
        scanned.append(text)
        return original(text)

    monkeypatch.setattr(adapter_module, "_hides_identity", counting)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    shard = ConceptShard(
        domain=MentionDomain.RESOURCE_TYPE,
        index=0,
        total=1,
        candidates=(
            ConceptCandidate(id="value:x", values=("x",), labels=("reviewed catalog label",)),
        ),
        catalog_digest="sha256:" + "0" * 64,
    )
    adapter = _adapter(handler)

    for _ in range(3):
        await adapter.choose_concepts(
            utterance="VM 목록", mentions=({"mention": "m1", "text": "VM"},), shard=shard
        )

    assert scanned.count("reviewed catalog label") == 1
