import { Link } from "../components/link";

export function NotFound() {
  return (
    <article>
      <p className="eyebrow">404</p>
      <h1>This page is not part of SupplyScope</h1>
      <p>The address does not match any view. Start from the landing page or open the reorder workbench.</p>
      <p className="actions"><Link to="" className="btn">Landing page</Link> <Link to="reorder" className="btn btn--primary">Reorder workbench</Link></p>
    </article>
  );
}
