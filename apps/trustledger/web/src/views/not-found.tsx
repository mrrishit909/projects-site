import { Link } from "../components/link";
import { ViewHead } from "../components/ui";

export function NotFound() {
  return <ViewHead mark="Shelfmark unknown" title="Not found"><p className="lede">There is no such page in this library. <Link to="">Go to the start</Link>.</p></ViewHead>;
}
