'use client';

import {
  AlertTriangle,
  BarChart3,
  ClipboardList,
  Inbox,
  LifeBuoy,
  Lightbulb,
  ListChecks,
  Lock,
  Megaphone,
  Rocket,
  Route,
  ScrollText,
  Settings,
  Tags,
  UserCog,
  Users,
} from 'lucide-react';
import { StateBadge } from '@/components/shared/ui';
import type { ConversationStateWire } from '@/types/api';

type Tone = 'features' | 'best' | 'watch';

type TipGroup = {
  label: string;
  tone: Tone;
  items: string[];
};

type Workflow = {
  title: string;
  steps: string[];
};

type HelpSection = {
  id: string;
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  accent: string; // chip background + text classes
  adminOnly?: boolean;
  intro: string;
  states?: ConversationStateWire[];
  groups: TipGroup[];
  workflow?: Workflow;
};

const TONE_STYLES: Record<
  Tone,
  { icon: React.ComponentType<{ className?: string }>; iconClass: string; dotClass: string }
> = {
  features: { icon: ListChecks, iconClass: 'text-blue-600', dotClass: 'bg-blue-400' },
  best: { icon: Lightbulb, iconClass: 'text-amber-600', dotClass: 'bg-amber-400' },
  watch: { icon: AlertTriangle, iconClass: 'text-rose-600', dotClass: 'bg-rose-400' },
};

