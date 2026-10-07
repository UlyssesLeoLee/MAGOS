# package/branch-strategy

- Skill: `package`
- Feature: The root skill activates on branch-strategy requests and carries advisory branching-model guidance
- Result: **PASS**

## Expected behavior

- The root description names branch strategy / branching-model design or audit in English, Chinese, and Japanese, keeps the generic-explainer exclusion, and stays within 1-1024 characters.
- SKILL.md has a Branch Strategy section that is advisory (no rename, move, delete, or reconfigure) and links references/branch-strategy.md.
- SKILL.md hard stops forbid recommending a model without classifying the observed one, imposing a long-lived model, and asserting remote protection.
- references/branch-strategy.md defines observation, branch roles, model classification, the fit checklist, the default model, release/hotfix flow, protection, naming, strategy changes, and the report format; remote protection is reported unknown.
- reconnaissance.md, decision-matrix.md, pressure-tests.md, design-rationale.md, and both READMEs reference the new guidance.

## Contract checks

- PASS `SKILL.md`
- PASS `references/branch-strategy.md`
- PASS `references/reconnaissance.md`
- PASS `references/decision-matrix.md`
- PASS `references/pressure-tests.md`
- PASS `references/design-rationale.md`
- PASS `README.md`
- PASS `README.en.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
