import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { LegalLinks } from "@/components/LegalLinks";
import { api } from "@/lib/api";
import { useSiteInfo, type SiteInfo } from "@/lib/legal";
import { Kili } from "@/mascot/Kili";

const H = ({ children }: { children: ReactNode }) => <h2 className="mt-8 font-display text-xl font-bold">{children}</h2>;
const fmtDate = (v: string) => new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });

function useBiz() {
  const { data } = useSiteInfo();
  const s = data ?? ({ brand: "Aasan", legal_name: "", address: "", city: "Chennai", support_email: "", phone: "", grievance_officer: "", grievance_email: "", gstin: "", refund_days: 7, terms_version: "" } as SiteInfo);
  return { ...s, entity: s.legal_name || s.brand, contact: s.grievance_email || s.support_email };
}

function LegalLayout({ title, children }: { title: string; children: ReactNode }) {
  const { t, i18n } = useTranslation();
  const s = useBiz();
  return (
    <div className="min-h-dvh bg-bg">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-2 font-display text-xl font-extrabold text-accent"><Kili mood="idle" size={36} /> {s.brand}</Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8 leading-relaxed [&_li]:mt-1 [&_p]:mt-3 [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-6">
        <h1 className="font-display text-3xl font-extrabold">{title}</h1>
        {s.terms_version && <p className="text-sm text-muted">{t("legal.effective", { date: fmtDate(s.terms_version) })}</p>}
        {!i18n.language.startsWith("en") && <p className="mt-3 rounded-xl bg-surface-2 px-3 py-2 text-sm">{t("legal.englishOnly")}</p>}
        {children}
      </main>
      <footer className="border-t border-line py-6"><LegalLinks /></footer>
    </div>
  );
}

function GrievanceBlock() {
  const s = useBiz();
  return (
    <ul>
      <li><b>Grievance Officer:</b> {s.grievance_officer || "to be appointed. Until then, write to the email below"}</li>
      {s.contact && <li><b>Email:</b> <a className="text-accent underline" href={`mailto:${s.contact}`}>{s.contact}</a></li>}
      {s.address && <li><b>Address:</b> {s.address}</li>}
      {s.phone && <li><b>Phone:</b> {s.phone}</li>}
    </ul>
  );
}

