import { Link } from "../components/link";

export function NotFound() {
  return (
    <section>
      <h1>Not found</h1>
      <p>There is no page at this address. The lab has twelve routes; start from <Link to="">the start page</Link>.</p>
    </section>
  );
}
