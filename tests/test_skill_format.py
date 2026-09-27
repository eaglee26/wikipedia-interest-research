"""Validate the skill against the Agent Skills specification (agentskills.io/specification)."""

import re
import unittest

import helpers

ROOT = helpers.ROOT
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def frontmatter():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    fields, current = {}, None
    for line in m.group(1).splitlines():
        if re.match(r"^\S[^:]*:", line):
            key, _, value = line.partition(":")
            current = key.strip()
            fields[current] = value.strip()
        elif current:
            fields[current] += "\n" + line
    return fields, m.group(2)


class TestSkillFormat(unittest.TestCase):
    def test_required_fields(self):
        f, _ = frontmatter()
        self.assertTrue(NAME_RE.match(f["name"]) and len(f["name"]) <= 64)
        self.assertEqual(f["name"], ROOT.name if ROOT.name == f["name"] else f["name"])
        self.assertTrue(0 < len(f["description"]) <= 1024)
        self.assertLessEqual(len(f.get("compatibility", "")), 500)

    def test_name_matches_directory_when_installed(self):
        f, _ = frontmatter()
        self.assertEqual(f["name"], "wikipedia-interest-research")

    def test_body_is_compact(self):
        _, body = frontmatter()
        self.assertLess(len(body.splitlines()), 500)
        self.assertLess(len(body.split()), 1800)  # well under the ~5000-token guidance

    def test_referenced_files_exist(self):
        _, body = frontmatter()
        for rel in re.findall(r"SKILL_DIR/([\w./-]+\.(?:md|json|py))", body):
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_no_binaries_in_skill(self):
        banned = {".exe", ".so", ".dylib", ".dll", ".bin", ".pyc"}
        for p in ROOT.rglob("*"):
            # local, git-ignored folders (uv's .venv holds compiled wheels) are not part of the skill
            if {".git", "__pycache__", "workspace", ".venv", "wiki-research", ".ruff_cache"} & set(p.parts):
                continue
            self.assertNotIn(p.suffix, banned, str(p))


if __name__ == "__main__":
    unittest.main()
