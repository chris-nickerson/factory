import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_machine  # noqa: E402
from fake_machine import use_machine  # noqa: E402
import harness  # noqa: E402
import roles  # noqa: E402

CLAUDE_WROTE = {"vendor": "anthropic", "description": "the hosting session (claude)"}
CODEX_WROTE = {"vendor": "openai", "description": "the hosting session (codex)"}


class RoleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        env = patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "FACTORY_STATE_DIR": str(self.root / "state"),
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def reviewer(self, **context):
        return roles.reviewer(roles.Policy(self.repo), **context)

    def simplifier(self, spec=None):
        binding = roles.simplifier(roles.Policy(self.repo), explicit=spec)
        return binding["harness"], binding["model"]

    def pair(self, **choices):
        pair = roles.consensus_pair(roles.Policy(self.repo), **choices)
        return [(b["harness"], b["model"], b["reductions"]) for b in pair.values()]

    def configure(self, text, project=False):
        path = self.repo / roles.PROJECT_FILE if project else roles.user_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_two_harnesses_keep_the_cross_vendor_pairing(self):
        use_machine(self, "codex", "claude")
        review = self.reviewer()
        self.assertEqual((review["harness"], review["model"]), ("codex", "gpt-9.2-astra"))
        self.assertEqual(self.simplifier(), ("claude", "opus"))
        self.assertEqual(
            self.pair(), [("codex", "gpt-9.2-sol", []), ("claude", "opus", [])]
        )

    def test_reviewer_avoids_the_vendor_that_last_wrote_the_change(self):
        use_machine(self, "codex", "claude")
        for writer, expected in ((CLAUDE_WROTE, "codex"), (CODEX_WROTE, "claude")):
            binding = self.reviewer(writer=writer)
            self.assertEqual((binding["harness"], binding["reductions"]), (expected, []))
        stated = self.reviewer(writer=CODEX_WROTE, explicit="codex")
        self.assertIn("shares a vendor with the hosting session", stated["reductions"][0])

    def test_one_harness_fills_every_role_and_names_what_it_costs(self):
        for name, writer, label in (
            ("claude", CLAUDE_WROTE, "Same-model"),
            ("codex", CODEX_WROTE, "Same-harness"),
        ):
            with self.subTest(name):
                use_machine(self, name)
                review = self.reviewer(writer=writer)
                self.assertEqual(review["harness"], name)
                self.assertEqual(len(review["reductions"]), 1)
                self.assertEqual(self.simplifier()[0], name)
                first, second = self.pair()
                self.assertEqual((first[0], first[2], second[0]), (name, [], name))
                self.assertTrue(second[2][0].startswith(label))

    def test_one_vendor_and_an_unknown_writer_leave_independence_unverified(self):
        use_machine(self, "codex")
        self.assertIn("unverified", self.reviewer()["reductions"][0])
        pinned = self.reviewer(explicit="codex:default")
        self.assertIn("unverified", pinned["reductions"][0])
        use_machine(self, "codex", "claude")
        self.assertEqual(self.reviewer()["reductions"], [])

    def test_unreadable_project_file_cannot_stop_a_run(self):
        use_machine(self, "codex")
        (self.repo / roles.PROJECT_FILE).write_bytes(b"[roles]\nreviewer = \"\xff\"\n")
        self.assertEqual(self.reviewer()["harness"], "codex")

    def test_report_names_the_login_a_chosen_harness_still_needs(self):
        use_machine(self, "codex", "claude")
        signed_out = fake_machine.harnesses("codex", "claude")
        signed_out["claude"].update(authenticated=False, available=False)
        self.configure('[roles]\nreviewer = "claude:default"\n')
        with patch.object(roles, "installed", lambda: signed_out):
            row = roles.report(roles.Policy(self.repo))["roles"]["reviewer"]
        self.assertEqual(row["status"], "SIGNED_OUT")
        self.assertIn("claude auth login", row["reason"])

    def test_no_harness_leaves_a_role_unfilled_with_a_next_step(self):
        use_machine(self)
        with self.assertRaisesRegex(roles.RoleError, "factory doctor"):
            self.reviewer()
        self.assertEqual(
            {row["status"] for row in roles.report(roles.Policy(self.repo))["roles"].values()},
            {"UNFILLED"},
        )

    def test_flag_beats_approved_project_beats_user(self):
        use_machine(self, "codex", "claude")
        self.configure('[roles]\nreviewer = "claude:opus"\n')
        self.configure('[roles]\nreviewer = "codex:sol"\n', project=True)
        roles.approve_project(self.repo)
        binding = self.reviewer()
        self.assertEqual(
            (binding["harness"], binding["model"], binding["source"]),
            ("codex", "gpt-9.2-sol", "project"),
        )
        flagged = self.reviewer(explicit="claude:fable")
        self.assertEqual((flagged["harness"], flagged["model"]), ("claude", "fable"))

    def test_project_settings_count_only_while_their_approval_matches(self):
        use_machine(self, "codex", "claude")
        self.configure('[roles]\nreviewer = "claude:opus"\n')
        self.configure('[roles]\nreviewer = "codex:sol"\n', project=True)
        self.assertEqual(self.reviewer()["harness"], "claude")
        note = roles.report(roles.Policy(self.repo))["configuration"]["note"]
        self.assertIn("factory roles --approve", note)
        roles.approve_project(self.repo)
        self.assertEqual(self.reviewer()["harness"], "codex")
        self.configure('[roles]\nreviewer = "codex:default"\n', project=True)
        self.assertEqual(self.reviewer()["harness"], "claude")

    def test_unapproved_project_mistake_cannot_stop_a_run(self):
        use_machine(self, "codex")
        self.configure('[roles]\nreviewr = "codex"\n', project=True)
        self.assertIn("reviewr", roles.report(roles.Policy(self.repo))["configuration"]["note"])
        self.assertEqual(self.reviewer()["harness"], "codex")
        with self.assertRaisesRegex(roles.RoleError, "reviewr"):
            roles.approve_project(self.repo)

    def test_model_follows_the_harness_it_was_written_for(self):
        use_machine(self, "codex", "claude")
        self.configure('[roles]\nsimplifier = "claude:sonnet"\n')
        self.assertEqual(self.simplifier(":frontier"), ("claude", "fable"))
        self.assertEqual(self.simplifier("claude"), ("claude", "sonnet"))
        self.assertEqual(self.simplifier("codex"), ("codex", "gpt-9.2-sol"))
        self.configure('[roles]\nsimplifier = ":frontier"\n')
        self.assertEqual(self.simplifier("codex"), ("codex", "gpt-9.2-astra"))

    def test_model_written_alone_yields_when_a_later_layer_picks_the_harness(self):
        use_machine(self, "codex", "claude")
        self.configure('[roles]\nsimplifier = ":sonnet"\n')
        self.assertEqual(self.simplifier(), ("claude", "sonnet"))
        self.assertEqual(self.simplifier("codex"), ("codex", "gpt-9.2-sol"))
        self.assertEqual(self.simplifier(":haiku"), ("claude", "haiku"))

    def test_user_can_change_the_family_behind_a_tier(self):
        use_machine(self, "codex", "claude")
        self.configure('[models.claude]\nstandard = "sonnet"\n')
        self.assertEqual(self.simplifier(), ("claude", "sonnet"))

    def test_role_requires_the_capabilities_it_names(self):
        class ReadOnly(harness.Codex):
            name = "reader"
            vendor = "elsewhere"
            capabilities = frozenset({"read_only", "resume"})

        with patch.dict(harness.ADAPTERS, {"reader": ReadOnly}):
            use_machine(self, "reader")
            self.assertEqual(self.reviewer(explicit="reader:default")["harness"], "reader")
            with self.assertRaisesRegex(roles.RoleError, "edit, sandboxed_shell"):
                self.simplifier("reader")
            with self.assertRaisesRegex(roles.RoleError, "No installed"):
                self.simplifier()

    def test_codex_family_resolves_through_the_catalog(self):
        use_machine(self, "codex")
        model = lambda spec: self.reviewer(explicit=spec)["model"]  # noqa: E731
        self.assertEqual(model("codex:astra"), "gpt-9.2-astra")
        self.assertEqual(model("codex:gpt-9.1-astra"), "gpt-9.1-astra")
        self.assertEqual(model("codex:o9"), "o9")
        self.assertEqual(model("codex:luna"), "gpt-9-luna")
        with self.assertRaisesRegex(roles.RoleError, "'high' family"):
            model("codex:high")

    def test_default_tier_falls_back_when_the_catalog_lacks_its_family(self):
        use_machine(self, "codex", catalog=[fake_machine.UNHYPHENATED])
        fallback = self.reviewer(writer=CLAUDE_WROTE)
        self.assertIsNone(fallback["model"])
        self.assertIn("harness default model", fallback["reductions"][0])
        with self.assertRaisesRegex(roles.RoleError, "codex:default"):
            self.reviewer(explicit=":frontier")

    def test_codex_without_a_catalog_still_takes_a_complete_name_or_its_default(self):
        use_machine(self, "codex", catalog=None)
        self.assertIsNone(self.reviewer(explicit="codex:default")["model"])
        self.assertEqual(self.reviewer(explicit="codex:gpt-x")["model"], "gpt-x")
        self.assertEqual(self.reviewer(explicit="codex:o9")["model"], "o9")
        with self.assertRaisesRegex(roles.RoleError, "codex:default"):
            self.reviewer(explicit=":frontier")
        fallback = self.reviewer(writer=CLAUDE_WROTE)
        self.assertIsNone(fallback["model"])
        self.assertIn("harness default model", fallback["reductions"][0])

    def test_consensus_participants_move_apart_when_one_is_chosen(self):
        use_machine(self, "codex", "claude")
        self.assertEqual(
            [p[:2] for p in self.pair(b="codex")],
            [("claude", "opus"), ("codex", "gpt-9.2-sol")],
        )
        self.assertEqual(
            [p[:2] for p in self.pair(a=":frontier", b="codex")],
            [("claude", "fable"), ("codex", "gpt-9.2-sol")],
        )
        same = self.pair(a="claude:standard", b="claude:opus")
        self.assertIn("Same-model consensus", same[1][2][0])
        mixed = self.pair(a="claude:fable", b="claude:opus")
        self.assertIn("one vendor", mixed[1][2][0])

    def test_model_flags_from_before_roles_follow_their_harness(self):
        use_machine(self, "codex", "claude")
        models = {"codex": "gpt-9.1-astra", "claude": "sonnet"}
        self.assertEqual(
            [p[:2] for p in self.pair(a="claude", harness_models=models)],
            [("claude", "sonnet"), ("codex", "gpt-9.1-astra")],
        )
        with self.assertRaisesRegex(roles.RoleError, "no consensus participant"):
            self.pair(a="claude", b="claude", harness_models={"codex": "x"})

    def test_tier_option_sets_the_model_and_refuses_a_second_choice(self):
        self.assertEqual(roles.at_tier(None, "frontier"), ":frontier")
        self.assertEqual(roles.at_tier("codex", "frontier"), "codex:frontier")
        self.assertEqual(roles.at_tier("claude:opus", None), "claude:opus")
        with self.assertRaisesRegex(roles.RoleError, "Give one"):
            roles.at_tier("claude:opus", "frontier")

    def test_spec_and_configuration_errors_name_the_fix(self):
        for bad in ("", ":", "claude:", "gemini"):
            with self.subTest(bad), self.assertRaises(roles.RoleError):
                roles.parse_spec(bad)
        for text, named in (
            ('[roles]\nreviewr = "codex"\n', "reviewr"),
            ('[roles]\nreviewer = "gemini"\n', "gemini"),
            ('[models]\nclaude = "opus"\n', r"\[models.claude\]"),
            ('[models.claude]\nfrontir = "x"\n', r"\[models.claude\]"),
        ):
            with self.subTest(text):
                self.configure(text)
                with self.assertRaisesRegex(roles.RoleError, f"config.toml.*{named}"):
                    roles.Policy(self.repo)


