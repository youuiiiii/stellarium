# Stellarium Desktop Rework Ledger

## Mission

Rework `apps/desktop` from the inherited Hermes presentation into a calm, dense, desktop-native **Stellarium Agent Studio** while preserving Hermes's proven agent, profile, provider, session, workspace, plugin, and recovery behavior.

The supplied `Stellarium-Agent-Studio.html` is the **canonical visual and structural reference**. Port its desktop composition—global navigation rail, workspace/session sidebar, contextual conversation header, three-zone workspace, right-side dock, prominent composer, dense typography, spacing rhythm, and status strip—into the real renderer. Its static mock data, demo-only interactions, and markup are not production sources.

## Canonical-port priority

1. Port the reference's major composition and information architecture into real Hermes surfaces first.
2. Map existing sessions, projects, profiles, model/provider state, tools, artifacts, previews, and gateway status into those surfaces; do not invent mock dashboard content.
3. Treat secondary overlays and lifecycle refinements as follow-up work, never as a substitute for the rail/sidebar/workspace/right-dock port.

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

## Execution tracker — source of truth

**Legend:** `[x]` integrated and verified · `[~]` partially integrated · `[ ]` not started. This is an engineering execution ledger, not a release-note list. Work only advances from the first unfinished phase; a later checkbox may not be used as a substitute for an earlier structural one.

### A. Canonical target and mapping

| Canonical HTML zone | Real Stellarium source of truth | Port state |
| --- | --- | --- |
| Global header / command center | titlebar controls, command palette, gateway/model state | `[~]` context identity exists; full composition pass remains |
| Narrow global rail | app navigation, contributions, settings and surface routes | `[ ]` |
| Workspace/session sidebar | `ChatSidebar`, project tree, profile scope, session data | `[~]` real data is intact; reference hierarchy/layout remains |
| Central workbench | `ChatView`, transcript, session tiles, composer | `[~]` real header/composer states exist; canonical workspace composition remains |
| Right dock | pane tree, right sidebar, previews, artifacts, terminal | `[ ]` |
| Status strip | statusbar controls, gateway/update/system state | `[ ]` |

### B. Ordered implementation plan

1. `[x]` **Foundation:** inspect the actual renderer/reference; establish `stella` tokens, product identity, and real runtime context contracts.
2. `[ ]` **Shell composition (ACTIVE):** build the narrow global rail around existing routes; preserve navigation semantics and provide a clear sidebar-collapse relationship.
3. `[ ]` **Sidebar composition:** reshape `ChatSidebar` into the canonical workspace/session hierarchy while retaining projects, profiles, search, session drag/split, and all current actions.
4. `[ ]` **Workbench composition:** place contextual conversation header, transcript, real model controls, and prominent composer within the canonical central zone; retain multi-pane/tile behavior.
5. `[ ]` **Dock composition:** surface existing preview/artifact/terminal/inspection capabilities in the right dock, including genuine empty, loading, error, and narrow-window states.
6. `[ ]` **Chrome completion:** integrate the titlebar command center and compact real status strip with the completed zones.
7. `[ ]` **Secondary surfaces:** port provider/profile/onboarding/settings/artifacts/capabilities/schedules only after their parent zone is structurally complete.
8. `[ ]` **Visual and interaction acceptance:** responsive geometry, resizable pane behavior, focus order, keyboard use, reduced motion, interactive renderer pass, then full-suite disposition.

### C. Already-integrated supporting work

- `[x]` Live session selected/in-flight state (`selected` / `busy`).
- `[x]` Composer `working` / `ready` / `unavailable` state (`busy` / `disabled`).
- `[x]` Settings route frame plus project/worktree creation lifecycle states.
- `[x]` Session row density/state attributes (`density`, `unread`, `pinned`, `archived`) and section headers/date dividers.
- `[x]` Composer dock capsule layout and runtime state (`data-studio-composer-dock`, `layout`, `state`).

These supporting commits remain valid, but **they do not advance the active shell-composition phase.**

### D. Per-slice definition of done

- Real source mapping and existing actions preserved; no static mock content or duplicate controls.
- Focused behavior test(s), scoped lint, TypeScript, and `git diff --check` pass.
- Structural milestones additionally receive a production Electron build.
- Commit message and this ledger record the exact completed phase/sub-item and the next unfinished one.

