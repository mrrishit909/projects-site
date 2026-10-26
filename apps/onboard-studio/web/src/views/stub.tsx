import type { RouteDef } from "../routes";

/** Placeholder for a route whose view is built in the next part. */
export function Stub({ route }: { route: RouteDef }) {
  return (
    <article>
      <p className="eyebrow">Route /{route.path}/</p>
      <h1>{route.title}</h1>
      <p className="muted">In progress</p>
    </article>
  );
}
