# Stellarium Desktop Rework Ledger

## Mission

Rework `apps/desktop` from the inherited Hermes presentation into a calm, dense, desktop-native **Stellarium Agent Studio** while preserving Hermes's proven agent, profile, provider, session, workspace, plugin, and recovery behavior.

The supplied `Stellarium-Agent-Studio.html` is a visual and interaction reference only. Its information hierarchy and operational intent may inform this implementation; its static mock data, demo-only interactions, and markup are not production sources.

## Non-negotiable constraints

- Preserve real runtime data and actions. No decorative metrics, fake agent state, or dead controls.
- Reuse the existing contribution, pane-tree, theme, provider onboarding, profile, and session systems rather than introducing a parallel architecture.
- Keep keyboard, screen-reader, reduced-motion, loading, empty, offline, and error states explicit.
- Use theme tokens and typed React components. Do not layer unscoped `!important` visual overrides over the Hermes UI.
- Keep the rework reviewable: focused files, behavior tests before implementation, and validation after every milestone.

## Experience model

| Layer | Purpose |
| --- | --- |
| Studio chrome | Establish product identity, global workspace context, navigation, and connection confidence. |
| Operational workspace | Keep the active session, agent state, model/provider, and working directory glanceable without wasting transcript space. |
| Conversation surface | Prioritize reading, steering, action visibility, and the composer; preserve the existing real streaming and tool workflow. |
| Secondary surfaces | Make sessions, projects, profiles, artifacts, skills, schedules, and settings discoverable but visually subordinate. |

## Delivery slices

- [x] Inspect the current desktop architecture, existing theme system, and the supplied reference.
- [x] Confirm the old global purple-glow override was reverted and must not be revived.
- [x] Establish a typed Studio header backed only by live session, workspace, provider, model, and gateway state.
- [x] Establish the Stellarium theme/token layer and product identity.
- [x] Rework the persistent navigation, fresh-session state, composer hierarchy, and operational chrome without replacing existing actions.
- [x] Add behavior tests for the new live-context header contract.
- [x] Run focused UI tests, typecheck, and production build.
- [ ] Complete a clean interactive renderer review in an isolated dev instance; the current native app is a pre-existing single-instance process and was intentionally not closed.
- [ ] Perform a final implementation review and record any actionable findings below.

### Implemented surfaces

- **Studio workspace header** — active session remains its existing action-menu trigger, while the real workspace basename, configured provider/model, and `Working` / `Ready` / `Offline` gateway state become glanceable. No fabricated run counts or health metrics.
- **Stellarium Studio skin** — a tokenized, default `stella` theme supplies light and dark palettes, terminal colours, typography, density, and an indigo signal colour. It remains selectable alongside imported/user skins rather than overriding them.
- **Operational hierarchy** — scoped CSS changes only layout hierarchy the token layer cannot express: rail separation, transcript canvas, composer focus treatment, responsive status suppression, and restrained elevation. No global `!important` skin.
- **Navigation and empty state** — the actual sidebar gains the Stellarium Agent Studio identity; the actual empty-chat wordmark/copy identifies the product as `STELLARIUM`. Existing nav, project, profile, session, drag-to-split, command, and provider flows remain the original real controls.

## Baseline evidence

- Git branch: `design`.
- Starting commit: `a470dc8839ef2e4b777b598404e1ce4314fd86d6` (`revert(desktop): rollback desktop UI and layout to authentic Hermes design`).
- Baseline typecheck and UI-test run started before edits; final outcome is recorded after the process completes.
- The source already contains a contribution-driven shell, pane layout, true session/project/profile data, themed tokens, accessibility primitives, and a substantial UI test suite. The rework will extend those seams rather than replace runtime behavior.

## Verification log

| Gate | Status | Evidence |
| --- | --- | --- |
| Behavior tests written before Studio header implementation | Passed | New test initially failed because `studio-workspace-header` did not exist; it now covers path labels and live working/offline state. |
| Typecheck | Passed | `npm run typecheck` exited 0 after the changes. |
| Focused UI test | Passed | `npx vitest run --project ui src/themes/presets.test.ts src/app/chat/studio-workspace-header.test.tsx`: **22 passed**. |
| Full UI suite | Blocked by unrelated failures | `npm run test:ui` was run without the invalid `--runInBand` flag and stopped after two existing failures: Markdown streaming property fuzz (`markdown-blocks.test.ts`, ~88 s) and transcript scrolling (`list-auto-show-earlier.test.tsx`, ~37 s); jsdom also lacks canvas `getContext`. Neither suite covers changed files. |
| Scoped lint | Passed with one existing warning | ESLint reported no errors in changed files; the `tailProfile` hook-dependency warning in `src/app/chat/index.tsx` predates this rework. |
| Repository-wide lint | Pre-existing failures | `src/app/profiles/hermes-migration-dialog.tsx` has six existing lint errors (unused imports / prop order), unrelated to this change. |
| Production build | Passed | `npm run build` exited 0: Vite bundle, Electron main/preload bundle, native-dependency stage, and `assert-dist-built` all completed. |
| Renderer source serve | Passed | The isolated Vite renderer served `/` and the updated `src/components/chat/intro.tsx` module containing `STELLARIUM`. |
| Interactive UI / keyboard review | Deferred safely | Electron's single-instance lock activated an already-open, pre-rework Stellarium process. It was not closed or altered; an attempted isolated user-data launch still honored that lock and was terminated. |
| Implementation review | Passed locally | `git diff --check`, TypeScript, focused UI tests, scoped lint, and production build were all reviewed after the final source edits. |

## Remaining gates

1. Run the full suite only after its unrelated Markdown, transcript-scroll, and canvas environment failures are repaired.
2. Launch a clean isolated native instance (without disturbing the user's running app) for final visual and keyboard/focus review.
3. Commit or otherwise submit the reviewed `design`-branch change set when Master approves.
