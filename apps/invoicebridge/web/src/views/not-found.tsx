import { Link } from "../components/link";
import { ViewHead } from "../components/layout";

export function NotFound() {
  return (
    <>
      <ViewHead eyebrow="404" title="Not found"><p className="lede">There is no such page. <Link to="">Back to the start</Link>.</p></ViewHead>
    </>
  );
}
