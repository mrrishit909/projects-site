// Secret redaction for structured logs and evidence (D-03, P08-TEST-11). A redaction check runs on every log line and fails closed.
export const REDACTED = "[REDACTED]";
export const WITHHELD = "[LOG LINE WITHHELD: a secret pattern survived redaction]";
const SECRET_KEYS = /(?<![a-z])(pass(word|wd)?|secrets?|tokens?|api[_-]?keys?|apikey|authorization|auth|credentials?|private[_-]?key|access[_-]?key|cookie|session[_-]?id|dsn|connection[_-]?string)(?![a-z])/i;
const P = {
  bearer: /\bbearer\s+[A-Za-z0-9._~+/=-]{8,}/gi,
  basic: /\bbasic\s+[A-Za-z0-9+/=]{12,}/gi,
  url_credentials: /\b([a-z][a-z0-9+.-]*:\/\/)([^/\s:@]+):([^/\s@]+)@/gi,
  key_value: /\b(pass(?:word|wd)?|secret|token|api[_-]?key|apikey|authorization|access[_-]?key|private[_-]?key|client[_-]?secret)(["']?\s*[=:]\s*)(?!["']?\[REDACTED\])("[^"]*"|'[^']*'|[^\s,;&"'}]+)/gi,
};
const REST: RegExp[] = [/\b(AKIA|ASIA)[0-9A-Z]{16}\b/g, /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, /\bgithub_pat_[A-Za-z0-9_]{20,}\b/g, /\bxox[abprs]-[A-Za-z0-9-]{10,}\b/g,
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, /-----BEGIN [A-Z ]*PRIVATE KEY-----/g];

/** Replace every secret-looking span of a log line with [REDACTED] (the key name and the surrounding text stay). */
export function redactText(text: string): string {
  let out = text;
  out = out.replace(P.bearer, REDACTED).replace(P.basic, REDACTED);
  out = out.replace(P.url_credentials, (_m, a: string, b: string) => `${a}${b}:${REDACTED}@`);
  out = out.replace(P.key_value, (_m, a: string, b: string) => `${a}${b}${REDACTED}`);
  for (const re of REST) out = out.replace(re, REDACTED);
  return out;
}
/** True if `text` still carries a secret pattern. A span already replaced by [REDACTED] is stable, so "redacting changes nothing" = "none left". */
export const containsSecret = (text: string): boolean => redactText(text) !== text;
/** Redact a JSON-like value: secret-named keys are replaced whole, strings are scrubbed, containers are walked. */
export function redactValue(value: unknown, key = ""): unknown {
  if (key && SECRET_KEYS.test(key) && value !== null && value !== undefined) return REDACTED;
  if (Array.isArray(value)) return value.map((v) => redactValue(v, key));
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redactValue(v, k)]));
  return typeof value === "string" ? redactText(value) : value;
}
/** The structured-log check: redact, then verify nothing survived; a line that still fails is withheld whole (fail closed). */
export function safeLine(line: string): string { const clean = redactText(line); return containsSecret(clean) ? WITHHELD : clean; }