class HostTests(unittest.TestCase):
    def host(self, environ, ancestors=()):
        return roles.detect_host(environ, list(ancestors))["harness"]

    def test_nearest_agent_process_decides_before_inherited_environment(self):
        nested = {"CLAUDECODE": "1", "CODEX_SHELL": "1"}
        self.assertEqual(self.host(nested, ["zsh", "claude", "zsh", "chatgpt"]), "claude")
        self.assertEqual(self.host(nested, ["zsh", "codex", "claude"]), "codex")
        ambiguous = roles.detect_host(nested, ["zsh"])
        self.assertIsNone(ambiguous["harness"])
        self.assertIn("ambiguous", ambiguous["evidence"])

    def test_environment_and_explicit_host(self):
        self.assertEqual(self.host({"CODEX_THREAD_ID": "t"}), "codex")
        self.assertEqual(self.host({"CLAUDECODE": "1"}), "claude")
        self.assertIsNone(self.host({}))
        self.assertEqual(self.host({"FACTORY_HOST": "codex", "CLAUDECODE": "1"}), "codex")
        self.assertIsNone(self.host({"FACTORY_HOST": "none", "CLAUDECODE": "1"}, ["claude"]))
        with self.assertRaises(roles.RoleError):
            self.host({"FACTORY_HOST": "gemini"})


if __name__ == "__main__":
    unittest.main()
