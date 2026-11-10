# Plan: Adaptive learning engine + enterprise admin console

## Context
Aasan generates a course once from `goal + level + notes` and the outline never changes; completion is "click Finish";
shared courses are identical for every learner. A learner model already exists (BKT `MasteryRecord`, FSRS reviews,
`Placement`, fast-track, pulse checks, checkpoints) but nothing feeds back into the path. The owner wants a Schole-class
*adaptive* platform: Kili learns the goal and prior knowledge, builds a goal-directed course, and re-plans as the learner
performs — while staying strict about reaching the goal. The admin console (11 sections, `is_staff` only) lacks user,
org, certificate and refund management, has no audit log, and certificates cannot be customised.

Decisions taken with the owner: build adaptive engine first, then admin console; security hardening (MFA, SSO,
sessions, hardening pass) is a **later round**. Intake = conversation + short diagnostic; a learner may enter only a
topic — the system suggests real-life scenarios, and a typed use case is verified before the course is built. Re-planning = remaining
items only, goal fixed. Visible skill map. Per-learner path over shared/org outlines too. Staff roles
superadmin/support/finance/content. Certificate template designer (layout, logo, signature, signatory, colours,
wording per kind + language, live preview).

Design walkthrough (Priya example) was presented and approved. First implementation step: save that design to
`docs/superpowers/specs/2026-10-19-adaptive-learning-admin-design.md` and commit it.

---

## Part A — Adaptive learning engine (new app `api/apps/adaptive/`)

### A1. Models + migration
`apps/adaptive/models.py`:
- `Concept(curriculum FK, key slug, title, description, order, critical bool)` — unique (curriculum, key).
- `ConceptEdge(prereq FK Concept, concept FK Concept)`.
- `Subsection.concepts` M2M (add on `learning.Subsection` via `adaptive` through-model to avoid touching learning migrations heavily).
- `ConceptMastery(user, concept, p_known float default 0.2, observations int, updated_at)` unique (user, concept).
- `LearningGoal(user, curriculum OneToOne, outcome, context, prior list, constraints JSON{no_code, hours_week, deadline}, transcript JSON)`.
- `LearnerPath(user, curriculum, version int, replanned_at, reason)` unique (user, curriculum).
- `PathItem(path FK, order, kind: lesson|skip_check|remediation|checkpoint|final, subsection FK null, concept FK null, status: pending|active|done|skipped, reason str, payload JSON)`.
- `Diagnostic(user, curriculum, items JSON, answers JSON, result JSON, created_at)` — reuses `paths.Placement` item format.
Keep `review.MasteryRecord` writing in place (compat); `ConceptMastery` is the new source of truth. Data migration maps existing lessons → one concept each so existing courses get a trivial graph.

### A2. Concept graph extraction
`apps/adaptive/graph.py` + prompt `llm/prompts/adaptive.py::GRAPH_SYSTEM` (task `author`): from outline + `LearningGoal` → 10–25 concepts with prereq edges, `critical` flag (on the path to the outcome), and lesson→concept mapping. Called inside `learning/services.py::_generate_outline` after sections are stored (personal courses) and lazily on first enrolment for shared courses (`ensure_graph(curriculum)`), idempotent. Validate DAG (reject cycles → drop offending edge, log).

### A3. Goal interview (topic-first, scenarios suggested) + diagnostic
Learners often know only a topic ("AI"), not a goal. The interview never demands one:
1. **Topic in** → `POST /api/adaptive/interview/start/` with `{topic}`. Kili asks at most one context question
   (who are you / what do you do), using `AboutMe`/profile if already known.
