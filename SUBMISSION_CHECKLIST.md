# MAGOS Hermes Plugin Catalog — Submission Checklist

Source of requirements: NousResearch/hermes-agent plugin-catalog/README.md and 'Submitting to the Plugin Catalog' guide.

## Files
- Add only `plugin-catalog/magos.yaml` to the upstream Hermes repository PR.
- Use `PR_DESCRIPTION.md` as the text of the pull request (not as an extra file in upstream).
- Keep MAGOS source code in https://github.com/UlyssesLeoLee/MAGOS.

## Pinned source
- Repository: UlyssesLeoLee/MAGOS
- Source branch observed: main
- SHA verified during preparation: 071e9c6a75a10a59d4ca1252067c293ea0684257
- Version read from plugin.yaml: 1.0.5
- Verify this remains the desired source commit when creating the PR.
- Any subsequent version requires a new SHA-bump PR; a branch or tag is not accepted in `sha`.

## Before opening the PR
1. Clone/fetch MAGOS locally and check out the pinned SHA:
   git clone https://github.com/UlyssesLeoLee/MAGOS.git
   cd MAGOS
   git checkout 071e9c6a75a10a59d4ca1252067c293ea0684257
2. Run:
   hermes plugins validate . --install-deps
3. Resolve all failures. Read every caution warning.
4. Audit the pinned tree for prohibited self-updaters, Hermes core monkey-patching, credential-store reads, bundled binaries, and unattended bypasses.
5. Confirm security disclosures in PR_DESCRIPTION.md are accurate against the pinned source.
6. Fork NousResearch/hermes-agent, add plugin-catalog/magos.yaml and open a PR.

## Review risks / limitations
- The repository includes host-specific Claude Code hooks and optional MAGOS guard scripts. The Hermes plugin entrypoint currently registers skills only. Be explicit about this distinction in review.
- The guard stores audit metadata locally. Never claim 'no data retention' without distinguishing local records from telemetry.
- This submission leaves `requires_hermes` unset because a tested minimum compatible Hermes release has not been established. Add a tested SemVer minimum to both manifests if required by a feature or the reviewer.
- `image` is omitted intentionally: Hermes requires an optional 2:1 listing image, while the previous MAGOS icon is square.
- The YAML is prepared and structurally checked; official Hermes CLI validation and maintainer review are still required.
