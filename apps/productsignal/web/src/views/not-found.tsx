import { Link } from "../components/link";
import { ViewHead } from "../components/ui";

export function NotFound() {
  return (
    <>
      <ViewHead eyebrow="404" title="Not found"><p className="lede">There is no such page in this lab. <Link to="">Go to the start</Link>.</p></ViewHead>
    </>
  );
}