2. **Scenario suggestions** → `SCENARIO_SUGGEST_SYSTEM` returns 3–4 concrete, real-life use cases for *this* learner
   (e.g. topic "AI" + shop owner → "AI chatbot that answers WhatsApp orders", "Stock forecasting from your Excel
   sheet", "Write product descriptions in Tamil + English", "Just understand AI basics first"). Each card: title,
   what you'll build, time estimate, level. The last option is always a pure foundations track.
3. **Learner picks a card or types their own use case.** A typed use case goes through `SCENARIO_VERIFY_SYSTEM`:
   on-topic? feasible with the platform's activity types (no hardware, no paid APIs the learner lacks)? too broad
   (→ split into 2–3 narrower suggestions) or too narrow (→ widen)? unsafe/out of scope (→ decline with reason)?
   Result is a verified `LearningGoal` or a follow-up suggestion list; loop at most twice, then fall back to the
   foundations track.
4. **Constraints** (1–2 turns): prior exposure (`prior`, `no_code`), hours/week, deadline. Skip any already known.
5. Output structured `LearningGoal` via `llm/structured.py`; `createCourse` is called with `goal_id`; outline + graph
   are built *from the verified scenario*, so the course is a build-toward-the-use-case path, not a topic survey.
Web: `NewCourseForm` becomes a 3-step sheet (topic → scenario cards → constraints); chat UI reuses Onboarding chat.
Models: `LearningGoal` gains `topic`, `scenario` JSON (title, deliverable, suggested bool, verified bool, verify_notes).
Tests: topic-only path yields cards; custom use case accepted / split / declined; foundations fallback.

- `Diagnostic`:
- `POST /api/adaptive/courses/<id>/diagnostic/` builds 6–8 items selecting concepts with highest uncertainty (p≈0.5) spread across graph depth; reuse checkpoint item generation (`apps/study/checkpoints.py`) tagging each item with a concept. `POST .../diagnostic/answer/` grades (existing `GRADE_SYSTEM` path / MCQ keys) and seeds `ConceptMastery` via `bkt_update` (`apps/review/scheduling.py:137`) with strong prior weight.

### A4. Planner (pure, unit-tested)
`apps/adaptive/planner.py::plan(graph, mastery, goal, outline, prefs) -> list[PathItemSpec]` and `replan(path)`:
- Topological order of concepts; lesson item per subsection whose concepts are not mastered.
- `p_known ≥ 0.85` for all of a lesson's concepts → `skip_check` item (3 harder Qs; reuse fast-track `apps/study/journey.py:301-500`).
- After a lesson/checkpoint, any concept `< 0.5` → `remediation` item (practice via `generate_practice` or short remedial lesson via `ADD_SECTION_SYSTEM`), inserted before the next dependant.
- `checkpoint` every 3 lessons; `final` at end.
- Time budget: estimated minutes (session_minutes × items) vs `hours_week × weeks_to_deadline` → drop non-critical concepts first, mark `reason`.
- `LearningPrefs.pace/difficulty` (`accounts/preferences.py:56`) adjust remediation threshold and item count.
- `replan` only rewrites items with status `pending`; bumps `version`, sets `reason` (learner-facing string).

### A5. Mastery-gated progression + feedback into mastery
- `learning/api.py::subsection_complete`: if lesson score < `pass_score()` (`credentials/services.py:22`) and no passed remediation → 409 with `{"remediation": item}` and `replan`. Keep an owner/author bypass.
- Write `ConceptMastery` from: `ActivityAttempt` (existing `_update_mastery` in `review/services.py`), tutor chunk scores (`learning/tutor.py`), fast-track pass, roleplay outcome.
- Signal: after any mastery write → `replan` (debounced per path via cache key).
- `curriculum_detail` returns `path` (items in order) and `locked` derived from path, not raw order.

### A6. API + web
- `GET /api/adaptive/courses/<id>/path/`, `POST .../path/replan/`, `GET .../skill-map/` (concepts, mastery, edges, critical path, ETA).
- Web (`web/src/lib/adaptive.ts`, `web/src/pages/learn/`): interview chat step reusing Onboarding chat UI; diagnostic screen reusing placement quiz UI; course page renders PathItems with kind badges and "Path updated — <reason>" banner (mascot `say`); `SkillMap.tsx` graph (extend mastery-graph in `review` pages); i18n strings in `en.ts` + `ta.ts`.
- Org/teacher reports (`apps/orgs`, `workshops/report.py`) unchanged: still keyed to syllabus; add per-learner "skipped/remediated" counts.

### A7. Generation uses learner state
`studio/context.py::generation_extras` adds: known concepts to skip, weak prerequisites to recap, goal outcome/context, `no_code` flag. `curriculum.py::outline_prompts/lesson_prompts` accept these. Certificates: `credentials/services.py::course_completed` also requires all critical concepts ≥ 0.8; `detail` gains mastery snapshot.

### A8. Tests
`tests/test_adaptive_planner.py` (pure planner: skip, remediation, budget trimming, replan immutability of started items), `test_adaptive_api.py` (interview → diagnostic → path → gated complete → replan, fake provider), `test_adaptive_shared.py` (two learners, one org course, different paths, same syllabus report), authz sweep allowlist updates.

---

## Part B — Admin console

### B1. Staff roles + audit log (`apps/accounts`)
- `StaffRole(user OneToOne, roles list: superadmin|support|finance|content)`; permission class `HasStaffRole(*roles)` in `apps/accounts/permissions.py`; superadmin implies all. `make_admin` → superadmin. `me` serializer exposes `staff_roles`.
- `AdminAuditLog(actor, action, target_type, target_id, diff JSON, ip, at)` + `@audited("action")` decorator for admin mutations; replace `IsAdminUser` section by section with role classes. `GET /api/admin/audit/` (superadmin), paged + filter.
- Web: `AdminLayout.SECTIONS` filtered by role; Audit page.

### B2. Users section
`apps/accounts/admin_api.py`: paged search (email/name/org), detail (profile, entitlements, orgs+roles, certificates, AI spend from `UsageCounter`, devices/extension tokens), actions: deactivate/reactivate, force-logout (`tokens.revoke_all_sessions`), grant plan (reuse `payments/grant/`), set creator, set staff roles (superadmin). Page `admin/Users.tsx`.

### B3. Organisations section
`apps/orgs/admin_api.py`: list (kind, members, seats paid `billing.services.seats_total` vs used, subscription status), detail (members by role, features, branding, DPA, workshop seats, certificates), actions: feature toggles (`orgs/extras.py::FEATURES`), seat limits, suspend/unsuspend (new `Organization.suspended_at`; `perms.require` blocks). Move `workshops/orgs` controls here. Page `admin/Orgs.tsx`.

### B4. Certificates section + template designer (`apps/credentials`)
- `GET /api/admin/certificates/` paged search, revoke, reissue (`services.issue` with new dedupe), counts.
- `CertificateTemplate(scope: platform|org FK null, kind, language, layout: classic|modern|minimal, logo (media), signature_image, signatory_name, signatory_title, colours JSON, wording JSON, active)`; resolution order org+kind+lang → org+kind → platform+kind+lang → platform default (current hard-coded values become the default row).
- `pdf.render(cert)` → `pdf.render(cert, template)`; three layout functions; Noto fonts unchanged. `POST /api/admin/certificate-templates/preview/` and org equivalent `POST /api/credentials/orgs/<slug>/template/preview/` return PDF for sample data.
- Shared React form `CertificateTemplateEditor.tsx` used by `admin/CertificateTemplates.tsx` and org settings.

### B5. Refunds, paging, exports, overview
- `billing.Refund(order, amount, reason, rp_refund_id, status, by)`; `POST /api/admin/payments/orders/<id>/refund/` via `razorpay.py`; webhook `refund.processed`; wire `run_cancel.refunds_due`.
- Add `?page=&q=` + `?format=csv` to orders, subscriptions, invoices, certificates, users, orgs (shared `admin_paging.py` helper).
- `providers/overview.py`: workshop enrolments/revenue, certificates issued, orgs by kind + seat usage, MRR/churn from `Subscription`, refunds.

### B6. Tests
Role matrix test (each section × each role), audit log written on each mutation, users/orgs/certificates endpoints, template resolution + PDF renders for ta/en, refund flow with `gateway` fixture, authz sweep update.

---

## Red-team fixes (applied; implementer must honour these)
1. **Concept tags on activities.** Lesson schema (`curriculum.py` lesson/practice prompts) and checkpoint items emit a
   `concept` key per activity; `Activity.payload["concept"]` + `Diagnostic.items[].concept`. `ConceptMastery` is
   updated per *activity concept*, not per lesson. Fallback: lesson's first concept.
2. **BKT discipline.** Only first attempts update `ConceptMastery` (mirror `subsection_complete` api.py:458);
   skip/remediation decisions require `observations ≥ 3`; diagnostic seeds with 2 pseudo-observations; thresholds
   (0.85 / 0.5) are unit-tested against `scheduling.py` constants (P_LEARN 0.15, P_SLIP 0.1) and adjusted if needed.
3. **Never mutate shared outlines.** Remediation = `generate_practice` on the existing subsection or generated content
   stored in `PathItem.payload`; `ADD_SECTION_SYSTEM` only for `kind == personal` courses owned by the learner.
4. **Skips count as done.** Passed `skip_check` writes `UserSubsectionState(COMPLETED, score=skip score)` so
   `course_completed`, org reports and badges keep working.
5. **Cost and re-plan gating.** `replan` runs only in `subsection_complete`, checkpoint submit, skip-check and
   remediation submit (not in `record_attempt`'s transaction). New usage tasks `adaptive_interview`,
   `adaptive_graph`, `adaptive_diag`; per-course AI cap setting `ADAPTIVE_COURSE_AI_UNITS`.
6. **Under-specified bits resolved.** `ConceptLink(subsection, concept)` plain model in `adaptive` (no learning
   migration). Diagnostic picks concepts by graph depth spread (root, mid, leaf) since all priors are equal. Per-item
   minutes = `authoring.preset.session_minutes` or 10. `replan` never touches `active` items; client sends
   `path_version`, server returns 409 on mismatch and the client refetches. Studio outline edits call
   `ensure_graph(force=True)` on the changed sections. B1 role map table written first (section → role).
7. **Deferred to v1.1:** time-budget trimming, `LearningPrefs` modulation, verify *loop* (v1 = single verify pass:
   accept / split / decline), SkillMap as graph (v1 = mastery list grouped by section with critical-path marker).

## Success criteria (measure before/after with the fake→real provider on a pilot cohort)
- Learning gain: `study/checkpoints.py:summary()` pre→post ≥ +10 pts vs non-adaptive courses.
- Completion rate per enrolment and certificate issuance rate not lower than today (mastery gating risk).
- First-attempt pass rate on remediated concepts rises after remediation.
- Re-plan churn `LearnerPath.version` < 1 per 3 lessons; skip-check pass rate 60–90% (else thresholds wrong).
- `LLMUsage` tokens per course by task; interview funnel topic → card → course (log to `LearningGoal.transcript`).

## Order of work
1. Commit design spec. 2. A1→A2→A4 (planner with tests) →A3→A5→A6→A7→A8. 3. B1→B2→B3→B4→B5→B6.
Each step: migrations, `ruff`, `pytest`, `pnpm lint && pnpm test && pnpm build`, commit on `feature/ai-workshops` (or a new `feature/adaptive-learning` branch — create it).

## Verification
- `cd api && uv run pytest` (SQLite) and the Postgres job locally if available; `uv run python manage.py makemigrations --check`.
- `cd web && pnpm lint && pnpm test && pnpm build`.
- Manual (fake provider): new course → interview → diagnostic → path shows a skip-check and lessons → fail a lesson → remediation inserted + banner → skill map updates → certificate blocked until critical concepts mastered.
- Admin: log in as superadmin/support/finance/content, confirm section visibility; edit a certificate template, preview PDF with Tamil name; revoke/reissue; refund a test order; audit page lists all of it.

---

## Implementation decisions (made while building, 2026-10-19)
- **Diagnostic reuses the course pre-checkpoint** (`apps/study/checkpoints.py`, 8 MCQs tagged by lesson title). No
  separate `Diagnostic` model: a submitted `pre` attempt seeds `ConceptMastery` (correct → p ≥ 0.9, wrong → p ≤ 0.15,
  2 observations each); a `post` attempt is observed like any graded answer and triggers a re-plan.
- **Skip-check reuses fast-track** (`apps/study/journey.py`). A pass already writes a COMPLETED
  `UserSubsectionState`, so certificates and org reports keep working (red-team fix 4).
- **Remediation reuses practice sets** (`generate_practice`, kind=`practice`). Done when the concept reaches 0.6 or
  after 8 first-attempt practice answers on that lesson. Shared outlines are never changed (red-team fix 3).
- **Activity → concept** is stored in `adaptive.ActivityConcept` (no change to `learning.Activity`). The lesson prompt
  is told the lesson's concept keys and each `FlatActivity` may carry `concept`; untagged activities fall back to the
  lesson's first concept.
- **Graphs:** courses generated after this change get an AI concept graph in the outline job; existing courses get a
  one-concept-per-lesson graph lazily (no AI, so a learner never triggers paid generation on a shared course).
- **Gating response:** `subsection_complete` on an adaptive course returns `200 {"passed": false, "remediation": …}`
  and leaves the lesson IN_PROGRESS, instead of a 409, so the existing client flow doesn't treat it as an error.
  Completing after remediation records `max(lesson score, practice score)` so certificates can be earned.
- Gating, path and the certificate concept check apply only where a `LearnerPath` exists for that learner and course.