const SECTIONS: HelpSection[] = [
  {
    id: 'getting-started',
    title: 'Getting Started',
    icon: Rocket,
    accent: 'bg-indigo-100 text-indigo-700',
    intro:
      'EngageOS is a WhatsApp CRM for handling customer conversations at scale. Inbound messages land in the Inbox, where an AI assistant can reply automatically or hand off to a human agent. Outbound campaigns, contacts, templates, and analytics all support that core conversation workflow.',
    groups: [
      {
        label: 'What you can do',
        tone: 'features',
        items: [
          'Read and reply to every WhatsApp conversation from one Inbox.',
          'Let the AI handle routine replies, and take over the moment a human is needed.',
          'Reach out first with templated campaigns and one-off messages.',
          'Keep contacts, tags, and analytics organized around those conversations.',
        ],
      },
      {
        label: 'Good habits',
        tone: 'best',
        items: [
          'Live in the Inbox day to day — most work flows through it.',
          'New here? Read Inbox first, then Contacts and Templates.',
          'Ask an admin for access if Analytics, Users, or Audit Logs are blocked for you.',
        ],
      },
    ],
    workflow: {
      title: 'A customer message, end to end',
      steps: [
        'A customer messages your WhatsApp number.',
        'The conversation appears in the Inbox marked NEW.',
        'The AI activates and either sends a reply or drafts one for approval (per your Settings).',
        'If it needs a person, you click Take Over and reply by hand.',
        'Once the issue is resolved, you Close the conversation.',
      ],
    },
  },
  {
    id: 'inbox',
    title: 'Inbox',
    icon: Inbox,
    accent: 'bg-blue-100 text-blue-700',
    intro:
      'The Inbox is the live view of every WhatsApp conversation. Each thread shows its current state, full message history, and the contact it belongs to. Reply directly, take over from the AI, or start a brand-new outbound conversation.',
    states: ['NEW', 'AI_ACTIVE', 'AWAITING_APPROVAL', 'HUMAN_ASSIGNED', 'AI_PAUSED', 'CLOSED'],
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'Live thread list with the current state shown on every conversation.',
          'Take Over pauses the AI and assigns the conversation to you.',
          'Quick reply box for free-form text inside the 24-hour window.',
          'New Message starts an outbound conversation with any contact.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Check the state and assignee before jumping into a thread.',
          'Close conversations when resolved so your queue reflects real open work.',
          'Use Take Over before replying by hand so the AI does not reply over you.',
        ],
      },
      {
        label: 'Watch out',
        tone: 'watch',
        items: [
          'A conversation locked by another agent cannot be edited by you.',
          'Outside the 24-hour window you must pick an approved Template — free text is blocked.',
        ],
      },
    ],
    workflow: {
      title: 'Handle an incoming conversation',
      steps: [
        'Open the thread from the Inbox list.',
        'Read the history and check the state badge to see who is in control.',
        'Click Take Over to pause the AI and assign it to yourself.',
        'Type your reply and send it.',
        'Click Close once the customer is taken care of.',
      ],
    },
  },
  {
    id: 'contacts',
    title: 'Contacts',
    icon: Users,
    accent: 'bg-emerald-100 text-emerald-700',
    intro:
      'Contacts is your customer directory. Browse, search, and filter the people you talk to, edit their details, and act on many at once with bulk actions. Contacts are also created automatically when someone messages you.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'Search and filter to narrow large lists fast.',
          'Select multiple rows for bulk actions.',
          'Bulk-assign an agent or bulk-delete in one step.',
          'Import contacts in bulk from a CSV file.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Keep names and tags accurate — campaigns and analytics rely on clean data.',
          'Filter down to the exact segment before running a bulk action.',
          'For big imports, let the background job finish before relying on the new rows.',
        ],
      },
    ],
    workflow: {
      title: 'Assign a segment to an agent',
      steps: [
        'Filter or search to the contacts you want (e.g. a tag or region).',
        'Tick the checkbox on each matching row, or select all.',
        'Open Bulk actions and choose Assign agent.',
        'Pick the agent — those conversations are now routed to them.',
      ],
    },
  },
  {
    id: 'campaigns',
    title: 'Campaigns',
    icon: Megaphone,
    accent: 'bg-orange-100 text-orange-700',
    intro:
      'Campaigns send outbound WhatsApp messages to a defined audience on a schedule. They respect throttle limits and compliance gates so you stay within WhatsApp policy and rate limits.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'Target a specific audience of contacts.',
          'Send with an approved template, one-off or recurring.',
          'Global and per-campaign throttling rolls sends out gradually.',
          'Compliance gates enforce the 24-hour window and template rules.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Test with a small audience before launching a broad send.',
          'Double-check the template status is Approved before scheduling.',
          'Schedule during business hours so replies can be handled live.',
        ],
      },
      {
        label: 'Watch out',
        tone: 'watch',
        items: [
          'Compliance gates will block sends that violate policy — fix the cause, do not retry blindly.',
          'A large send rolls out over time; it will not all leave at once.',
        ],
      },
    ],
    workflow: {
      title: 'Launch a campaign safely',
      steps: [
        'Pick an approved template for the message.',
        'Define the audience of contacts to reach.',
        'Run a test against a small audience and confirm delivery.',
        'Set the schedule (one-off or recurring) and launch.',
        'Watch the throttled rollout and answer replies in the Inbox.',
      ],
    },
  },
  {
    id: 'templates',
    title: 'Templates',
    icon: ClipboardList,
    accent: 'bg-violet-100 text-violet-700',
    intro:
      'Templates are pre-approved WhatsApp message formats required to start a conversation or message a contact outside the 24-hour service window. Import them from Meta and track their approval status here.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'Import templates straight from your WhatsApp Business Account on Meta.',
          'See each template’s latest approval status at a glance.',
          'Open a template to read its body and details before using it.',
          'Use approved templates in campaigns and new messages.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Confirm the status badge says Approved before relying on a template.',
          'Re-import after editing in Meta so statuses stay in sync.',
        ],
      },
      {
        label: 'Watch out',
        tone: 'watch',
        items: [
          'Inside the 24-hour window you can send free text; outside it a template is mandatory.',
          'Only Meta-approved templates can actually be sent.',
        ],
      },
    ],
    workflow: {
      title: 'Get a template ready to use',
      steps: [
        'Create and submit the template inside Meta.',
        'Come back and click Import from Meta.',
        'Wait until the status badge reads Approved.',
        'Select it in a campaign or a new Inbox message.',
      ],
    },
  },
  {
    id: 'tag-review',
    title: 'Tag Review',
    icon: Tags,
    accent: 'bg-pink-100 text-pink-700',
    intro:
      'Tag Review is where AI-suggested tags for contacts and conversations are approved or rejected. It keeps your taxonomy accurate by putting a human in the loop before tags are applied.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'See AI tag suggestions with the context that triggered them.',
          'Approve fitting suggestions or reject the ones that miss.',
          'Every decision is recorded for audit.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Review regularly so suggestions do not pile up.',
          'Reject low-quality tags promptly to keep the taxonomy clean.',
          'Manage the underlying tag list under Settings → Tags.',
        ],
      },
    ],
    workflow: {
      title: 'Clear the suggestion queue',
      steps: [
        'Open Tag Review.',
        'Read each suggestion alongside its conversation or contact.',
        'Click Approve or Reject.',
        'Tweak the tag list itself in Settings → Tags if a tag is missing or wrong.',
      ],
    },
  },
  {
    id: 'analytics',
    title: 'Analytics',
    icon: BarChart3,
    accent: 'bg-cyan-100 text-cyan-700',
    adminOnly: true,
    intro:
      'Analytics summarizes daily activity and campaign performance, including ROI attribution. Metrics are rolled up nightly, so the most recent numbers update once the overnight aggregation runs.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'Daily activity metrics across conversations and messages.',
          'Per-campaign performance and ROI.',
          'Last-touch attribution over a rolling 30-day window.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Read yesterday’s numbers as final; today’s may lag until the rollup runs.',
          'Compare campaigns over the same window for a fair read.',
        ],
      },
      {
        label: 'Watch out',
        tone: 'watch',
        items: ['Admin only — if the page is blocked, ask an administrator for access.'],
      },
    ],
    workflow: {
      title: 'Measure a campaign’s impact',
      steps: [
        'Wait for the overnight rollup so the campaign’s day is included.',
        'Open Analytics and find the campaign.',
        'Read its ROI, attributed by last touch over 30 days.',
      ],
    },
  },
  {
    id: 'settings',
    title: 'Settings',
    icon: Settings,
    accent: 'bg-slate-200 text-slate-700',
    intro:
      'Settings controls how the CRM behaves — AI toggles, operational switches, your tag taxonomy, and campaign categories. Every change here is audited.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'AI toggles: send replies automatically, or only draft them for approval.',
          'Operational toggles to pause or limit automation during incidents.',
          'Tag taxonomy management under Settings → Tags.',
          'Campaign organization under Settings → Campaign Categories.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Use approval mode when you want a human to vet every AI reply.',
          'Flip operational toggles off during an incident, then back on once stable.',
          'Check the Audit Logs to confirm a change took effect.',
        ],
      },
    ],
    workflow: {
      title: 'Switch the AI to approval mode',
      steps: [
        'Open Settings.',
        'Turn off auto-send so the AI drafts instead of sending.',
        'New AI replies now arrive in the Inbox as AWAITING_APPROVAL.',
        'Approve or edit each draft from the conversation.',
        'The change is recorded in Audit Logs automatically.',
      ],
    },
  },
  {
    id: 'users',
    title: 'Users',
    icon: UserCog,
    accent: 'bg-teal-100 text-teal-700',
    adminOnly: true,
    intro:
      'Users manages the agents and administrators who can access the CRM, along with their roles.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'Create agents and administrators.',
          'Set each person’s role and access level.',
          'New agents become assignable on conversations and bulk contact actions.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Grant admin sparingly — admins reach Analytics, Users, and Audit Logs.',
          'Remove access promptly when someone leaves the team.',
        ],
      },
      {
        label: 'Watch out',
        tone: 'watch',
        items: ['Admin only — non-admins cannot open this page.'],
      },
    ],
    workflow: {
      title: 'Add a new agent',
      steps: [
        'Open Users and create the account.',
        'Assign the Agent role.',
        'They can now be assigned conversations and appear in bulk-assign.',
      ],
    },
  },
  {
    id: 'audit-logs',
    title: 'Audit Logs',
    icon: ScrollText,
    accent: 'bg-amber-100 text-amber-700',
    adminOnly: true,
    intro:
      'Audit Logs is a searchable history of who did what across the CRM — assignments, approvals, settings changes, and more. Use it to investigate and stay accountable.',
    groups: [
      {
        label: 'Key features',
        tone: 'features',
        items: [
          'Searchable record of actions across the system.',
          'Each entry shows the user, the action, and the time.',
          'Read-only — entries cannot be edited or deleted.',
        ],
      },
      {
        label: 'Best practices',
        tone: 'best',
        items: [
          'Start here when reviewing how a conversation or setting reached its state.',
          'Filter by user or time range to zero in on an event.',
        ],
      },
      {
        label: 'Watch out',
        tone: 'watch',
        items: ['Admin only — ask an administrator if you need to investigate.'],
      },
    ],
    workflow: {
      title: 'Investigate a change',
      steps: [
        'Open Audit Logs.',
        'Search by the user, action, or time range in question.',
        'Open the entry to trace exactly who did what, and when.',
      ],
    },
  },
  {
    id: 'troubleshooting',
    title: 'Troubleshooting & FAQ',
    icon: LifeBuoy,
    accent: 'bg-rose-100 text-rose-700',
    intro:
      'Quick fixes for the most common issues. If something still does not work after these steps, contact your administrator.',
    groups: [
      {
        label: 'Common fixes',
        tone: 'features',
        items: [
          'Blank page or stuck loading → refresh; if it persists, sign out and back in.',
          'Cannot send a message → you may be outside the 24-hour window; send an approved Template.',
          'Cannot reply to a conversation → it is locked by another agent; confirm the assignee or Take Over.',
          'AI not responding → the conversation may be AI_PAUSED, or AI is disabled in Settings.',
        ],
      },
      {
        label: 'Access & permissions',
        tone: 'watch',
        items: [
          '“Insufficient permissions” → that section is admin-only; ask an admin for access.',
          'A page is missing from your sidebar → your role does not include it.',
        ],
      },
    ],
    workflow: {
      title: 'When a message won’t send',
      steps: [
        'Check whether the last customer message was over 24 hours ago.',
        'If so, open New Message and pick an approved Template instead of free text.',
        'Confirm the template’s status badge reads Approved.',
        'Still blocked? Check the conversation isn’t locked by another agent.',
      ],
    },
  },
];

function AdminBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
      <Lock className="h-3 w-3" />
      Admin only
    </span>
  );
}

export default function HelpPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Help &amp; Guide</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          How to use the EngageOS CRM — what each section does, the features you’ll reach for, best
          practices, and a short example workflow to follow.
        </p>
      </header>

      <div className="md:grid md:grid-cols-[210px_minmax(0,1fr)] md:gap-10">
        {/* Table of contents */}
        <nav className="mb-8 md:mb-0">
          <div className="md:sticky md:top-4">
            <p className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              On this page
            </p>
            <ul className="flex gap-2 overflow-x-auto pb-2 md:flex-col md:gap-1 md:overflow-visible md:pb-0">
              {SECTIONS.map(({ id, title, icon: Icon }) => (
                <li key={id} className="shrink-0">
                  <a
                    href={`#${id}`}
                    className="flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {title}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </nav>

        {/* Content */}
        <div className="space-y-6">
          {SECTIONS.map(
            ({ id, title, icon: Icon, accent, adminOnly, intro, states, groups, workflow }) => (
              <section
                key={id}
                id={id}
                className="scroll-mt-20 rounded-xl border bg-white p-6 shadow-sm"
              >
                {/* Header */}
                <div className="mb-3 flex items-center gap-3">
                  <span
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${accent}`}
                  >
                    <Icon className="h-5 w-5" />
                  </span>
                  <h2 className="text-lg font-semibold">{title}</h2>
                  {adminOnly ? <AdminBadge /> : null}
                </div>

                {/* Intro */}
                <p className="text-[15px] leading-relaxed text-slate-600">{intro}</p>

                {/* Conversation-state legend (Inbox only) */}
                {states ? (
                  <div className="mt-4 rounded-lg bg-muted/50 p-3">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Conversation states
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {states.map((s) => (
                        <StateBadge key={s} state={s} />
                      ))}
                    </div>
                  </div>
                ) : null}

                {/* Tip groups */}
                <div className="mt-5 grid gap-x-8 gap-y-5 md:grid-cols-2">
                  {groups.map((group) => {
                    const tone = TONE_STYLES[group.tone];
                    const ToneIcon = tone.icon;
                    return (
                      <div key={group.label}>
                        <div className="mb-2 flex items-center gap-2">
                          <ToneIcon className={`h-4 w-4 shrink-0 ${tone.iconClass}`} />
                          <h3 className="text-sm font-semibold">{group.label}</h3>
                        </div>
                        <ul className="space-y-2 text-sm leading-relaxed text-slate-600">
                          {group.items.map((item, i) => (
                            <li key={i} className="flex gap-2.5">
                              <span
                                className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${tone.dotClass}`}
                              />
                              <span>{item}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </div>

                {/* Example workflow */}
                {workflow ? (
                  <div className="mt-6 rounded-lg border border-dashed border-primary/20 bg-primary/[0.03] p-4">
                    <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary">
                      <Route className="h-4 w-4" />
                      Example workflow — {workflow.title}
                    </div>
                    <ol className="space-y-3">
                      {workflow.steps.map((step, i) => (
                        <li key={i} className="flex gap-3">
                          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
                            {i + 1}
                          </span>
                          <span className="pt-0.5 text-sm leading-relaxed text-slate-700">
                            {step}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
              </section>
            ),
          )}
        </div>
      </div>
    </div>
  );
}
