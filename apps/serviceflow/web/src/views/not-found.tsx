import { Link } from "../components/link";
export function NotFound() {
  return (
    <article>
      <p className="eyebrow">No such route</p>
      <h1>Not found</h1>
      <p>This address is not one of the ServiceFlow routes.</p>
      <p><Link to="" className="btn btn--primary">Back to the start</Link></p>
    </article>
  );
}
