/** A business-rule violation with a stable machine-readable code (domain/serviceflow/errors.py). */
export class DomainError extends Error {
  readonly code: string;
  readonly path: string | null;
  constructor(code: string, message: string, path: string | null = null) {
    super(`${code}: ${message}`);
    this.name = "DomainError";
    this.code = code;
    this.path = path;
  }
}
