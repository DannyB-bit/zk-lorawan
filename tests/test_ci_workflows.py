"""Regression tests for the GitHub Actions build contract."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
STRICT = (ROOT / ".github/workflows/strict-verification.yml").read_text()
SBF_WORKFLOW = (ROOT / ".github/workflows/sbf-integration.yml").read_text()
SBF_SCRIPT = (ROOT / "scripts/test-sbf.sh").read_text()


class CiWorkflowContractTests(unittest.TestCase):
    def test_release_prover_is_built_before_workspace_tests(self):
        build = "cargo build --release -p zk-lorawan-groth16"
        self.assertIn(build, STRICT)
        self.assertLess(STRICT.index(build), STRICT.index("cargo test --workspace"))

    def test_native_prover_toolchain_supports_locked_icu_crates(self):
        match = re.search(r"cargo \+(\d+)\.(\d+)\.0 build -p zk-lorawan-groth16", SBF_SCRIPT)
        self.assertIsNotNone(match)
        version = tuple(map(int, match.groups()))
        self.assertGreaterEqual(version, (1, 83))
        toolchain = f"{version[0]}.{version[1]}.0"
        self.assertIn(f"rustup toolchain install {toolchain}", SBF_WORKFLOW)
        self.assertIn(f"prover-{version[0]}.{version[1]}", SBF_WORKFLOW)

    def test_actions_use_node24_supported_major_versions(self):
        for workflow in (STRICT, SBF_WORKFLOW):
            self.assertIn("uses: actions/checkout@v5", workflow)
            self.assertIn("uses: actions/setup-node@v5", workflow)
        self.assertIn("uses: actions/setup-python@v6", STRICT)


if __name__ == "__main__":
    unittest.main()
