import { lazy, Suspense, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { DialogHost } from "@/components/dialog";
import { bootAuth } from "@/lib/api";
import { savedCourses } from "@/lib/offline";
import { useMe } from "@/lib/useMe";
import { useAuth } from "@/stores/auth";

import { AdminLayout } from "./pages/admin/AdminLayout";
import { ForgotPassword, ResetPassword, VerifyEmail } from "./pages/PasswordReset";

// Each page loads on first visit — keeps the first download small on mobile networks.
const AdminProviders = lazy(() => import("./pages/admin/Providers"));
const AdminFeatures = lazy(() => import("./pages/admin/Features"));
const HomePage = lazy(() => import("./pages/Home"));
const Login = lazy(() => import("./pages/Login"));
const SsoCallback = lazy(() => import("./pages/SsoCallback"));
const MentorPage = lazy(() => import("./pages/Mentor"));
const CoursePage = lazy(() => import("./pages/learn/Course"));
const LessonPage = lazy(() => import("./pages/learn/Lesson"));
const LibraryPage = lazy(() => import("./pages/learn/Library"));
const DocumentsPage = lazy(() => import("./pages/docs/Documents"));
const LabHome = lazy(() => import("./pages/lab/LabHome"));
const CourseEditor = lazy(() => import("./pages/lab/CourseEditor"));
const CatalogPage = lazy(() => import("./pages/lab/Catalog"));
const SharePage = lazy(() => import("./pages/lab/SharePage"));
const GuestLinksPage = lazy(() => import("./pages/guests/GuestLinks"));
const GuestLandingPage = lazy(() => import("./pages/guests/GuestPublic"));
const GuestLessonPage = lazy(() => import("./pages/guests/GuestPublic").then((m) => ({ default: m.GuestLessonPage })));
const GuestRolePlayPage = lazy(() => import("./pages/guests/GuestPublic").then((m) => ({ default: m.GuestRolePlayPage })));
const GuestDonePage = lazy(() => import("./pages/guests/GuestPublic").then((m) => ({ default: m.GuestDonePage })));
const AdminCatalog = lazy(() => import("./pages/admin/Catalog"));
const RolePlayStudio = lazy(() => import("./pages/roleplay/Studio"));
const RolePlayPlayer = lazy(() => import("./pages/roleplay/Player"));
const PracticePage = lazy(() => import("./pages/learn/Practice"));
const OnboardingPage = lazy(() => import("./pages/Onboarding"));
const AchievementsPage = lazy(() => import("./pages/game/Achievements"));
const BossPage = lazy(() => import("./pages/game/Boss"));
const LeaderboardPage = lazy(() => import("./pages/game/Leaderboard"));
const PlanPage = lazy(() => import("./pages/game/Plan"));
const ShopPage = lazy(() => import("./pages/game/Shop"));
const MasteryPage = lazy(() => import("./pages/review/Mastery"));
const ReviewHub = lazy(() => import("./pages/review/ReviewHub"));
const PersonalizePage = lazy(() => import("./pages/Personalize"));
const Signup = lazy(() => import("./pages/Signup"));
const OrgsPage = lazy(() => import("./pages/orgs/Orgs"));
const JoinOrInvite = lazy(() => import("./pages/orgs/Orgs").then((m) => ({ default: m.JoinOrInvite })));
const Cockpit = lazy(() => import("./pages/orgs/Cockpit"));
const SurveysPage = lazy(() => import("./pages/orgs/Surveys"));
const PlansPage = lazy(() => import("./pages/billing/Plans"));
const AccountPage = lazy(() => import("./pages/account/Account"));
const LivePage = lazy(() => import("./pages/live/Live"));
const LiveRecap = lazy(() => import("./pages/live/LiveRecap"));
const Unsubscribe = lazy(() => import("./pages/account/Unsubscribe"));
const AdminSite = lazy(() => import("./pages/admin/SiteLegal"));
const AdminOverview = lazy(() => import("./pages/admin/Overview"));
const AdminEmail = lazy(() => import("./pages/admin/Email"));
const AdminSystem = lazy(() => import("./pages/admin/SystemCheck"));
const PrivacyPage = lazy(() => import("./pages/legal/Legal").then((m) => ({ default: m.PrivacyPage })));
const TermsPage = lazy(() => import("./pages/legal/Legal").then((m) => ({ default: m.TermsPage })));
const RefundsPage = lazy(() => import("./pages/legal/Legal").then((m) => ({ default: m.RefundsPage })));
const ContactPage = lazy(() => import("./pages/legal/Legal").then((m) => ({ default: m.ContactPage })));
const DpaPage = lazy(() => import("./pages/legal/Legal").then((m) => ({ default: m.DpaPage })));
const PublicSurveyPage = lazy(() => import("./pages/public/PublicSurvey"));
const VerifyPage = lazy(() => import("./pages/public/Verify"));
const CertificatesPage = lazy(() => import("./pages/credentials/Certificates"));
const GuardianPage = lazy(() => import("./pages/public/Guardian"));
const JoinCampaignPage = lazy(() => import("./pages/orgs/JoinLinks").then((m) => ({ default: m.JoinCampaignPage })));
const JoinReferralPage = lazy(() => import("./pages/orgs/JoinLinks").then((m) => ({ default: m.JoinReferralPage })));
const HelpPage = lazy(() => import("./pages/help/Help"));
const AdminSupport = lazy(() => import("./pages/admin/Support"));
const AdminCodes = lazy(() => import("./pages/admin/Codes"));
const ReviewPage = lazy(() => import("./pages/study/Review"));
const TodayPage = lazy(() => import("./pages/study/Today"));
const ProgressPage = lazy(() => import("./pages/study/Progress"));
const CheckpointsPage = lazy(() => import("./pages/study/Checkpoints"));
const BuddyInvitePage = lazy(() => import("./pages/study/BuddyInvite"));
const SkillsPage = lazy(() => import("./pages/paths/Skills"));
const PathsPage = lazy(() => import("./pages/paths/Paths"));
const CareersPage = lazy(() => import("./pages/paths/Careers"));
const CareerPlanPrintPage = lazy(() => import("./pages/paths/CareerPlanPrint"));
const MyJourneyPage = lazy(() => import("./pages/journeys/MyJourney"));
const OrgJourneysPage = lazy(() => import("./pages/journeys/OrgJourneys"));
const AdminPayments = lazy(() => import("./pages/admin/Payments"));
const ConnectPage = lazy(() => import("./pages/connect/Connect"));
const ConnectAuthorize = lazy(() => import("./pages/connect/Authorize"));
const AdminCalendarApps = lazy(() => import("./pages/admin/CalendarApps"));
const CalendarCallbackPage = lazy(() => import("./pages/study/CalendarCallback"));
const WorkshopsPage = lazy(() => import("./pages/workshops/Workshops"));
const WorkshopDetailPage = lazy(() => import("./pages/workshops/Detail"));
const WorkshopLobbyPage = lazy(() => import("./pages/workshops/Lobby"));
const OrgWorkshopLivePage = lazy(() => import("./pages/orgs/WorkshopLive"));
const WorkshopSessionPage = lazy(() => import("./pages/workshops/Session"));
const WorkshopResultPage = lazy(() => import("./pages/workshops/Result"));
const AdminWorkshops = lazy(() => import("./pages/admin/Workshops"));
const AdminUsers = lazy(() => import("./pages/admin/Users"));
const AdminOrgs = lazy(() => import("./pages/admin/Orgs"));
const AdminCertificates = lazy(() => import("./pages/admin/Certificates"));
const AdminRefunds = lazy(() => import("./pages/admin/Refunds"));
const AdminFamilyGroups = lazy(() => import("./pages/admin/FamilyGroups"));
const FamilyInvitePage = lazy(() => import("./pages/billing/FamilyInvite"));
const AdminStaff = lazy(() => import("./pages/admin/Staff"));


function RequireAuth() {
  const { t } = useTranslation();
  const access = useAuth((s) => s.access);
  const signedIn = useAuth((s) => s.signedIn);
  const ready = useAuth((s) => s.ready);
  const loc = useLocation();
  // Keep where the learner was heading (e.g. a class join link) so login can send them back.
  const next = loc.pathname !== "/" ? `?next=${encodeURIComponent(loc.pathname + loc.search)}` : "";
  if (!ready) return <div className="p-8 text-muted">…</div>;
  if (!access && signedIn && navigator.onLine && !Object.keys(savedCourses.list()).length) {
    // Still signed in, but the server couldn't be reached — don't throw the learner out to the login page.
    return (
      <div role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-3 p-8 text-center">
        <p className="font-display text-xl font-bold">{t("auth.offline")}</p>
        <button className="rounded-xl bg-accent px-4 py-2 font-semibold text-accent-ink" onClick={() => void bootAuth([800, 1500])}>{t("common.retry")}</button>
      </div>
    );
  }
  // Signed in but no token here means offline (or server unreachable with saved lessons): run on cached data.
  return access || signedIn ? <Outlet /> : <Navigate to={`/login${next}`} replace />;
}

function RequireCreator({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading } = useMe();
  if (isLoading) return null;
  return me?.can_author ? <>{children}</> : <Navigate to="/" replace />;
}

function GuestOnly() {
  const access = useAuth((s) => s.access);
  const ready = useAuth((s) => s.ready);
  // The router's location, not window.location: right after sign-in the login page navigates to `next`, and
  // window.location already shows the new URL (no ?next) while this still renders once — that sent people to "/".
  const { search } = useLocation();
  if (!ready) return null;
  const next = new URLSearchParams(search).get("next");
  const safe = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  return access ? <Navigate to={safe} replace /> : <Outlet />;
}

export default function App() {
  useEffect(() => {
    void bootAuth();
  }, []);
  return (
    <Suspense fallback={<div className="p-8 text-muted">…</div>}>
    <DialogHost />
    <Routes>
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
      </Route>
      <Route path="/verify-email" element={<VerifyEmail />} />
      <Route path="/sso/callback" element={<SsoCallback />} />
      <Route path="/s/:token" element={<SharePage />} />
      <Route path="/g/:slug" element={<GuestLandingPage />} />
      <Route path="/g/:slug/lesson/:id" element={<GuestLessonPage />} />
      <Route path="/g/:slug/role-play" element={<GuestRolePlayPage />} />
      <Route path="/g/:slug/done" element={<GuestDonePage />} />
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/terms" element={<TermsPage />} />
      <Route path="/refunds" element={<RefundsPage />} />
      <Route path="/contact" element={<ContactPage />} />
      <Route path="/dpa" element={<DpaPage />} />
      <Route path="/p/:token" element={<PublicSurveyPage />} />
      <Route path="/verify/:code" element={<VerifyPage />} />
      <Route path="/guardian/:token" element={<GuardianPage />} />
      <Route path="/unsubscribe" element={<Unsubscribe />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="/mentor" element={<MentorPage />} />
          <Route path="/mentor/:id" element={<MentorPage />} />
          <Route path="/personalize" element={<PersonalizePage />} />
          <Route path="/learn" element={<LibraryPage />} />
          <Route path="/learn/:id" element={<CoursePage />} />
          <Route path="/learn/:courseId/lesson/:lessonId" element={<LessonPage />} />
          <Route path="/learn/:courseId/lesson/:lessonId/practice" element={<PracticePage />} />
          <Route path="/review" element={<ReviewHub />} />
          <Route path="/learn/:courseId/boss/:sectionId" element={<BossPage />} />
          <Route path="/achievements" element={<AchievementsPage />} />
          <Route path="/shop" element={<ShopPage />} />
          <Route path="/leaderboard" element={<LeaderboardPage />} />
          <Route path="/plan" element={<PlanPage />} />
          <Route path="/calendar/callback/:provider" element={<CalendarCallbackPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:id" element={<DocumentsPage />} />
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/roleplay" element={<RolePlayStudio />} />
          <Route path="/roleplay/:id" element={<RolePlayPlayer />} />
          <Route path="/lab" element={<RequireCreator><LabHome /></RequireCreator>} />
          <Route path="/lab/:id" element={<RequireCreator><CourseEditor /></RequireCreator>} />
          <Route path="/today" element={<TodayPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/help/:slug" element={<HelpPage />} />
          <Route path="/progress" element={<ProgressPage />} />
          <Route path="/progress/review" element={<ReviewPage />} />
          <Route path="/checkpoints" element={<CheckpointsPage />} />
          <Route path="/buddy/:token" element={<BuddyInvitePage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/paths" element={<PathsPage />} />
          <Route path="/paths/:slug" element={<PathsPage />} />
          <Route path="/careers" element={<CareersPage />} />
          <Route path="/careers/:slug" element={<CareersPage />} />
          <Route path="/journey" element={<MyJourneyPage />} />
          <Route path="/org/:slug/journeys" element={<OrgJourneysPage />} />
          <Route path="/mastery" element={<MasteryPage />} />
          <Route path="/mastery/:id" element={<MasteryPage />} />
          <Route path="/orgs" element={<OrgsPage />} />
          <Route path="/org/:slug" element={<Cockpit />} />
          <Route path="/org/:slug/workshops/:runId/live" element={<OrgWorkshopLivePage />} />
          <Route path="/surveys" element={<SurveysPage />} />
          <Route path="/certificates" element={<CertificatesPage />} />
          <Route path="/guests" element={<GuestLinksPage />} />
          <Route path="/connect" element={<ConnectPage />} />
          <Route path="/plans" element={<PlansPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/live" element={<LivePage />} />
          <Route path="/live/:id" element={<LiveRecap />} />
          <Route path="/workshops" element={<WorkshopsPage />} />
          <Route path="/workshops/session/:id" element={<WorkshopSessionPage />} />
          <Route path="/workshops/session/:id/result" element={<WorkshopResultPage />} />
          <Route path="/workshops/:runId" element={<WorkshopDetailPage />} />
          <Route path="/workshops/:runId/lobby" element={<WorkshopLobbyPage />} />
          <Route path="/join/c/:token" element={<JoinCampaignPage />} />
          <Route path="/join/r/:code" element={<JoinReferralPage />} />
          <Route path="/join/:code" element={<JoinOrInvite mode="code" />} />
          <Route path="/invite/:token" element={<JoinOrInvite mode="invite" />} />
          <Route path="/family/:token" element={<FamilyInvitePage />} />
        </Route>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/careers/:slug/plan/print" element={<CareerPlanPrintPage />} />
        <Route path="/connect/authorize" element={<ConnectAuthorize />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="/admin/overview" replace />} />
          <Route path="overview" element={<AdminOverview />} />
          <Route path="system" element={<AdminSystem />} />
          <Route path="email" element={<AdminEmail />} />
          <Route path="providers" element={<AdminProviders />} />
          <Route path="features" element={<AdminFeatures />} />
          <Route path="catalog" element={<AdminCatalog />} />
          <Route path="payments" element={<AdminPayments />} />
          <Route path="calendar-apps" element={<AdminCalendarApps />} />
          <Route path="codes" element={<AdminCodes />} />
          <Route path="workshops" element={<AdminWorkshops />} />
          <Route path="support" element={<AdminSupport />} />
          <Route path="site" element={<AdminSite />} />
          <Route path="users" element={<AdminUsers />} />
          <Route path="orgs" element={<AdminOrgs />} />
          <Route path="certificates" element={<AdminCertificates />} />
          <Route path="refunds" element={<AdminRefunds />} />
          <Route path="families" element={<AdminFamilyGroups />} />
          <Route path="staff" element={<AdminStaff />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
  );
}