export function PrivacyPage() {
  const s = useBiz();
  return (
    <LegalLayout title="Privacy Policy">
      <p>This policy explains what personal data {s.brand} collects, why, who it is shared with and the choices you have. {s.entity} (“we”) is the Data Fiduciary for your data under India's Digital Personal Data Protection Act, 2023 (DPDP Act).</p>

      <H>1. What we collect</H>
      <ul>
        <li><b>Account details:</b> your name, email address, a securely hashed password (or your Google account ID if you sign in with Google), interface language and your age group (18+ or under 18). For learners under 18, we also collect a parent's or guardian's email.</li>
        <li><b>Learning data:</b> your goals and skills, the courses you create or join, your answers, scores, progress, mastery, XP, streaks and badges.</li>
        <li><b>Conversations:</b> messages you exchange with the AI mentor and in role-play practice.</li>
        <li><b>Files you upload:</b> notes and documents, and the text we extract from them so the mentor can answer questions about them.</li>
        <li><b>Voice:</b> when you use voice, your audio is sent to a speech-to-text service to turn it into text. We do not keep the recording. Only the resulting text is saved, as part of the conversation.</li>
        <li><b>Organization data:</b> if you join a school, college, coaching centre or company on {s.brand}, your membership, role, class and assignments, plus survey answers (anonymous surveys are stored without your name).</li>
        <li><b>Payments:</b> payments are handled by Razorpay. We never see or store your card, UPI or bank details. We keep the plan, amount, date, status and the Razorpay order and payment IDs.</li>
        <li><b>Technical data:</b> IP address and browser or device details in our server logs, for security and troubleshooting.</li>
      </ul>

      <H>2. Why we use it</H>
      <ul>
        <li>To run your account and personalise lessons, explanations, practice and reviews (based on your consent).</li>
        <li>To show your progress to you and, for courses an organization assigns to you, to your teachers.</li>
        <li>To process payments, send receipts and remind you before your plan ends.</li>
        <li>To keep the service safe, prevent abuse and enforce plan limits.</li>
        <li>To meet legal duties such as tax record-keeping (a legitimate use under Section 7 of the DPDP Act).</li>
      </ul>
      <p>We do not sell your data and we do not show ads.</p>

      <H>3. How AI is used</H>
      <p>To answer you, create courses, grade open answers and speak or listen, the relevant content (your message, recent conversation, learning profile and any document passages you asked about) is sent to the AI and speech providers we use. These may include Anthropic, OpenAI, Google, Sarvam AI and Deepgram, as configured by us (the current list is in our Data Processing Addendum). Live voice calls run on our own servers and are not recorded. They process it on our behalf, under their API terms, which, at the time of writing, do not permit them to train their models on this data. AI can make mistakes, so please check important facts.</p>

      <H>4. Who can see your data</H>
      <ul>
        <li><b>Service providers</b> who process data for us: AI and speech providers, Razorpay (payments), and our hosting and email providers. Some of these process data outside India.</li>
        <li><b>Your organization:</b> if you join one, its teachers and admins see your name, email, progress and scores <i>only for courses they assign</i>, plus non-anonymous survey answers. They never see your mentor chats, role-plays or uploaded notes.</li>
        <li><b>People you share with:</b> courses you publish with a link or in the catalog are visible to people you share them with.</li>
        <li><b>Authorities</b>, when the law requires it.</li>
      </ul>

      <H>5. Children (under 18)</H>
      <p>Learners under 18 may use {s.brand} only with the consent of a parent or lawful guardian. When an under-18 account is created we email the guardian a link to agree or refuse. Until the guardian agrees, the AI mentor, voice, role-play, workshops and document uploads stay switched off; lessons still work. We do not track children's behaviour for advertising, show them targeted ads, send them re-engagement or streak-pressure reminders, or learn their study habits for nudges. A guardian can change their answer from the same link, and can ask us at any time to access or delete the child's data.</p>

      <H>6. How long we keep data</H>
      <p>We keep your data while your account is active, with these limits: mentor conversations you haven't opened for 12 months, role-play transcripts older than 12 months, and generated speech audio older than 6 months are deleted automatically; AI usage records (counts only, no content) are kept about 13 months; workshop transcripts are kept 90 days (scores and certificates stay). Your documents stay until you delete them. When you delete your account, your personal data is deleted straight away from our live systems and from backups within 30 days. Two exceptions: payment records are kept, without your name, for 8 years as tax law requires, and courses that other learners are already using stay available without your name on them.</p>

      <H>7. Your rights</H>
      <ul>
        <li><b>Access:</b> download everything we hold about you from <Link className="text-accent underline" to="/account">Account &amp; privacy</Link>.</li>
        <li><b>Correction:</b> edit your profile and settings any time.</li>
        <li><b>Erasure and withdrawing consent:</b> delete your account from <Link className="text-accent underline" to="/account">Account &amp; privacy</Link>, or write to us.</li>
        <li><b>Nomination:</b> you may name someone to exercise these rights if you die or become unable to.</li>
        <li><b>Grievances:</b> contact our Grievance Officer (below). If you are not satisfied with our response, you may complain to the Data Protection Board of India.</li>
      </ul>

      <H>8. Security</H>
      <p>Data travels over HTTPS. Passwords are hashed, and provider and payment keys are encrypted at rest. Access to production data is limited to people who need it. If a personal data breach occurs, we will inform affected users and the Data Protection Board as the law requires.</p>

      <H>9. Cookies and local storage</H>
      <p>We use only essential browser storage: it keeps you signed in and remembers your language, theme and mascot settings. We use no advertising or analytics cookies. During a payment, Razorpay's checkout may set its own cookies, under Razorpay's privacy policy.</p>

      <H>10. Grievance Officer</H>
      <GrievanceBlock />
      <p>We acknowledge complaints within 48 hours and aim to resolve them within 30 days.</p>

      <H>11. Changes</H>
      <p>If we make a material change, we will update the date above and ask you to accept the new version the next time you open {s.brand}.</p>
    </LegalLayout>
  );
}

