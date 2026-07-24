"""Narrator translator + coordinator hook tests (Chunk 27)."""

from __future__ import annotations

import pytest

from fdai.core.conversation.narrator import (
    DeterministicKeywordNarrator,
    ToolSchema,
    default_tool_schemas,
    format_prompt_tool_list,
)


class TestDeterministicKeywordNarrator:
    def test_english_verb_keyword_returns_verb(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="please list_rules for storage",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "explore_catalog"
        )

    def test_korean_keyword_returns_english_verb(self) -> None:
        n = DeterministicKeywordNarrator()
        # Compound Korean phrase for "resource group list" MUST map to
        # `query_inventory resource-group` (longer keyword wins over
        # the plain "resource list" prefix).
        assert (
            n.translate(
                utterance="리소스 그룹 목록",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "query_inventory resource-group"
        )

    def test_korean_audit_keyword_maps_to_query_audit(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="최근 감사 로그 보여줘",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "query_audit"
        )

    def test_longer_keyword_wins_over_shorter(self) -> None:
        n = DeterministicKeywordNarrator()
        # Same principle stated positively: when a longer keyword is a
        # superstring of a shorter one, the narrator MUST return the
        # longer one so we never emit a narrower verb than intended.
        assert (
            n.translate(
                utterance=("프로젝트 리소스 그룹 목록 입니다"),
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "query_inventory resource-group"
        )

    def test_no_keyword_match_returns_none(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="hello there, what do you think?",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_empty_utterance_returns_none(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="   ",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_english_keyword_respects_word_boundaries(self) -> None:
        n = DeterministicKeywordNarrator()
        # `list_rules` MUST NOT trigger on `list_rules_deprecated`.
        result = n.translate(
            utterance="list_rules_deprecated please",
            tools=default_tool_schemas(),
            principal_role="reader",
        )
        assert result is None

    def test_empty_table_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 1 keyword"):
            DeterministicKeywordNarrator(table=[])

    def test_custom_table_supersedes_default(self) -> None:
        n = DeterministicKeywordNarrator(table=[("magic", "explore_catalog")])
        assert (
            n.translate(
                utterance="magic please",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "explore_catalog"
        )


class TestToolSchemaDefaults:
    def test_default_schemas_cover_every_known_verb(self) -> None:
        """Every shipped verb has a schema entry (drift-guard).

        A new verb in coordinator._VERB_PATTERNS MUST also land in
        `default_tool_schemas()` or the narrator prompt is stale.
        """
        from fdai.core.conversation.coordinator import _VERB_PATTERNS

        # tool_name is the target verb we route to; take the unique set.
        coordinator_tool_names = {tool for _pattern, tool in _VERB_PATTERNS}
        schema_tool_names = {s.tool_name for s in default_tool_schemas()}
        missing = coordinator_tool_names - schema_tool_names
        assert not missing, f"coordinator verbs missing from default_tool_schemas(): {missing}"

    def test_reader_prompt_hides_write_tools(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="reader")
        # Reader gets Reader-floor tools + activate_break_glass (Reader
        # floor per chat invariant 7). approve_hil / list_hil (Approver)
        # MUST NOT appear.
        assert "approve_hil" not in rendered
        assert "list_hil" not in rendered
        assert "explore_catalog" in rendered

    def test_approver_prompt_includes_write_tools(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="approver")
        assert "approve_hil" in rendered
        assert "list_hil" in rendered
        assert "explore_catalog" in rendered

    def test_owner_prompt_includes_everything(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="owner")
        for verb in ("explore_catalog", "approve_hil", "run_runbook", "activate_break_glass"):
            assert verb in rendered

    def test_unknown_role_defaults_to_reader_visibility(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="unknown-role")
        assert "approve_hil" not in rendered
        assert "explore_catalog" in rendered

    def test_tool_schema_is_frozen(self) -> None:
        schema = ToolSchema(
            verb="v",
            tool_name="t",
            argument_hint="",
            summary="s",
            rbac_floor="reader",
            side_effect_class="read",
        )
        with pytest.raises(AttributeError):
            schema.verb = "hijack"  # type: ignore[misc]


class TestCoordinatorNarratorHook:
    def _tools(self):  # type: ignore[no-untyped-def]
        from fdai.core.conversation import ExploreCatalogTool

        return [ExploreCatalogTool(rules=[], action_types=[])]

    def _session(self, role: str = "reader"):  # type: ignore[no-untyped-def]
        from fdai.core.conversation import (
            ConversationSession,
            Principal,
            Role,
        )

        return ConversationSession(
            session_id="s-1",
            principal=Principal(id="p-1", role=Role(role)),
            channel_id="cli",
            turns=[],
        )

    def _successful_tools(self):  # type: ignore[no-untyped-def]
        from fdai.core.conversation import Role, ToolResult

        class _SuccessfulTool:
            name = "explore_catalog"
            description = "Return a grounded synthetic catalog result."
            rbac_floor = Role.READER
            side_effect_class = "read"

            def call(self, *, arguments, principal):  # type: ignore[no-untyped-def]
                return ToolResult(
                    status="ok",
                    data={"rules": [{"id": "rule-example"}]},
                    preview="found rule-example",
                    evidence_refs=("rule-example",),
                )

        return [_SuccessfulTool()]

    def test_no_narrator_leaves_regex_behaviour_intact(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
        )

        coord = ConversationCoordinator(tools=self._tools())
        result = coord.handle_turn(session=self._session(), message="뭐가 있나")
        assert isinstance(result, AbstainResult)

    def test_narrator_hits_when_regex_misses(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            DeterministicKeywordNarrator,
            ToolResult,
            default_tool_schemas,
        )

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=DeterministicKeywordNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        # Korean utterance no regex would match; narrator translates it
        # via the "카탈로그" keyword to `explore_catalog`, coordinator
        # re-runs the regex, ExploreCatalogTool fires (tool call happens
        # regardless of whether the empty query succeeds - the point is
        # the narrator routed a Korean prompt into a tool dispatch).
        result = coord.handle_turn(
            session=self._session(),
            message="카탈로그에서 보여줘",
        )
        # Coordinator DID reach a tool (any status), not an abstain.
        assert isinstance(result, ToolResult)

    def test_narrator_returning_none_falls_through_to_abstain(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
        )

        class _NullNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=_NullNarrator(),
            narrator_tool_schemas=[],
        )
        result = coord.handle_turn(
            session=self._session(),
            message="이건 아무것도 안 맞는 말",
        )
        assert isinstance(result, AbstainResult)

    def test_narrator_clarifies_ambiguous_turn_without_calling_tool(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
            default_tool_schemas,
        )

        class _ClarifyingNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

            def clarify(  # type: ignore[no-untyped-def]
                self,
                *,
                utterance,
                tools,
                prior_turns,
                principal_role,
            ):
                assert utterance == "show me that one"
                assert {tool.tool_name for tool in tools} == {"explore_catalog"}
                assert prior_turns == ()
                assert principal_role == "reader"
                return "Which catalog subject should I search?"

        coord = ConversationCoordinator(
            tools=self._successful_tools(),
            narrator=_ClarifyingNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        session = self._session()

        result = coord.handle_turn(session=session, message="show me that one")

        assert isinstance(result, AbstainResult)
        assert result.reason == "Which catalog subject should I search?"
        assert all(turn.direction != "tool_call" for turn in session.turns)
        assert session.turns[-1].direction == "outbound"
        assert session.turns[-1].tier == "T1"

    def test_invalid_clarification_falls_back_to_deterministic_abstain(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
            default_tool_schemas,
        )

        class _InvalidClarifyingNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

            def clarify(self, **kwargs):  # type: ignore[no-untyped-def]
                return "Run inventory now.\nThen approve it."

        coord = ConversationCoordinator(
            tools=self._successful_tools(),
            narrator=_InvalidClarifyingNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )

        result = coord.handle_turn(session=self._session(), message="do it")

        assert isinstance(result, AbstainResult)
        assert result.reason == "no chat_t0 intent match; try one of the listed verbs"

    def test_narrator_error_falls_through_to_abstain(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
        )

        class _BoomNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                raise RuntimeError("network down")

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=_BoomNarrator(),
            narrator_tool_schemas=[],
        )
        result = coord.handle_turn(session=self._session(), message="아무런 입력")
        assert isinstance(result, AbstainResult)

    def test_narrator_translation_logged_as_system_turn(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            DeterministicKeywordNarrator,
            default_tool_schemas,
        )

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=DeterministicKeywordNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        session = self._session()
        coord.handle_turn(
            session=session,
            message="카탈로그에서 보여줘",
        )
        # Should have a system turn recording the narrator translation.
        system_turns = [t.content for t in session.turns if t.direction == "system"]
        assert any("narrator translated to:" in c for c in system_turns)

    def test_contextual_narrator_receives_only_prior_turns_for_follow_up(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            ToolResult,
            Turn,
            default_tool_schemas,
        )

        class _ContextualNarrator:
            def translate(self, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("legacy translate must not run")

            def translate_with_context(  # type: ignore[no-untyped-def]
                self,
                *,
                utterance,
                tools,
                prior_turns,
                principal_role,
            ):
                assert utterance == "show that catalog again"
                assert [turn.content for turn in prior_turns] == [
                    "explore_catalog storage",
                    "found storage rules",
                ]
                assert principal_role == "reader"
                return "explore_catalog storage"

        coordinator = ConversationCoordinator(
            tools=self._successful_tools(),
            narrator=_ContextualNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        session = self._session()
        session.append(
            Turn(turn_id="prior-in", direction="inbound", content="explore_catalog storage")
        )
        session.append(
            Turn(turn_id="prior-out", direction="outbound", content="found storage rules")
        )

        result = coordinator.handle_turn(session=session, message="show that catalog again")

        assert isinstance(result, ToolResult)
        assert result.data["rules"][0]["id"] == "rule-example"

    def test_contextual_narrator_cannot_invent_argument_absent_from_history(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
            Turn,
            default_tool_schemas,
        )

        class _InventingNarrator:
            def translate(self, **kwargs):  # type: ignore[no-untyped-def]
                raise AssertionError("legacy translate must not run")

            def translate_with_context(self, **kwargs):  # type: ignore[no-untyped-def]
                return "explore_catalog confidential"

        coordinator = ConversationCoordinator(
            tools=self._successful_tools(),
            narrator=_InventingNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        session = self._session()
        session.append(
            Turn(
                turn_id="prior-in",
                direction="inbound",
                content="explore_catalog storage",
            )
        )

        result = coordinator.handle_turn(session=session, message="show that again")

        assert isinstance(result, AbstainResult)

    def test_grounded_answer_narrator_renders_successful_tool_result(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            ToolResult,
            default_tool_schemas,
        )

        class _GroundedNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

            def render_answer(  # type: ignore[no-untyped-def]
                self,
                *,
                utterance,
                tool,
                result,
                answer_plan,
                prior_turns,
                principal_role,
            ):
                assert utterance == "explore_catalog storage"
                assert tool.tool_name == "explore_catalog"
                assert result.status == "ok"
                assert answer_plan.intent.value == "open_question"
                assert answer_plan.format.value == "prose"
                assert prior_turns == ()
                assert principal_role == "reader"
                return "I found the matching storage catalog entries. [rule-example]"

        coord = ConversationCoordinator(
            tools=self._successful_tools(),
            narrator=_GroundedNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        session = self._session()

        result = coord.handle_turn(
            session=session,
            message="explore_catalog storage",
        )

        assert isinstance(result, ToolResult)
        assert result.preview == "I found the matching storage catalog entries. [rule-example]"
        assert session.turns[-2].direction == "tool_result"
        assert session.turns[-1].direction == "outbound"
        assert session.turns[-1].tier == "T1"

    def test_grounded_answer_narrator_failure_preserves_deterministic_preview(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            ToolResult,
            default_tool_schemas,
        )

        class _FailingNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

            def render_answer(self, **kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("provider unavailable")

        coord = ConversationCoordinator(
            tools=self._successful_tools(),
            narrator=_FailingNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )

        result = coord.handle_turn(
            session=self._session(),
            message="explore_catalog storage",
        )

        assert isinstance(result, ToolResult)
        assert result.preview == "found rule-example"

    def test_grounded_answer_narrator_does_not_rewrite_tool_errors(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            ToolResult,
            default_tool_schemas,
        )

        class _RecordingNarrator:
            calls = 0

            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

            def render_answer(self, **kwargs):  # type: ignore[no-untyped-def]
                self.calls += 1
                return "must not render"

        narrator = _RecordingNarrator()
        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=narrator,
            narrator_tool_schemas=default_tool_schemas(),
        )

        result = coord.handle_turn(
            session=self._session(),
            message="explore_catalog",
        )

        assert isinstance(result, ToolResult)
        assert result.status == "error"
        assert narrator.calls == 0

    def test_grounded_answer_narrator_requires_every_evidence_reference(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            ToolResult,
            default_tool_schemas,
        )

        class _CitationDroppingNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

            def render_answer(self, **kwargs):  # type: ignore[no-untyped-def]
                return "I found a matching rule."

        coord = ConversationCoordinator(
            tools=self._successful_tools(),
            narrator=_CitationDroppingNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )

        result = coord.handle_turn(
            session=self._session(),
            message="explore_catalog storage",
        )

        assert isinstance(result, ToolResult)
        assert result.preview == "found rule-example"
