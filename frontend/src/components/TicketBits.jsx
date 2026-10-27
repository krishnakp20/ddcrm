import { Badge } from "./ui";

export const PRIORITIES = [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["urgent", "Urgent"]];
export const STATUSES = [["open", "Open"], ["in_progress", "In progress"], ["pending", "Pending"], ["resolved", "Resolved"], ["closed", "Closed"]];
const P_TONE = { low: "", medium: "primary", high: "warn", urgent: "danger" };
const S_TONE = { open: "primary", in_progress: "warn", pending: "", resolved: "success", closed: "" };

export const PriorityBadge = ({ priority }) => <Badge tone={P_TONE[priority]}>{PRIORITIES.find(([k]) => k === priority)?.[1] || priority}</Badge>;
export const TicketStatus = ({ status }) => <Badge tone={S_TONE[status]}>{STATUSES.find(([k]) => k === status)?.[1] || status}</Badge>;

/** "2h left", "3d overdue", "Met" - the SLA at a glance. */
export function SlaChip({ sla, due }) {
  if (sla === "none" || !due) return <span className="muted small">—</span>;
  const diff = new Date(due).getTime() - Date.now();
  const span = (ms) => {
    const m = Math.round(Math.abs(ms) / 60000);
    if (m < 60) return `${m}m`;
    if (m < 60 * 48) return `${Math.round(m / 60)}h`;
    return `${Math.round(m / 1440)}d`;
  };
  if (sla === "met") return <Badge tone="success">SLA met</Badge>;
  if (sla === "breached") return <Badge tone="danger">{diff < 0 ? `${span(diff)} overdue` : "SLA missed"}</Badge>;
  return <Badge tone={sla === "due_soon" ? "warn" : ""}>{span(diff)} left</Badge>;
}

const SOURCE = { website: "Website", whatsapp: "WhatsApp", email: "Email", call: "Call" };
/** Where a ticket came from; nothing is shown for tickets typed in by hand. */
export const SourceChip = ({ source }) => (SOURCE[source] ? <Badge tone="primary">{SOURCE[source]}</Badge> : null);