export function TermsPage() {
  const s = useBiz();
  return (
    <LegalLayout title="Terms of Use">
      <p>These terms are an agreement between you and {s.entity} for the use of {s.brand}. By creating an account or using {s.brand}, you agree to them and to our <Link className="text-accent underline" to="/privacy">Privacy Policy</Link>.</p>

      <H>1. Who can use {s.brand}</H>
      <p>Anyone can learn on {s.brand}. If you are under 18, a parent or lawful guardian must agree to these terms for you and is responsible for your use of the service.</p>

      <H>2. Your account</H>
      <p>Give accurate details, keep your password private, and don't share your account. You are responsible for activity on it. Tell us straight away if you think someone else has used it.</p>

      <H>3. The AI mentor</H>
      <p>{s.brand} uses artificial intelligence to explain topics, create courses and practice, grade answers and hold conversations. AI can be wrong, incomplete or out of date. Check anything important, and don't rely on {s.brand} for medical, legal, financial or other professional advice. {s.brand} helps you learn; it does not replace your teachers or guarantee exam results.</p>

      <H>4. Fair use</H>
      <ul>
        <li>Use {s.brand} to learn, not to pass off AI-written work as your own where that breaks your school's or exam board's rules.</li>
        <li>Don't upload content you don't have the right to share, or anything illegal, hateful, sexual involving minors, harassing or harmful.</li>
        <li>Don't try to break, overload, scrape or reverse-engineer the service, get around plan limits, or access other people's data.</li>
        <li>Don't use {s.brand} to produce spam, malware or misleading content.</li>
      </ul>

      <H>5. Your content</H>
      <p>What you write and upload stays yours. You give us permission to store and process it only so we can provide {s.brand} to you, including sending it to our AI providers as described in the Privacy Policy. If you publish a course, people you share it with may use it, and learners already enrolled may keep using it even after you delete your account.</p>

      <H>6. Organizations</H>
      <p>Schools, colleges, coaching centres and companies that create an organization on {s.brand} must have the right to invite their members. They must use members' learning data only for education or training purposes.</p>

      <H>7. Plans and payments</H>
      <ul>
        <li>The Free plan has the usage limits shown on the Plans page. Paid plans raise them for the period you buy.</li>
        <li>Prices are in Indian Rupees and include GST. Payments are one-time payments for a fixed number of days. Nothing renews automatically.</li>
        <li>We may change prices or limits for future purchases. A period you have already paid for is not affected.</li>
        <li>Refunds follow our <Link className="text-accent underline" to="/refunds">Refund &amp; Cancellation Policy</Link>.</li>
      </ul>

      <H>8. Our rights</H>
      <p>The {s.brand} name, the Kili mascot, the software and our original content belong to {s.entity}. We may change, add or remove features. We may suspend or close accounts that break these terms, and we will tell you why unless the law prevents us.</p>

      <H>9. Liability</H>
      <p>We work hard to keep {s.brand} available and accurate, but it is provided “as is”. To the extent the law allows, we are not liable for indirect or consequential losses. Our total liability to you is limited to the amount you paid us in the 3 months before the claim. Nothing here limits rights you have under the Consumer Protection Act, 2019.</p>

      <H>10. Law and disputes</H>
      <p>These terms are governed by the laws of India. Please contact us first so we can try to resolve any problem. Otherwise, the courts at {s.city} have jurisdiction.</p>

      <H>11. Contact and grievances</H>
      <GrievanceBlock />
    </LegalLayout>
  );
}

export function RefundsPage() {
  const s = useBiz();
  return (
    <LegalLayout title="Refund & Cancellation Policy">
      <H>What you buy</H>
      <p>{s.brand} plans are digital services. Your plan is activated immediately after a successful payment, and nothing physical is shipped. Each payment buys access for a fixed number of days, shown at checkout.</p>

      <H>Cancellation</H>
      <p>Plans never renew automatically, so there is nothing to cancel. When your period ends, your account moves back to the Free plan, and everything you created stays.</p>

      <H>Refunds</H>
      {s.refund_days > 0 ? (
        <p>If you're not happy, ask for a refund within <b>{s.refund_days} days</b> of payment and we'll refund the full amount. Write to {s.support_email || "our support email"} with your registered email and Razorpay payment ID (shown on the Plans page). After {s.refund_days} days, payments are not refundable for the unused part of the period, except where the law requires.</p>
      ) : (
        <p>Payments are not refundable for the unused part of a period, except for failed or duplicate payments (below) or where the law requires.</p>
      )}

      <H>Failed or duplicate payments</H>
      <p>If money left your account but your plan wasn't activated, or you were charged twice, the extra amount is refunded in full. Razorpay automatically refunds payments that were not completed. If anything is still missing, write to us and we'll fix it.</p>

      <H>Timeline</H>
      <p>Approved refunds are processed within 5–7 working days to the original payment method. Your bank or UPI app may take a few more days to show it.</p>

      <H>Contact</H>
      <GrievanceBlock />
    </LegalLayout>
  );
}

export function ContactPage() {
  const s = useBiz();
  return (
    <LegalLayout title="Contact us">
      <p>We'd love to hear from you, whether it's a question, feedback or a problem.</p>
      <ul>
        <li><b>Business:</b> {s.entity}</li>
        {s.address && <li><b>Address:</b> {s.address}</li>}
        {s.support_email && <li><b>Support:</b> <a className="text-accent underline" href={`mailto:${s.support_email}`}>{s.support_email}</a></li>}
        {s.phone && <li><b>Phone:</b> {s.phone}</li>}
        {s.gstin && <li><b>GSTIN:</b> {s.gstin}</li>}
      </ul>
      <H>Grievance Officer</H>
      <GrievanceBlock />
      <p>We reply within 2 working days.</p>
    </LegalLayout>
  );
}

