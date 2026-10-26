import { Link } from "../components/link";

export function NotFound() {
  return (
    <article>
      <p className="eyebrow">404</p>
      <h1>This page is not part of Onboard Studio</h1>
      <p>The address does not match any view. Start from the landing page or open the case timeline.</p>
      <p className="actions"><Link to="" className="btn">Landing page</Link> <Link to="cases" className="btn btn--primary">Case timeline</Link></p>
    </article>
  );
}
