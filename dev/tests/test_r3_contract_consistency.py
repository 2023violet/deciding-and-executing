"""R3: prove high-value guarantees remain described consistently after future edits."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]

class TestContracts(unittest.TestCase):
    def test_plan_auxiliary_approval_fields_match_implementation(self):
        doc=(ROOT/'skills/deciding-and-executing/references/stage-2-plan.md').read_text(encoding='utf-8')
        code=(ROOT/'skills/deciding-and-executing/scripts/de.py').read_text(encoding='utf-8')
        self.assertIn('`if_then` / `first_step`',doc)
        self.assertIn(' | **是**', next(line for line in doc.splitlines() if line.startswith('| `if_then` / `first_step`')))
        self.assertIn('"if_then":',code)
        self.assertIn('"first_step":',code)
    def test_read_only_review_never_claims_acceptance(self):
        doc=(ROOT/'skills/deciding-and-executing/references/verification-strategy.md').read_text(encoding='utf-8')
        self.assertIn('不意味着通过',doc)
        code=(ROOT/'skills/deciding-and-executing/scripts/de.py').read_text(encoding='utf-8')
        self.assertIn('all_ready_for_review',code)
        self.assertIn('不等于用户验收通过',code)
    def test_main_skill_keeps_resource_discoverable(self):
        skill=(ROOT/'skills/deciding-and-executing/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('[references/verification-strategy.md](references/verification-strategy.md)',skill)
        self.assertIn('`preflight`',skill)
        self.assertIn('`coverage`',skill)

if __name__=='__main__': unittest.main()