export function DpaPage() {
  const s = useBiz();
  const { data } = useQuery({ queryKey: ["subprocessors"], queryFn: () => api<{ version: string; subprocessors: { name: string; location: string; purposes: string[] }[] }>("/api/legal/subprocessors/") });
  return (
    <LegalLayout title="Data Processing Agreement">
      <p>This Data Processing Agreement (“DPA”) applies when a school, college, coaching centre or company (the “Organization”) uses {s.brand} for its members. The Organization is the <b>Data Fiduciary</b> for its members' personal data, and {s.entity} acts as its <b>Data Processor</b> under India's Digital Personal Data Protection Act, 2023. It is accepted by an owner or admin of the Organization in the {s.brand} dashboard.{data && <> Version {data.version}.</>}</p>

      <H>1. What we process</H>
      <ul>
        <li><b>Members:</b> learners, teachers and admins the Organization invites or who join with its class code.</li>
        <li><b>Data:</b> names, email addresses, roles and classes, learning progress, scores, assignment completion and survey answers (anonymous surveys without names).</li>
        <li><b>Not shared with the Organization:</b> members' private mentor chats, role-plays, Live Class transcripts and uploaded notes.</li>
      </ul>

      <H>2. Purpose and instructions</H>
      <p>We process this data only to provide {s.brand} to the Organization and its members: lessons, assignments, analytics, surveys and support. We follow the Organization's documented instructions, which are given through the product settings and this DPA. We don't sell the data, show ads, or use it to train AI models.</p>

      <H>3. Confidentiality and security</H>
      <ul>
        <li>Staff with access are bound by confidentiality and get only the access they need.</li>
        <li>Data is encrypted in transit (HTTPS); passwords are hashed; provider and payment keys are encrypted at rest.</li>
        <li>Role-based access separates owners, admins, teachers and learners; every endpoint enforces it on the server.</li>
        <li>Rate limits, audit-friendly logs and regular security reviews protect the service.</li>
      </ul>

      <H>4. Sub-processors</H>
      <p>The Organization authorises the following sub-processors, which are bound by data-protection terms at least as protective as this DPA. We will update this list before adding a new one, and the Organization may object.</p>
      <div className="overflow-x-auto">
        <table className="mt-3 w-full text-sm">
          <thead className="text-left text-muted"><tr><th className="py-1">Sub-processor</th><th>Purpose</th><th>Location</th></tr></thead>
          <tbody>
            {(data?.subprocessors ?? []).map((p) => <tr key={p.name} className="border-t border-line"><td className="py-1.5">{p.name}</td><td>{p.purposes.join(", ")}</td><td>{p.location}</td></tr>)}
            <tr className="border-t border-line"><td className="py-1.5">Hosting provider</td><td>Servers, database and backups</td><td>As notified to the Organization</td></tr>
          </tbody>
        </table>
      </div>

      <H>5. Personal data breaches</H>
      <p>We will tell the Organization without undue delay, and in any case within 72 hours, after becoming aware of a breach affecting its members' data. The notice will say what happened, the likely impact and what we are doing. We will help the Organization meet its own duties to inform the Data Protection Board of India and affected members.</p>

      <H>6. Members' rights</H>
      <p>We help the Organization answer members' requests to access, correct or erase their data. Members can also download or delete their own data directly from Account &amp; privacy.</p>

      <H>7. Children</H>
      <p>Where members are under 18, the Organization confirms it has the verifiable consent of a parent or lawful guardian, or another lawful basis under the DPDP Act. {s.brand} doesn't track children for advertising or show them targeted ads.</p>

      <H>8. Transfers outside India</H>
      <p>Some sub-processors (such as AI providers) may process data outside India. We use them only where the transfer is lawful under the DPDP Act and to countries not restricted by the Government of India.</p>

      <H>9. Deletion and return</H>
      <p>When the Organization stops using {s.brand} or asks us to, we will delete or return its members' organization data within 30 days, except where the law requires us to keep it (for example, tax records). Members' personal accounts remain theirs unless they delete them.</p>

      <H>10. Audits</H>
      <p>On reasonable written notice (not more than once a year, unless after a breach), we will provide the information needed to show compliance with this DPA.</p>

      <H>11. Term and law</H>
      <p>This DPA lasts as long as we process the Organization's data. It is governed by the laws of India, and the courts at {s.city} have jurisdiction.</p>

      <H>Contact</H>
      <GrievanceBlock />
    </LegalLayout>
  );
}
