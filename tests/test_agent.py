import tempfile
import unittest
from pathlib import Path

from basira_agent import BasiraAgent, TOOL_SPECS, Workspace, WorkspaceError, run_check


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def chat(self, model, messages, tools):
        self.requests.append({"model": model, "messages": messages, "tools": tools})
        return self.responses.pop(0)

    def tags(self):
        return ["qwen2.5-coder:7b"]


def tool_call(name, arguments):
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        }
    }


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "module.py").write_text("def answer():\n    return 41\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=do-not-read\n", encoding="utf-8")
        (self.root / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")
        self.workspace = Workspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_lists_and_reads_workspace_text_while_excluding_secrets_and_generated_files(self):
        files = self.workspace.list_files()
        self.assertIn("src/module.py", files)
        self.assertIn(".env.example", files)
        self.assertNotIn(".env", files)
        self.assertFalse(any("node_modules" in name for name in files))
        self.assertEqual(self.workspace.read_file("src/module.py"), "def answer():\n    return 41\n")
        with self.assertRaises(WorkspaceError):
            self.workspace.read_file(".env")

    def test_blocks_parent_traversal_and_symlink_escape(self):
        outside = self.root.parent / "outside-basira-test.txt"
        outside.write_text("private", encoding="utf-8")
        try:
            with self.assertRaises(WorkspaceError):
                self.workspace.read_file("../outside-basira-test.txt")
            link = self.root / "escape.txt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("This system does not permit creating test symlinks.")
            with self.assertRaises(WorkspaceError):
                self.workspace.read_file("escape.txt")
        finally:
            outside.unlink(missing_ok=True)

    def test_change_is_staged_until_explicit_apply(self):
        proposal = self.workspace.stage_change("src/module.py", "def answer():\n    return 42\n", "Correct the result")
        self.assertIn("-    return 41", proposal["diff"])
        self.assertEqual(self.workspace.read_file("src/module.py"), "def answer():\n    return 41\n")
        result = self.workspace.apply_change(proposal["id"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.workspace.read_file("src/module.py"), "def answer():\n    return 42\n")

    def test_stale_proposal_is_rejected_if_file_changes_before_apply(self):
        proposal = self.workspace.stage_change("src/module.py", "replacement\n", "test stale protection")
        (self.root / "src" / "module.py").write_text("manual edit\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "changed since"):
            self.workspace.apply_change(proposal["id"])
        self.assertEqual(self.workspace.read_file("src/module.py"), "manual edit\n")


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "README.md").write_text("# Example project\n", encoding="utf-8")
        self.workspace = Workspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_agent_runs_a_read_tool_then_returns_a_final_answer(self):
        client = FakeClient([
            tool_call("list_files", {"path": "."}),
            {"message": {"role": "assistant", "content": "The workspace contains README.md."}},
        ])
        agent = BasiraAgent(self.workspace, client=client)
        result = agent.run([], "Inspect the repository.")
        self.assertEqual(result["reply"], "The workspace contains README.md.")
        self.assertEqual(result["tool_log"][0]["summary"], "Listed 1 files")
        tool_messages = [m for m in client.requests[1]["messages"] if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("README.md", tool_messages[0]["content"])

    def test_agent_proposal_does_not_write_until_user_approval(self):
        client = FakeClient([
            tool_call("propose_file_change", {"path": "README.md", "content": "# Updated\n", "reason": "Clarify title"}),
            {"message": {"role": "assistant", "content": "I prepared a reviewable README change."}},
        ])
        result = BasiraAgent(self.workspace, client=client).run([], "Update the README title.")
        self.assertEqual(self.workspace.read_file("README.md"), "# Example project\n")
        self.assertTrue(result["proposals"][0]["id"])
        self.assertTrue(result["proposals"][0]["diff"])
        self.workspace.apply_change(result["proposals"][0]["id"])
        self.assertEqual(self.workspace.read_file("README.md"), "# Updated\n")

    def test_agent_does_not_expose_shell_or_apply_tools(self):
        names = {entry["function"]["name"] for entry in TOOL_SPECS}
        self.assertEqual(names, {"list_files", "read_file", "search_files", "propose_file_change"})
        self.assertNotIn("run_shell", names)

    def test_only_fixed_check_names_are_allowed(self):
        with self.assertRaisesRegex(WorkspaceError, "Choose one"):
            run_check(self.workspace, "rm -rf .")


if __name__ == "__main__":
    unittest.main()