### E. Known validation debt (not a reason to drift)

- Full UI suite remains blocked by pre-existing Markdown fuzz, transcript-scroll, and jsdom-canvas failures.
- A clean isolated native renderer/keyboard pass remains pending because the existing application instance must not be disturbed.

### Implemented surfaces

- **Studio workspace header** — active session remains its existing action-menu trigger, while the real workspace basename, configured provider/model, and `Working` / `Ready` / `Offline` gateway state become glanceable. No fabricated run counts or health metrics.
- **Stellarium Studio skin** — a tokenized, default `stella` theme supplies light and dark palettes, terminal colours, typography, density, and an indigo signal colour. It remains selectable alongside imported/user skins rather than overriding them.
- **Operational hierarchy** — scoped CSS changes only layout hierarchy the token layer cannot express: rail separation, transcript canvas, composer focus treatment, responsive status suppression, and restrained elevation. No global `!important` skin.
- **Navigation and empty state** — the actual sidebar gains the Stellarium Agent Studio identity; the actual empty-chat wordmark/copy identifies the product as `STELLARIUM`. Existing nav, project, profile, session, drag-to-split, command, and provider flows remain the original real controls.
- **Live session hierarchy treatment** — session rows now expose their genuine selected, in-flight, density (`compact`, `comfortable`, `detailed`, `card`), unread, pinned, and archived states to the Studio skin. Sidebar section headers and date dividers carry tokenized typography and hover affordances. Sorting, virtual list thresholds, and drag/split gestures remain untouched.
- **Composer dock capsule** — the actual composer dock container exposes its layout mode (`docked` vs `floating`) and tested runtime state (`working`, `ready`, `unavailable`). Studio styles center the floating capsule geometry (clamped to 900px max width matching the Studio specification) with subtle elevation and responsive padding.
- **Composer readiness treatment** — the actual composer now carries a tested `working` / `ready` / `unavailable` state derived from real `busy` and `disabled` inputs. Studio emphasizes active work at the dock boundary while preserving the existing stop, queue, steer, attachment, and accessibility controls.
- **Settings management frame** — the real settings overlay now carries a tested route-derived Studio identity. Configuration collapses into one calm management canvas; provider and credentials subviews remain distinct because they represent different live tasks. The existing deep links, narrow-screen dropdown, settings scope, search palette, import/export/reset, and all original actions remain unchanged.

## Baseline evidence

- Git branch: `design`.
- Starting commit: `a470dc8839ef2e4b777b598404e1ce4314fd86d6` (`revert(desktop): rollback desktop UI and layout to authentic Hermes design`).
- Baseline typecheck and UI-test run started before edits; final outcome is recorded after the process completes.
- The source already contains a contribution-driven shell, pane layout, true session/project/profile data, themed tokens, accessibility primitives, and a substantial UI test suite. The rework will extend those seams rather than replace runtime behavior.

## Verification log

| Gate | Status | Evidence |
| --- | --- | --- |
| Session row density & state behavior tests | Passed | Tested in `session-row.test.tsx` (14 passed) verifying `data-density`, `data-unread`, `data-pinned`, `data-archived`, `data-open-unfocused`. |
| Composer dock layout & state unit tests | Passed | Tested in `studio-state.test.ts` (4 passed) verifying `composerDockStudioState` resolution of docked/floating layout and working/ready/unavailable states. |
| Section header & date divider tests | Passed | Tested in `sessions-section.test.tsx` (3 passed) and `chrome.test.tsx` (2 passed) verifying `data-studio-session-section`, `data-studio-section-header`, and `data-studio-date-divider`. |
| Typecheck | Passed | `npm run typecheck` (`tsc -p . --noEmit && tsc -p tsconfig.electron.json --noEmit && tsc -p tsconfig.e2e.json --noEmit`) exited 0. |
| Scoped lint | Passed | `npx eslint` reported 0 errors and 0 warnings across all 9 touched files. |
| Production build | Passed | `vite build` completed successfully in 1m 48s with 0 errors. |
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
3. The reviewed foundation is committed as `2efa248ff5`; keep subsequent surface rework in reviewable commits on `design`.
