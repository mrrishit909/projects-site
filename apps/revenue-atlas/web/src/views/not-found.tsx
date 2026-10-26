import { Link } from "../components/link";

export function NotFound() {
  return (
    <section>
      <p className="eyebrow">404</p>
      <h1 className="display">This page is not in the atlas</h1>
      <p className="lede">The address does not match any screen of this demo.</p>
      <p><Link to="" className="btn">Back to the start</Link></p>
    </section>
  );
}
